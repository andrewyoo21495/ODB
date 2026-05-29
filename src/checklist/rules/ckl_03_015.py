"""CKL-03-015: PCB outline clearance check.

Components and routing must be placed with a clearance of at least
0.65mm from the inner PCB outline.

- Top / Bottom layers: flags components whose **pads** intersect or fall
  within the clearance zone (component outline overlap is acceptable).
- Signal layers: identifies nets with copper features encroaching on the
  clearance zone.  (Currently commented out for verification.)

A result image is generated showing the board outline, the 0.65mm inset
boundary, the clearance zone, and any violating component pads.
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

from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    _get_pad_union,
    build_board_polygon,
    build_inset_boundary,
    components_with_pads_in_clearance_zone,
)
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


_CLEARANCE_MM = 0.65
_EXCLUDED_PREFIXES = ("ANT", "CN", "TP")


def _shapely_to_arrays(geom):
    """Yield (xs, ys) arrays for each ring of a Shapely geometry."""
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        xs, ys = geom.exterior.xy
        yield np.array(xs), np.array(ys)
        for interior in geom.interiors:
            ixs, iys = interior.xy
            yield np.array(ixs), np.array(iys)
    elif geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        for part in geom.geoms:
            yield from _shapely_to_arrays(part)


def _render_clearance_overview(
    board_poly,
    inset_poly,
    fail_comps,
    packages,
    output_path: Path,
    *,
    rule_id: str,
    layer_name: str,
    clearance_mm: float,
    user_symbols: dict | None = None,
) -> Path:
    """Render a board-level clearance overview image."""
    fig, ax = plt.subplots(1, 1, figsize=(12, 12))

    n_fail = len(fail_comps)
    status_str = "FAIL" if n_fail > 0 else "PASS"
    ax.set_title(
        f"{rule_id}: PCB Outline Clearance ({layer_name})\n"
        f"Clearance = {clearance_mm} mm — "
        f"{n_fail} violation(s)  [{status_str}]",
        fontsize=12, fontweight="bold",
    )
    ax.set_aspect("equal")

    # Board outline
    for xs, ys in _shapely_to_arrays(board_poly):
        ax.plot(xs, ys, color="royalblue", linewidth=1.5, zorder=2)

    # Inset boundary (dashed)
    for xs, ys in _shapely_to_arrays(inset_poly):
        ax.plot(xs, ys, color="darkorange", linewidth=1.2,
                linestyle="--", zorder=2)

    # Clearance zone fill (between board outline and inset)
    try:
        clearance_zone = board_poly.difference(inset_poly)
        for xs, ys in _shapely_to_arrays(clearance_zone):
            verts = list(zip(xs, ys))
            ax.add_patch(MplPolygon(
                verts, closed=True,
                facecolor="orange", edgecolor="none",
                alpha=0.15, zorder=1,
            ))
    except Exception:
        pass

    # FAIL component pads (red)
    for comp in fail_comps:
        is_bottom = (layer_name == "Bottom")
        pad_geom = _get_pad_union(comp, packages, is_bottom=is_bottom,
                                  user_symbols=user_symbols)
        if pad_geom is None:
            continue
        for xs, ys in _shapely_to_arrays(pad_geom):
            verts = list(zip(xs, ys))
            ax.add_patch(MplPolygon(
                verts, closed=True,
                facecolor="#FF6060", edgecolor="darkred",
                alpha=0.6, linewidth=0.6, zorder=3,
            ))
        ax.annotate(
            comp.comp_name, (comp.x, comp.y),
            fontsize=5, color="darkred", ha="center", va="bottom",
            zorder=4,
        )

    # Viewport from board polygon bounds
    bx0, by0, bx1, by1 = board_poly.bounds
    margin = max(bx1 - bx0, by1 - by0) * 0.05
    ax.set_xlim(bx0 - margin, bx1 + margin)
    ax.set_ylim(by0 - margin, by1 + margin)

    # Legend
    legend_elements = [
        plt.Line2D([], [], color="royalblue", linewidth=1.5,
                   label="Board outline"),
        plt.Line2D([], [], color="darkorange", linewidth=1.2, linestyle="--",
                   label=f"Inset boundary ({clearance_mm} mm)"),
        mpatches.Patch(facecolor="orange", alpha=0.15,
                       label="Clearance zone"),
        mpatches.Patch(facecolor="#FF6060", edgecolor="darkred", alpha=0.6,
                       label="Violating pads (FAIL)"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", fontsize=8)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.grid(True, alpha=0.2)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


@register_rule
class CKL03015(ChecklistRule):
    rule_id = "CKL-03-015"
    description = (
        "부품은 PCB 외곽선으로부터 최소 0.65mm 이격되어야 합니다"
    )
    category = "Clearance"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        profile = job_data.get("profile")
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []
        user_symbols: dict = job_data.get("user_symbols") or {}

        board_poly = build_board_polygon(profile)
        if board_poly is None:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                category=self.category,
                passed=True,
                message="이격 검사에 사용할 보드 프로파일이 없습니다.",
            )

        inset_poly = build_inset_boundary(board_poly, _CLEARANCE_MM)
        if inset_poly is None:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                category=self.category,
                passed=True,
                message="이격 검사를 위한 내측 경계를 생성할 수 없습니다.",
            )

        # --- Part 1: Top / Bottom component pad clearance ------------------
        columns = ["comp", "part_name", "cmp_layer", "distance", "status"]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_03_015_"))

        for comps, layer_name in [
            (components_top, "Top"),
            (components_bot, "Bottom"),
        ]:
            violations = components_with_pads_in_clearance_zone(
                comps, board_poly, inset_poly, packages
            )
            fail_comps_for_image = []

            for comp, dist in violations:
                if comp.comp_name.startswith(_EXCLUDED_PREFIXES):
                    continue
                status = "PASS" if dist >= _CLEARANCE_MM else "FAIL"
                rows.append({
                    "comp": comp.comp_name,
                    "part_name": comp.part_name or "",
                    "cmp_layer": layer_name,
                    "distance": f"{dist:.3f}",
                    "status": status,
                })
                if status == "FAIL":
                    fail_comps_for_image.append(comp)

            # Generate overview image for this layer
            if fail_comps_for_image:
                img_path = image_dir / f"clearance_{layer_name.lower()}.png"
                _render_clearance_overview(
                    board_poly, inset_poly,
                    fail_comps_for_image,
                    packages, img_path,
                    rule_id=self.rule_id,
                    layer_name=layer_name,
                    clearance_mm=_CLEARANCE_MM,
                    user_symbols=user_symbols,
                )
                images.append({
                    "path": img_path,
                    "title": (
                        f"{layer_name} — {len(fail_comps_for_image)} "
                        f"violation(s) within {_CLEARANCE_MM}mm"
                    ),
                    "width": 700,
                })

        # --- Aggregate results ---------------------------------------------
        comp_fail = sum(1 for r in rows if r["status"] == "FAIL")
        passed = comp_fail == 0

        message = (
            f"PCB 외곽선으로부터 {_CLEARANCE_MM}mm 이내에 패드가 있는 부품이 "
            f"{comp_fail}건 발견되었습니다."
            if not passed
            else f"모든 부품이 {_CLEARANCE_MM}mm 이격 요건을 충족합니다."
        )

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=message,
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={
                "columns": columns,
                "rows": [r for r in rows if r["status"] != "PASS"],
            },
            images=images,
        )
