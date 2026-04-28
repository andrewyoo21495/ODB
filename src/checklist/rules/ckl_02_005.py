"""CKL-02-005: D-pad application on capacitors — bidirectional check.

For every capacitor whose part_name appears in
``references/dpad_capacitors.csv``:

* If the capacitor sits **inside** a Shield Can (SC*) or Interposer (INP*)
  region, its EDA package name (PKG) must equal the ``option_geom_after``
  value from the CSV (= D-pad applied).
* If it sits **outside**, the package must NOT equal ``option_geom_after``
  (= regular pad, D-pad must not be applied).

The verdict therefore reduces to ``passed = (is_inside == is_dpad)``.
The ``option_geom_before`` column is not used in evaluation.

"Inside" is judged by the cap centre being contained within the convex
hull of the container's pad/outline points — this gives a filled region
even for SC frames or INP rings whose ``pkg.outlines`` are hollow.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from shapely.geometry import Point as ShapelyPoint

from src.checklist.component_classifier import (
    find_capacitors, find_interposers, find_shield_cans,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import _resolve_footprint
from src.checklist.reference_loader import load_reference_csv
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.dpad_mask_viz import render_dpad_side_image
from src.models import Component, Package, RuleResult


def _load_dpad_part_map() -> dict[str, str]:
    """Return {part_name: option_geom_after} from dpad_capacitors.csv.

    Rows missing either column are dropped — they cannot be evaluated.
    """
    out: dict[str, str] = {}
    for r in load_reference_csv("dpad_capacitors.csv"):
        pn = (r.get("part_name") or "").strip()
        gm = (r.get("option_geom_after") or "").strip()
        if pn and gm:
            out[pn] = gm
    return out


def _pick_soldermask_layer(layers_data: dict, *, is_bottom: bool):
    """Return (layer_name, LayerFeatures) for the side's solder mask, or (None, None)."""
    if not layers_data:
        return None, None
    side_hints_bot = ("bottom", "_bot", "_b", "smb", "bot")
    side_hints_top = ("top", "_top", "_t", "smt")
    side_hints = side_hints_bot if is_bottom else side_hints_top

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


def _package_name(comp: Component, packages: list[Package]) -> str:
    if 0 <= comp.pkg_ref < len(packages):
        return packages[comp.pkg_ref].name or ""
    return ""


def _matches_dpad(actual: str, expected: str) -> bool:
    """True if *actual* package equals *expected* or is a suffixed variant.

    EDA tools sometimes append suffixes to the canonical D-pad geom name
    (e.g. ``DE115070_CAP_THMC`` → ``DE115070_CAP_THMC_OSP``).  We treat any
    such ``<expected>_<suffix>`` as the same D-pad package.  The underscore
    boundary prevents accidental matches against unrelated names that
    happen to share the same prefix characters.
    """
    if not expected or not actual:
        return False
    return actual == expected or actual.startswith(expected + "_")


@register_rule
class CKL02005(ChecklistRule):
    rule_id = "CKL-02-005"
    description = (
        "D-pad list capacitors must use the D-pad package only when located "
        "inside a Shield Can / Interposer; outside, the regular package is required."
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda            = job_data.get("eda_data")
        layers_data    = job_data.get("layers_data", {})
        user_symbols   = job_data.get("user_symbols")
        font           = job_data.get("font")
        packages       = eda.packages if eda else []

        dpad_map = _load_dpad_part_map()

        columns = [
            "comp", "comp_layer", "part_name", "container",
            "location", "expected_pkg", "actual_pkg", "status",
        ]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_02_005_"))
        total_evaluated = 0

        for comps, layer_name, is_bottom in [
            (components_top, "Top", False),
            (components_bot, "Bottom", True),
        ]:
            if not comps:
                continue

            target_caps = [
                c for c in find_capacitors(comps)
                if (c.part_name or "") in dpad_map
            ]
            if not target_caps:
                continue

            # Container "inside regions" = convex hulls of all pad/outline
            # points. This handles hollow SC frames and INP rings correctly.
            containers = find_interposers(comps) + find_shield_cans(comps)
            cont_hulls: list[tuple] = []
            for cont in containers:
                hull = _resolve_footprint(cont, packages, is_bottom=is_bottom)
                if hull is not None and not hull.is_empty:
                    cont_hulls.append((hull, cont))

            cap_items: list[dict] = []
            for cap in target_caps:
                cap_pt = ShapelyPoint(cap.x, cap.y)
                host = next(
                    (c for h, c in cont_hulls if h.contains(cap_pt)),
                    None,
                )
                is_inside = host is not None

                expected_pkg = dpad_map[cap.part_name]
                actual_pkg   = _package_name(cap, packages)
                is_dpad      = _matches_dpad(actual_pkg, expected_pkg)

                passed   = (is_inside == is_dpad)
                status   = "PASS" if passed else "FAIL"
                location = "INSIDE" if is_inside else "OUTSIDE"

                expected_disp = (expected_pkg if is_inside
                                 else f"!= {expected_pkg}")

                total_evaluated += 1

                if not passed:
                    rows.append({
                        "comp":         cap.comp_name,
                        "comp_layer":   layer_name,
                        "part_name":    cap.part_name or "",
                        "container":    host.comp_name if host else "",
                        "location":     location,
                        "expected_pkg": expected_disp,
                        "actual_pkg":   actual_pkg,
                        "status":       status,
                    })
                cap_items.append({
                    "cap":      cap,
                    "host":     host,
                    "location": location,
                    "status":   status,
                })

            if not cap_items:
                continue

            mask_layer_name, mask_lf = _pick_soldermask_layer(
                layers_data, is_bottom=is_bottom
            )
            img_path = image_dir / f"dpad_{layer_name.lower()}.png"
            render_dpad_side_image(
                cap_items, containers, packages,
                mask_lf, mask_layer_name or "soldermask",
                img_path,
                rule_id=self.rule_id,
                layer_name=layer_name,
                is_bottom=is_bottom,
                user_symbols=user_symbols,
                font=font,
            )
            n_fail = sum(1 for it in cap_items if it["status"] == "FAIL")
            images.append({
                "path": img_path,
                "title": (
                    f"{layer_name} side ({mask_layer_name or 'soldermask'}) — "
                    f"{len(cap_items)} cap(s), {n_fail} FAIL"
                ),
                "width": 700,
            })

        fail_count = len(rows)
        passed_all = fail_count == 0

        if total_evaluated == 0:
            message = "No D-pad list capacitors found on the board to evaluate."
        elif passed_all:
            message = (
                f"All {total_evaluated} D-pad list capacitor(s) use the correct "
                f"package for their location (inside vs outside containers)."
            )
        else:
            message = (
                f"{fail_count} of {total_evaluated} D-pad list capacitor(s) use "
                f"an incorrect package for their location."
            )

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed_all,
            message=message,
            affected_components=[r["comp"] for r in rows],
            details={"columns": columns, "rows": rows},
            images=images,
        )
