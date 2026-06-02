"""CKL-03-006: Washer solder mask must not overlap with the bothhole solder mask.

Check process
-------------
1. Find washer components on top and bottom layers.
   (part_name starts with '3712-' OR comp_name starts with 'SUS')
2. For each washer, identify circular pads (CR / CT outline type).
3. Check whether each circular pad's geometry intersects/touches any other
   pad in the same component.  If the circular pad is isolated, the component
   passes; if it overlaps with any other pad, it fails.

Columns: comp, cmp_layer, part_name, status
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon as MplPolygon
import numpy as np

from src.checklist.component_classifier import find_washers
from src.checklist.engine import register_rule
from src.checklist.geometry_utils.polygon import _outline_to_shapely
from src.checklist.rule_base import ChecklistRule
from src.models import Component, Package, RuleResult
from src.visualizer.component_overlay import transform_point

try:
    from shapely.geometry import Point as ShapelyPoint
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False

# Buffer tolerance: pad geometries that are within this distance (mm) of each
# other are considered "touching" (overlapping).
_TOUCH_TOL_MM = 0.001


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _build_pad_geoms(
    comp: Component,
    pkg: Package,
    *,
    is_bottom: bool = False,
) -> list:
    """Return a list of Shapely geometries, one per pin, in board coordinates.

    Pads without usable geometry data are represented by a small buffer around
    the pin centre so that overlap calculations remain valid.
    """
    geoms: list = []
    for pin in pkg.pins:
        placed = False
        for outline in pin.outlines:
            g = _outline_to_shapely(outline, comp, is_bottom=is_bottom)
            if g is not None and not g.is_empty:
                geoms.append(g)
                placed = True
                break
        if not placed:
            bx, by = transform_point(
                pin.center.x, pin.center.y, comp, is_bottom=is_bottom,
            )
            geoms.append(ShapelyPoint(bx, by).buffer(0.02))
    return geoms


def _is_circular_pin(pin) -> bool:
    """Return True if the pin's first outline is circular (CR or CT)."""
    for outline in pin.outlines:
        return outline.type in ("CR", "CT")
    return False


def _check_circular_pad_overlap(
    pad_geoms: list,
    circular_indices: list[int],
) -> bool:
    """Return True if any circular pad overlaps/touches any other pad.

    Two pads are considered overlapping when their Shapely geometries
    intersect after a small tolerance buffer.
    """
    n = len(pad_geoms)
    for ci in circular_indices:
        circ_geom = pad_geoms[ci]
        # Slightly buffer the circular pad to catch "just touching" cases
        circ_buf = circ_geom.buffer(_TOUCH_TOL_MM)
        for j in range(n):
            if j == ci:
                continue
            if circ_buf.intersects(pad_geoms[j]):
                return True
    return False


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------

def _shapely_to_arrays(geom):
    """Yield (xs, ys) numpy arrays for each ring of a Shapely geometry."""
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        xs, ys = geom.exterior.xy
        yield np.array(xs), np.array(ys)
    elif geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        for part in geom.geoms:
            yield from _shapely_to_arrays(part)
    elif geom.geom_type in ("Point", "MultiPoint"):
        yield from _shapely_to_arrays(geom.buffer(0.02))


def _render_washer_image(
    comp: Component,
    pkg: Package,
    pad_geoms: list,
    circular_indices: list[int],
    has_overlap: bool,
    is_bottom: bool,
    output_path: Path,
    *,
    rule_id: str,
) -> Path:
    """Render a washer's pads, highlighting circular vs non-circular."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    layer_str = "Bottom" if is_bottom else "Top"
    status = "FAIL" if has_overlap else "PASS"
    ax.set_title(
        f"{comp.comp_name} ({comp.part_name}) — {layer_str} Layer\n"
        f"{rule_id}: Washer solder mask overlap check  [{status}]",
        fontsize=12, fontweight="bold",
    )
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)

    all_xs, all_ys = [], []
    circ_set = set(circular_indices)

    for i, geom in enumerate(pad_geoms):
        if i in circ_set:
            fc, ec = ("#FFB0B0", "darkred") if has_overlap else ("#90EE90", "darkgreen")
        else:
            fc, ec = "#D0D0D0", "gray"

        for xs, ys in _shapely_to_arrays(geom):
            verts = list(zip(xs, ys))
            ax.add_patch(MplPolygon(
                verts, closed=True,
                facecolor=fc, edgecolor=ec,
                alpha=0.55, linewidth=1.0,
            ))
            all_xs.extend(xs)
            all_ys.extend(ys)

    # Component centre
    ax.plot(comp.x, comp.y, "x", color="blue", markersize=10,
            markeredgewidth=2)

    # Viewport
    if all_xs and all_ys:
        cx = (max(all_xs) + min(all_xs)) / 2
        cy = (max(all_ys) + min(all_ys)) / 2
        span = max(max(all_xs) - min(all_xs),
                   max(all_ys) - min(all_ys), 0.5)
        margin = span * 0.3
        ax.set_xlim(cx - span / 2 - margin, cx + span / 2 + margin)
        ax.set_ylim(cy - span / 2 - margin, cy + span / 2 + margin)

    # Legend
    legend_elements = [
        mpatches.Patch(facecolor="#D0D0D0", edgecolor="gray", alpha=0.55,
                       label="Non-circular pad"),
    ]
    if has_overlap:
        legend_elements.append(
            mpatches.Patch(facecolor="#FFB0B0", edgecolor="darkred",
                           alpha=0.55, label="Circular pad (overlapping - FAIL)"))
    else:
        legend_elements.append(
            mpatches.Patch(facecolor="#90EE90", edgecolor="darkgreen",
                           alpha=0.55, label="Circular pad (isolated - PASS)"))
    ax.legend(handles=legend_elements, loc="upper left", fontsize=8)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


# ---------------------------------------------------------------------------
# Rule
# ---------------------------------------------------------------------------

@register_rule
class CKL03006(ChecklistRule):
    rule_id = "CKL-03-006"
    description = (
        "Washer solder mask 는 결합될 bothhole의 solder mask 와 "
        "overlap 되지 않도록 설계할 것"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        columns = ["comp", "cmp_layer", "part_name", "status"]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_03_006_"))

        if not _HAS_SHAPELY:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                category=self.category,
                passed=False,
                message="Shapely 라이브러리가 설치되어 있지 않습니다.",
            )

        for comps, layer_name, is_bottom in [
            (components_top, "Top", False),
            (components_bot, "Bottom", True),
        ]:
            washers = find_washers(comps)

            for comp in washers:
                if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
                    continue
                pkg = packages[comp.pkg_ref]
                if len(pkg.pins) < 2:
                    continue

                # Identify circular pin indices
                circular_indices = [
                    i for i, pin in enumerate(pkg.pins)
                    if _is_circular_pin(pin)
                ]

                if not circular_indices:
                    # No circular pad found — cannot evaluate; mark PASS
                    rows.append({
                        "comp": comp.comp_name,
                        "cmp_layer": layer_name,
                        "part_name": comp.part_name,
                        "status": "PASS",
                    })
                    continue

                pad_geoms = _build_pad_geoms(
                    comp, pkg, is_bottom=is_bottom,
                )

                has_overlap = _check_circular_pad_overlap(
                    pad_geoms, circular_indices,
                )

                status = "FAIL" if has_overlap else "PASS"
                rows.append({
                    "comp": comp.comp_name,
                    "cmp_layer": layer_name,
                    "part_name": comp.part_name,
                    "status": status,
                })

                # Generate visualisation image
                safe_name = comp.comp_name.replace("/", "_")
                img_path = image_dir / f"{safe_name}_{layer_name}.png"
                _render_washer_image(
                    comp, pkg, pad_geoms,
                    circular_indices, has_overlap,
                    is_bottom, img_path,
                    rule_id=self.rule_id,
                )
                images.append({
                    "path": img_path,
                    "title": f"{comp.comp_name} ({layer_name})",
                    "width": 500,
                })

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"동그란 패드가 다른 패드와 겹쳐있는 Washer 부품이 "
                f"{fail_count}건 감지되었습니다."
                if not passed
                else "모든 Washer 부품의 동그란 패드가 다른 패드와 분리되어 있습니다."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
