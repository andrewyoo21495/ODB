"""CKL-01-009: Interposer outer edge balls must have grouped solder mask.

Check process
-------------
1. Find interposer components on both top and bottom layers.
2. For each interposer, identify the outermost-ring pins.
3. On the corresponding solder mask layer (SMT / SMB), check whether
   adjacent outer pins share merged (grouped) pad openings.
4. Pins with grouped pads → PASS.
   Pins with normal (individual) pads that carry a non-GND signal → FAIL.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon as MplPolygon
import numpy as np

from src.checklist.component_classifier import find_interposers
from src.checklist.engine import register_rule
from src.checklist.geometry_utils.overlap import (
    find_outermost_pin_indices,
    transform_point,
)
from src.checklist.rule_base import ChecklistRule
from src.models import PadRecord, RuleResult

try:
    from shapely.geometry import Point as ShapelyPoint
    from shapely.ops import unary_union
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False

# Net names that are considered safe (ground)
_GND_KEYWORDS = ("GND", "GROUND", "VSS")


def _is_ground_net(net_name: str) -> bool:
    if not net_name:
        return False
    upper = net_name.strip().upper()
    return any(kw in upper for kw in _GND_KEYWORDS)


def _get_net_name(toeprint, eda_data) -> str:
    if eda_data is None or toeprint is None:
        return ""
    if toeprint.net_num < 0 or toeprint.net_num >= len(eda_data.nets):
        return ""
    return eda_data.nets[toeprint.net_num].name or ""


def _pick_soldermask_layer(layers_data: dict, *, is_bottom: bool):
    """Return (layer_name, LayerFeatures) for the side's solder mask."""
    if not layers_data:
        return None, None
    side_hints = (
        ("bottom", "_bot", "_b", "smb", "bot") if is_bottom
        else ("top", "_top", "_t", "smt")
    )
    for name, (lf, ml) in layers_data.items():
        if ml is None:
            continue
        if (ml.type or "").upper() != "SOLDER_MASK":
            continue
        if (ml.add_type or "").upper() == "COVERLAY":
            continue
        if any(h in name.lower() for h in side_hints):
            return name, lf
    return None, None


def _sm_pad_to_shapely(pad: PadRecord, symbols, user_symbols):
    """Build a Shapely geometry for a solder-mask PadRecord.

    Uses the symbol reference to determine shape and size, then applies
    position, rotation and mirror.
    """
    if not _HAS_SHAPELY:
        return None

    from src.checklist.geometry_utils.overlap import (
        _symbol_to_shapely,
        _user_symbol_to_shapely,
    )

    sym_idx = pad.symbol_idx
    geom = None

    # Try layer-level symbol table first.
    # Build geometry at origin (0, 0) with no rotation/mirror;
    # pad-level transforms are applied afterwards (lines below).
    if symbols and 0 <= sym_idx < len(symbols):
        sym = symbols[sym_idx]
        geom = _symbol_to_shapely(
            sym.name, 0.0, 0.0, 0.0, False,
            unit_override=getattr(sym, "unit_override", None),
        )

    # Fallback: user symbol table
    if geom is None and user_symbols:
        for us_name, us in user_symbols.items():
            geom = _user_symbol_to_shapely(us, 0.0, 0.0, 0.0, False)
            if geom is not None:
                break

    if geom is None:
        geom = ShapelyPoint(0, 0).buffer(0.15)

    # Apply rotation, mirror, translation
    import shapely.affinity as aff
    if pad.mirror:
        geom = aff.scale(geom, xfact=-1, origin=(0, 0))
    if pad.rotation:
        geom = aff.rotate(geom, pad.rotation, origin=(0, 0))
    geom = aff.translate(geom, xoff=pad.x, yoff=pad.y)
    return geom


def detect_grouped_outer_pins(
    comp, pkg, outer_indices, sm_features, symbols, user_symbols,
    *, is_bottom=False, merge_tol=0.02,
):
    """Determine which outermost pins have 'grouped' solder mask pads.

    Two adjacent outer pins are grouped if their solder-mask pad
    geometries overlap (or nearly touch within *merge_tol*).

    Returns a set of pin indices that are grouped.
    """
    if not _HAS_SHAPELY or not sm_features:
        return set()

    # Build board-coord centres of outer pins
    pin_positions: dict[int, tuple[float, float]] = {}
    for idx in outer_indices:
        if idx >= len(pkg.pins):
            continue
        pin = pkg.pins[idx]
        bx, by = transform_point(pin.center.x, pin.center.y, comp,
                                 is_bottom=is_bottom)
        pin_positions[idx] = (bx, by)

    if not pin_positions:
        return set()

    # Collect solder-mask PadRecords near pin positions
    from shapely.geometry import box as shapely_box
    all_xs = [p[0] for p in pin_positions.values()]
    all_ys = [p[1] for p in pin_positions.values()]
    pad_bbox = shapely_box(
        min(all_xs) - 1.0, min(all_ys) - 1.0,
        max(all_xs) + 1.0, max(all_ys) + 1.0,
    )

    sm_geoms = []
    for feat in sm_features:
        if not isinstance(feat, PadRecord):
            continue
        pt = ShapelyPoint(feat.x, feat.y)
        if not pad_bbox.contains(pt):
            continue
        g = _sm_pad_to_shapely(feat, symbols, user_symbols)
        if g is not None and not g.is_empty:
            sm_geoms.append(g)

    if not sm_geoms:
        return set()

    # Merge all SM pads (with small buffer tolerance) into connected clusters
    buffered = [g.buffer(merge_tol) for g in sm_geoms]
    merged = unary_union(buffered)

    # For each cluster, count how many outer pin positions it covers
    clusters = (
        list(merged.geoms)
        if hasattr(merged, "geoms")
        else [merged]
    )

    grouped: set[int] = set()
    for cluster in clusters:
        covered = [
            idx for idx, (bx, by) in pin_positions.items()
            if cluster.contains(ShapelyPoint(bx, by))
        ]
        if len(covered) >= 2:
            grouped.update(covered)

    return grouped


def _shapely_to_arrays(geom):
    """Yield (xs, ys) arrays for each ring of a Shapely geometry."""
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        xs, ys = geom.exterior.xy
        yield np.array(xs), np.array(ys)
    elif geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        for part in geom.geoms:
            yield from _shapely_to_arrays(part)
    elif geom.geom_type in ("Point", "MultiPoint"):
        yield from _shapely_to_arrays(geom.buffer(0.05))


def _render_interposer_image(
    comp,
    pkg,
    outer_indices: set[int],
    grouped_set: set[int],
    pin_results: list[dict],
    output_path: Path,
    *,
    rule_id: str,
    layer_name: str,
    is_bottom: bool = False,
) -> Path:
    """Render interposer outer pins coloured by grouped/normal status."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 10))

    has_fail = any(r["status"] == "FAIL" for r in pin_results)
    status_str = "FAIL" if has_fail else "PASS"
    ax.set_title(
        f"{comp.comp_name} ({comp.part_name}) — {layer_name} Layer\n"
        f"{rule_id}: Interposer outer ball grouped check  [{status_str}]",
        fontsize=12, fontweight="bold",
    )
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)

    all_xs, all_ys = [], []
    outer_set = set(outer_indices)

    # Draw all pins
    for idx, pin in enumerate(pkg.pins):
        bx, by = transform_point(
            pin.center.x, pin.center.y, comp, is_bottom=is_bottom,
        )
        all_xs.append(bx)
        all_ys.append(by)

        if idx not in outer_set:
            # Interior pin — dim grey
            ax.plot(bx, by, "o", color="#D0D0D0", markersize=3, zorder=2)
        elif idx in grouped_set:
            # Outer pin, grouped → green
            ax.plot(bx, by, "o", color="#4CAF50", markersize=5, zorder=3)
        else:
            # Outer pin, normal — check if it's GND (PASS) or signal (FAIL)
            matching = [
                r for r in pin_results
                if r["pin"] == pin.name and r["comp"] == comp.comp_name
            ]
            if matching and matching[0]["status"] == "FAIL":
                ax.plot(bx, by, "o", color="#F44336", markersize=6, zorder=4)
            else:
                ax.plot(bx, by, "o", color="#FFC107", markersize=5, zorder=3)

    # Component centre
    ax.plot(comp.x, comp.y, "x", color="blue", markersize=10,
            markeredgewidth=2, zorder=5)

    # Viewport
    if all_xs and all_ys:
        cx = (max(all_xs) + min(all_xs)) / 2
        cy = (max(all_ys) + min(all_ys)) / 2
        span = max(max(all_xs) - min(all_xs),
                   max(all_ys) - min(all_ys), 0.5)
        margin = span * 0.15
        ax.set_xlim(cx - span / 2 - margin, cx + span / 2 + margin)
        ax.set_ylim(cy - span / 2 - margin, cy + span / 2 + margin)

    # Legend
    legend_elements = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#D0D0D0",
                   markersize=6, label="Interior pin"),
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#4CAF50",
                   markersize=8, label="Outer pin (grouped - PASS)"),
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#FFC107",
                   markersize=8, label="Outer pin (normal - GND PASS)"),
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#F44336",
                   markersize=8, label="Outer pin (normal - FAIL)"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", fontsize=8)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


@register_rule
class CKL01009(ChecklistRule):
    rule_id = "CKL-01-009"
    description = (
        "Interposer edge의 외측 ball들이 묶음 구조(grouped) 적용되어 "
        "있는지 검토 (smt 또는 smb 층 확인)"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []
        layers_data = job_data.get("layers_data", {})
        user_symbols: dict = job_data.get("user_symbols") or {}

        columns = ["comp", "cmp_layer", "pin", "shape", "signal", "status"]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_01_009_"))

        for comps, layer in [(components_top, "Top"), (components_bot, "Bottom")]:
            is_bottom = layer == "Bottom"
            interposers = find_interposers(comps)
            if not interposers:
                continue

            # Get solder mask layer
            sm_name, sm_lf = _pick_soldermask_layer(layers_data, is_bottom=is_bottom)
            sm_features = sm_lf.features if sm_lf else []
            sm_symbols = sm_lf.symbols if sm_lf else []

            for inp in interposers:
                if inp.pkg_ref < 0 or inp.pkg_ref >= len(packages):
                    continue
                pkg = packages[inp.pkg_ref]
                if not pkg.pins:
                    continue

                outer_indices = find_outermost_pin_indices(pkg.pins)
                if not outer_indices:
                    continue

                # Detect grouped pins via solder mask analysis
                grouped_set = detect_grouped_outer_pins(
                    inp, pkg, outer_indices,
                    sm_features, sm_symbols, user_symbols,
                    is_bottom=is_bottom,
                )

                # Build toeprint lookup
                tp_by_name: dict[str, object] = {}
                for tp in inp.toeprints:
                    tp_by_name[tp.name] = tp

                comp_pin_results: list[dict] = []
                for idx in sorted(outer_indices):
                    pin = pkg.pins[idx]
                    is_grouped = idx in grouped_set
                    tp = tp_by_name.get(pin.name)
                    net_name = _get_net_name(tp, eda) if tp else ""

                    shape = "grouped" if is_grouped else "normal"

                    if is_grouped:
                        status = "PASS"
                    elif _is_ground_net(net_name):
                        # Normal but GND → still acceptable
                        status = "PASS"
                    else:
                        status = "FAIL"

                    row = {
                        "comp": inp.comp_name,
                        "cmp_layer": layer,
                        "pin": pin.name,
                        "shape": shape,
                        "signal": net_name or "(none)",
                        "status": status,
                    }
                    rows.append(row)
                    comp_pin_results.append(row)

                # Generate visualisation image for this interposer
                safe = inp.comp_name.replace("/", "_")
                img_path = image_dir / f"{safe}_{layer}.png"
                _render_interposer_image(
                    inp, pkg, outer_indices, grouped_set,
                    comp_pin_results, img_path,
                    rule_id=self.rule_id,
                    layer_name=layer,
                    is_bottom=is_bottom,
                )
                images.append({
                    "path": img_path,
                    "title": f"{inp.comp_name} ({layer})",
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
                f"인터포저 외측 볼 중 묶음 구조가 미적용된 시그널 핀이 "
                f"{fail_count}건 발견되었습니다."
                if not passed
                else "인터포저 외측 볼이 적절히 묶음 구조 적용되어 있습니다."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
