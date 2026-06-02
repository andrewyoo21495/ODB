"""CKL-03-003: Shield can edge pads must be separated from fill-cut areas by > 0 mm.

Check process
-------------
1. Find shield can components on top and bottom layers.
2. For each shield can, build individual pad geometries and compute the
   minimum distance between every pair of pads.
3. If all pad-to-pad distances are >= 0.01 mm the component passes;
   otherwise it fails.

Columns: comp, cmp_layer, status
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

from src.checklist.component_classifier import find_shield_cans
from src.checklist.engine import register_rule
from src.checklist.geometry_utils.polygon import _outline_to_shapely
from src.checklist.rule_base import ChecklistRule
from src.models import Component, Package, RuleResult
from src.visualizer.component_overlay import transform_point

try:
    from shapely.geometry import Point as ShapelyPoint
    from shapely.ops import nearest_points
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False

_MIN_GAP_MM = 0.01  # minimum required pad-to-pad gap


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

    Pads without geometry data are represented by a small buffer around the
    pin centre so that distance calculations remain valid.
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


def _min_pad_gap(pad_geoms: list) -> tuple[float, int, int]:
    """Return (min_distance, idx_a, idx_b) for the closest pad pair.

    Returns (inf, -1, -1) when fewer than 2 pads exist.
    """
    n = len(pad_geoms)
    if n < 2:
        return float("inf"), -1, -1

    best_dist = float("inf")
    best_i, best_j = -1, -1
    for i in range(n):
        for j in range(i + 1, n):
            d = pad_geoms[i].distance(pad_geoms[j])
            if d < best_dist:
                best_dist = d
                best_i, best_j = i, j
    return best_dist, best_i, best_j


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


def _render_pad_gap_image(
    comp: Component,
    pkg: Package,
    pad_geoms: list,
    min_dist: float,
    idx_a: int,
    idx_b: int,
    is_bottom: bool,
    output_path: Path,
    *,
    rule_id: str,
) -> Path:
    """Render a shield can's pads, highlighting the closest pair."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    layer_str = "Bottom" if is_bottom else "Top"
    status = "PASS" if min_dist >= _MIN_GAP_MM else "FAIL"
    ax.set_title(
        f"{comp.comp_name} ({comp.part_name}) — {layer_str} Layer\n"
        f"{rule_id}: Pad-to-pad gap check  [{status}]",
        fontsize=12, fontweight="bold",
    )
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)

    # Collect extent for viewport
    all_xs, all_ys = [], []

    for i, geom in enumerate(pad_geoms):
        if i == idx_a or i == idx_b:
            if min_dist < _MIN_GAP_MM:
                fc, ec = "#FFB0B0", "darkred"
            else:
                fc, ec = "#90EE90", "darkgreen"
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

    # Draw distance line between the closest pair
    if idx_a >= 0 and idx_b >= 0:
        try:
            pa, pb = nearest_points(pad_geoms[idx_a], pad_geoms[idx_b])
            line_color = "red" if min_dist < _MIN_GAP_MM else "green"
            ax.plot(
                [pa.x, pb.x], [pa.y, pb.y],
                color=line_color, linewidth=2, linestyle="--", zorder=5,
            )
            mid_x = (pa.x + pb.x) / 2
            mid_y = (pa.y + pb.y) / 2
            ax.annotate(
                f"gap: {min_dist:.4f} mm",
                (mid_x, mid_y),
                textcoords="offset points", xytext=(12, 12),
                fontsize=8, fontweight="bold", color=line_color,
                bbox=dict(
                    boxstyle="round,pad=0.3", facecolor="white",
                    edgecolor=line_color, alpha=0.9,
                ),
                arrowprops=dict(arrowstyle="->", color=line_color, lw=1.0),
                zorder=6,
            )
        except Exception:
            pass

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
                       label="Shield can pad"),
    ]
    if min_dist >= _MIN_GAP_MM:
        legend_elements.append(
            mpatches.Patch(facecolor="#90EE90", edgecolor="darkgreen",
                           alpha=0.55, label="Closest pair (PASS)"))
        legend_elements.append(
            plt.Line2D([], [], color="green", linewidth=2, linestyle="--",
                       label=f"Min gap >= {_MIN_GAP_MM} mm"))
    else:
        legend_elements.append(
            mpatches.Patch(facecolor="#FFB0B0", edgecolor="darkred",
                           alpha=0.55, label="Closest pair (FAIL)"))
        legend_elements.append(
            plt.Line2D([], [], color="red", linewidth=2, linestyle="--",
                       label=f"Min gap < {_MIN_GAP_MM} mm"))
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
class CKL03003(ChecklistRule):
    rule_id = "CKL-03-003"
    description = (
        "실드캔 엣지 패드는 fill-cut 부와 0mm 초과 이격하여 설계할 것"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        columns = ["comp", "cmp_layer", "min_gap_mm", "status"]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_03_003_"))

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
            shield_cans = find_shield_cans(comps)

            for comp in shield_cans:
                if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
                    continue
                pkg = packages[comp.pkg_ref]
                if len(pkg.pins) < 2:
                    continue

                pad_geoms = _build_pad_geoms(
                    comp, pkg, is_bottom=is_bottom,
                )
                min_dist, idx_a, idx_b = _min_pad_gap(pad_geoms)

                status = "PASS" if min_dist >= _MIN_GAP_MM else "FAIL"
                rows.append({
                    "comp": comp.comp_name,
                    "cmp_layer": layer_name,
                    "min_gap_mm": f"{min_dist:.4f}",
                    "status": status,
                })

                # Generate visualisation image
                safe_name = comp.comp_name.replace("/", "_")
                img_path = image_dir / f"{safe_name}_{layer_name}.png"
                _render_pad_gap_image(
                    comp, pkg, pad_geoms,
                    min_dist, idx_a, idx_b,
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
                f"패드 간 간격이 {_MIN_GAP_MM}mm 미만인 실드캔이 "
                f"{fail_count}건 감지되었습니다."
                if not passed
                else "모든 실드캔의 패드 간 간격이 기준을 충족합니다."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
