"""CKL-02-005: D-pad application on capacitors inside Shield Cans / Interposers.

Capacitors listed in ``references/dpad_capacitors.csv`` that sit inside the
outline of a Shield Can (SC*) or Interposer (INP*) must have a semi-circle
(D-shape) pad opening on the same-side solder-mask layer (``smt`` for Top,
``smb`` for Bottom).
"""

from __future__ import annotations

from src.checklist.component_classifier import (
    find_capacitors, find_interposers, find_shield_cans,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    _resolve_footprint, _resolve_outline,
)
from src.checklist.reference_loader import load_reference_csv
from src.checklist.rule_base import ChecklistRule
from src.models import PadRecord, RuleResult


_D_SHAPE_TOKENS = ("_D_THMC", "_D_", "DE_")


def _load_dpad_part_map() -> dict[str, str]:
    """Return {part_name: option_geom_after} from dpad_capacitors.csv."""
    rows = load_reference_csv("dpad_capacitors.csv")
    return {
        r["part_name"]: (r.get("option_geom_after") or "").strip()
        for r in rows if r.get("part_name")
    }


def _is_d_shape_symbol(symbol_name: str, expected_geoms: set[str]) -> bool:
    """Return True if *symbol_name* represents a semi-circle (D-shape) pad."""
    if not symbol_name:
        return False
    if symbol_name in expected_geoms:
        return True
    upper = symbol_name.upper()
    return any(tok in upper for tok in _D_SHAPE_TOKENS)


def _pick_soldermask_layer(layers_data: dict, *, is_bottom: bool):
    """Return the top/bottom solder-mask LayerFeatures, excluding coverlays."""
    if not layers_data:
        return None
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
        lname = name.lower()
        if any(h in lname for h in side_hints):
            return lf
    return None


def _iter_pad_records(lf) -> list[PadRecord]:
    return [f for f in (lf.features if lf else []) if isinstance(f, PadRecord)]


def _symbol_name(lf, symbol_idx: int) -> str:
    if lf is None or symbol_idx < 0 or symbol_idx >= len(lf.symbols):
        return ""
    return lf.symbols[symbol_idx].name or ""


@register_rule
class CKL02005(ChecklistRule):
    rule_id = "CKL-02-005"
    description = (
        "D-pad list capacitors located inside Shield Cans or Interposers must "
        "have a semi-circle (D-shape) opening on the SMT/SMB solder-mask layer."
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        layers_data = job_data.get("layers_data", {})
        packages = eda.packages if eda else []

        dpad_map = _load_dpad_part_map()
        dpad_parts = set(dpad_map.keys())
        expected_geoms = {g for g in dpad_map.values() if g}

        columns = ["comp", "comp_layer", "part_name", "d-pad", "status"]
        rows: list[dict] = []

        for comps, layer_name, is_bottom in [
            (components_top, "Top", False),
            (components_bot, "Bottom", True),
        ]:
            if not comps:
                continue

            interposers = find_interposers(comps)
            shield_cans = find_shield_cans(comps)
            containers = interposers + shield_cans
            if not containers:
                continue

            container_outlines = []
            for cont in containers:
                outline = _resolve_outline(cont, packages, is_bottom=is_bottom)
                if outline is not None and not outline.is_empty:
                    container_outlines.append(outline)
            if not container_outlines:
                continue

            target_caps = [
                c for c in find_capacitors(comps)
                if (c.part_name or "") in dpad_parts
            ]
            if not target_caps:
                continue

            mask_lf = _pick_soldermask_layer(layers_data, is_bottom=is_bottom)
            mask_pads = _iter_pad_records(mask_lf)

            for cap in target_caps:
                fp = _resolve_footprint(cap, packages, is_bottom=is_bottom)
                if fp is None or fp.is_empty:
                    continue

                inside_container = any(
                    co.intersects(fp) and co.intersection(fp).area > 0
                    for co in container_outlines
                )
                if not inside_container:
                    continue

                has_d_pad = False
                bbox = fp.bounds  # (minx, miny, maxx, maxy)
                minx, miny, maxx, maxy = bbox
                for pad in mask_pads:
                    if not (minx <= pad.x <= maxx and miny <= pad.y <= maxy):
                        continue
                    sym_name = _symbol_name(mask_lf, pad.symbol_idx)
                    if _is_d_shape_symbol(sym_name, expected_geoms):
                        has_d_pad = True
                        break

                status = "PASS" if has_d_pad else "FAIL"
                rows.append({
                    "comp": cap.comp_name,
                    "comp_layer": layer_name,
                    "part_name": cap.part_name or "",
                    "d-pad": "TRUE" if has_d_pad else "FALSE",
                    "status": status,
                })

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        if not rows:
            message = (
                "No D-pad list capacitors located inside Shield Cans or "
                "Interposers."
            )
        elif passed:
            message = (
                f"All {len(rows)} D-pad list capacitor(s) inside Shield Cans "
                f"or Interposers have a D-shape opening on the solder-mask layer."
            )
        else:
            message = (
                f"{fail_count} D-pad list capacitor(s) inside Shield Cans or "
                f"Interposers are missing a D-shape solder-mask opening."
            )

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=message,
            affected_components=[r["comp"] for r in rows if r["status"] == "FAIL"],
            details={"columns": columns, "rows": rows},
        )
