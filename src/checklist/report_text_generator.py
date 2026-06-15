"""Report text generator for checklist results.

Generates Korean-language bullet-point report text for each checklist rule.
Only FAIL items are included in the generated report bullets.
"""

from __future__ import annotations

from collections import defaultdict


def generate_report_bullets(rule_id: str, details: dict) -> list[str]:
    """Generate Korean report bullet points for a given rule's results.

    Args:
        rule_id: The checklist rule ID (e.g. "CKL-01-001").
        details: The rule result details dict with ``columns`` and ``rows``.

    Returns:
        List of bullet-point strings. Empty list if the rule is not
        registered or has no FAIL items.
    """
    generator = _GENERATORS.get(rule_id)
    if generator is None:
        return []

    rows = details.get("rows")
    if not isinstance(rows, list):
        return []

    fail_rows = [r for r in rows if r.get("status") == "FAIL"]
    if not fail_rows:
        return []

    return generator(fail_rows)


# ---------------------------------------------------------------------------
# Per-rule generators
# ---------------------------------------------------------------------------

def _gen_01_001(fail_rows: list[dict]) -> list[str]:
    """CKL-01-001: group comp by overlapping_cmp."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in fail_rows:
        opp = r.get("overlapping_cmp", "")
        comp = r.get("comp", "")
        if opp and comp and comp not in grouped[opp]:
            grouped[opp].append(comp)

    bullets: list[str] = []
    for opp, comps in grouped.items():
        comp_str = ", ".join(comps)
        bullets.append(f"{comp_str} 는 배면에 {opp} 회피 설계할 것.")
    return bullets


def _gen_01_002(fail_rows: list[dict]) -> list[str]:
    """CKL-01-002: group pad_name by comp."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in fail_rows:
        comp = r.get("comp", "")
        pad = r.get("pad_name", "")
        if comp and pad and pad not in grouped[comp]:
            grouped[comp].append(pad)

    bullets: list[str] = []
    for comp, pads in grouped.items():
        pad_str = ", ".join(pads)
        bullets.append(f"{comp}의 {pad_str}은 via 설계할 것.")
    return bullets


def _gen_01_003(fail_rows: list[dict]) -> list[str]:
    """CKL-01-003: group by comp, split edge vs vertical."""
    grouped: dict[str, dict] = defaultdict(lambda: {"edge": [], "vertical": []})
    for r in fail_rows:
        comp = r.get("comp", "")
        ind = r.get("overlapping_cmp", "")
        if not comp or not ind:
            continue
        if r.get("edge") == "TRUE":
            if ind not in [x for x in grouped[comp]["edge"]]:
                grouped[comp]["edge"].append(ind)
        elif r.get("hori/verti") == "Vertical":
            if ind not in [x for x in grouped[comp]["vertical"]]:
                grouped[comp]["vertical"].append(ind)

    # Remove items already in edge from vertical
    for comp in grouped:
        edge_set = set(grouped[comp]["edge"])
        grouped[comp]["vertical"] = [
            x for x in grouped[comp]["vertical"] if x not in edge_set
        ]

    bullets: list[str] = []
    for comp, cases in grouped.items():
        for ind in cases["edge"]:
            bullets.append(
                f"{ind}는 {comp}의 배면 outline edge 에 위치하므로 이격할 것."
            )
        for ind in cases["vertical"]:
            bullets.append(f"{ind}는 {comp}와 수평배치 할 것.")
    return bullets


def _gen_cap_edge_vertical(
    fail_rows: list[dict],
    cap_key: str = "overlapping_cap",
    comp_key: str = "comp",
    *,
    prefix: str = "",
    edge_msg_suffix: str = "의 배면 edge 에 위치하므로 이격할 것.",
    vertical_msg_suffix: str = "와 배면 수평배치 할 것.",
) -> list[str]:
    """Shared logic for CKL-02-002, 02-003, 02-006 style rules.

    Groups by comp, splits into edge=TRUE vs hori/verti=Vertical cases.
    Items already flagged as edge are excluded from the vertical case.
    """
    grouped: dict[str, dict] = defaultdict(lambda: {"edge": [], "vertical": []})
    for r in fail_rows:
        comp = r.get(comp_key, "")
        cap = r.get(cap_key, "")
        if not comp or not cap:
            continue
        if r.get("edge") == "TRUE":
            if cap not in grouped[comp]["edge"]:
                grouped[comp]["edge"].append(cap)
        elif r.get("hori/verti") == "Vertical":
            if cap not in grouped[comp]["vertical"]:
                grouped[comp]["vertical"].append(cap)

    # Remove items already in edge from vertical
    for comp in grouped:
        edge_set = set(grouped[comp]["edge"])
        grouped[comp]["vertical"] = [
            x for x in grouped[comp]["vertical"] if x not in edge_set
        ]

    bullets: list[str] = []
    for comp, cases in grouped.items():
        for cap in cases["edge"]:
            bullets.append(f"{prefix}{cap}는 {comp}{edge_msg_suffix}")
        for cap in cases["vertical"]:
            bullets.append(f"{prefix}{cap}는 {comp}{vertical_msg_suffix}")
    return bullets


def _gen_02_002(fail_rows: list[dict]) -> list[str]:
    """CKL-02-002: cap vs connector, edge/vertical split."""
    return _gen_cap_edge_vertical(fail_rows)


def _gen_02_003(fail_rows: list[dict]) -> list[str]:
    """CKL-02-003: cap vs shield can, edge/vertical split."""
    return _gen_cap_edge_vertical(fail_rows)


def _gen_02_005(fail_rows: list[dict]) -> list[str]:
    """CKL-02-005: D-pad application, grouped into two bullets by location."""
    inside: list[str] = []
    outside: list[str] = []

    for r in fail_rows:
        comp = r.get("comp", "")
        part = r.get("part_name", "")
        loc = r.get("location", "")
        entry = f"{comp}({part})"

        if loc == "INSIDE":
            if entry not in inside:
                inside.append(entry)
        elif loc == "OUTSIDE":
            if entry not in outside:
                outside.append(entry)

    bullets: list[str] = []
    if inside:
        bullets.append(f"{', '.join(inside)} 는 D-pad 적용할 것.")
    if outside:
        bullets.append(f"{', '.join(outside)} 는 일반 Pad 적용할 것.")
    return bullets


def _gen_02_006(fail_rows: list[dict]) -> list[str]:
    """CKL-02-006: general cap vs connector/shield, recommended prefix."""
    return _gen_cap_edge_vertical(fail_rows, prefix="(권장) ")


def _gen_02_007(fail_rows: list[dict]) -> list[str]:
    """CKL-02-007: shield can inner wall clearance, group by shield_can."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in fail_rows:
        comp = r.get("comp", "")
        shield = r.get("shield_can", "")
        if comp and shield and comp not in grouped[shield]:
            grouped[shield].append(comp)

    bullets: list[str] = []
    for shield, comps in grouped.items():
        comp_str = ", ".join(comps)
        bullets.append(
            f"{comp_str}는 {shield} inner wall로부터 0.3mm 이상 이격할 것."
        )
    return bullets


def _gen_02_008(fail_rows: list[dict]) -> list[str]:
    """CKL-02-008: inductor vs connector/shield, edge/vertical split."""
    grouped: dict[str, dict] = defaultdict(lambda: {"edge": [], "vertical": []})
    for r in fail_rows:
        comp = r.get("comp", "")
        ind = r.get("overlapping_ind", "")
        if not comp or not ind:
            continue
        if r.get("edge") == "TRUE":
            if ind not in grouped[comp]["edge"]:
                grouped[comp]["edge"].append(ind)
        elif r.get("hori/verti") == "Vertical":
            if ind not in grouped[comp]["vertical"]:
                grouped[comp]["vertical"].append(ind)

    for comp in grouped:
        edge_set = set(grouped[comp]["edge"])
        grouped[comp]["vertical"] = [
            x for x in grouped[comp]["vertical"] if x not in edge_set
        ]

    bullets: list[str] = []
    for comp, cases in grouped.items():
        for ind in cases["edge"]:
            bullets.append(
                f"{ind}는 {comp}의 배면 outline edge 에 위치하므로 이격할 것."
            )
        for ind in cases["vertical"]:
            bullets.append(f"{ind}는 {comp}와 수평배치 할 것.")
    return bullets


def _gen_02_010(fail_rows: list[dict]) -> list[str]:
    """CKL-02-010: SIM socket orientation, vertical only."""
    bullets: list[str] = []
    for r in fail_rows:
        if r.get("hori/verti") != "Vertical":
            continue
        cmp = r.get("overlapping_cmp", "")
        part = r.get("part_name", "")
        comp = r.get("comp", "")
        if cmp and comp:
            bullets.append(
                f"{cmp}({part})는 {comp}의 배면 outline과 수평배치 할 것."
            )
    return bullets


def _gen_03_001(fail_rows: list[dict]) -> list[str]:
    """CKL-03-001: MCP IC corner via, group corner_pin by comp."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in fail_rows:
        comp = r.get("comp", "")
        pin = r.get("corner_pin", "")
        if not comp or not pin or pin == "-":
            continue
        if pin not in grouped[comp]:
            grouped[comp].append(pin)

    bullets: list[str] = []
    for comp, pins in grouped.items():
        pin_str = ", ".join(pins)
        bullets.append(f"{comp}의 {pin_str} 들은 via 설계할 것.")
    return bullets


def _gen_03_009(fail_rows: list[dict]) -> list[str]:
    """CKL-03-009: SIM socket outermost pads VIA count, group by comp."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in fail_rows:
        comp = r.get("comp", "")
        pad = r.get("pad", "")
        if comp and pad and pad not in grouped[comp]:
            grouped[comp].append(pad)

    bullets: list[str] = []
    for comp, pads in grouped.items():
        pad_str = ", ".join(pads)
        bullets.append(
            f"{comp}의 최외곽 패드 {pad_str}들은 via 4개 이상 적용할 것."
        )
    return bullets


def _gen_03_015(fail_rows: list[dict]) -> list[str]:
    """CKL-03-015: PCB outline clearance, group by cmp_layer."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in fail_rows:
        layer = r.get("cmp_layer", "")
        comp = r.get("comp", "")
        part = r.get("part_name", "")
        if not layer or not comp:
            continue
        entry = f"{comp}({part})" if part else comp
        if entry not in grouped[layer]:
            grouped[layer].append(entry)

    bullets: list[str] = []
    for layer, entries in grouped.items():
        entry_str = ", ".join(entries)
        bullets.append(
            f"{layer} 위치한 {entry_str} 들은 PCB 외곽으로부터 "
            f"0.65mm 이상 이격할 것."
        )
    return bullets


def _gen_01_004(fail_rows: list[dict]) -> list[str]:
    """CKL-01-004: opposite-side overlap, group by comp."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in fail_rows:
        comp = r.get("comp", "")
        opp = r.get("overlapping_cmp", "")
        if comp and opp and opp not in grouped[comp]:
            grouped[comp].append(opp)

    bullets: list[str] = []
    for comp, opps in grouped.items():
        for opp in opps:
            bullets.append(
                f"{opp}는 {comp}의 배면 outline과 겹치지 않도록 하거나 수평배치 할 것."
            )
    return bullets


def _gen_01_005(fail_rows: list[dict]) -> list[str]:
    """CKL-01-005: inductor vs comp, edge/vertical split."""
    grouped: dict[str, dict] = defaultdict(lambda: {"edge": [], "vertical": []})
    for r in fail_rows:
        comp = r.get("comp", "")
        ind = r.get("overlapping_ind", "")
        if not comp or not ind:
            continue
        if r.get("edge") == "TRUE":
            if ind not in grouped[comp]["edge"]:
                grouped[comp]["edge"].append(ind)
        elif r.get("hori/verti") == "Vertical":
            if ind not in grouped[comp]["vertical"]:
                grouped[comp]["vertical"].append(ind)

    for comp in grouped:
        edge_set = set(grouped[comp]["edge"])
        grouped[comp]["vertical"] = [
            x for x in grouped[comp]["vertical"] if x not in edge_set
        ]

    bullets: list[str] = []
    for comp, cases in grouped.items():
        for ind in cases["edge"]:
            bullets.append(
                f"{ind}는 {comp}의 배면 outline edge 에 위치하므로 이격할 것."
            )
        for ind in cases["vertical"]:
            bullets.append(f"{ind}는 {comp}와 수평배치 할 것.")
    return bullets


def _gen_01_006(fail_rows: list[dict]) -> list[str]:
    """CKL-01-006: opposite-side pad overlap."""
    bullets: list[str] = []
    for r in fail_rows:
        comp = r.get("comp", "")
        opp = r.get("overlapping_cmp", "")
        if comp and opp:
            bullets.append(f"{comp}는 배면 {opp} 패드와 회피 배치할 것.")
    return bullets


def _gen_01_007(fail_rows: list[dict]) -> list[str]:
    """CKL-01-007: opposite-side comp overlap."""
    bullets: list[str] = []
    for r in fail_rows:
        comp = r.get("comp", "")
        opp = r.get("overlapping_cmp", "")
        if comp and opp:
            bullets.append(f"{comp}는 배면 {opp} 와 회피 배치할 것.")
    return bullets


def _gen_01_008(fail_rows: list[dict]) -> list[str]:
    """CKL-01-008: signal ball on curved area, group pin by comp."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in fail_rows:
        comp = r.get("comp", "")
        pin = r.get("pin", "")
        if comp and pin and pin not in grouped[comp]:
            grouped[comp].append(pin)

    bullets: list[str] = []
    for comp, pins in grouped.items():
        pin_str = ", ".join(pins)
        bullets.append(f"{comp}의 곡선부 {pin_str} 에는 signal ball 설계 회피할 것.")
    return bullets


def _gen_01_009(fail_rows: list[dict]) -> list[str]:
    """CKL-01-009: bundle or ground, group pin by comp."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in fail_rows:
        comp = r.get("comp", "")
        pin = r.get("pin", "")
        if comp and pin and pin not in grouped[comp]:
            grouped[comp].append(pin)

    bullets: list[str] = []
    for comp, pins in grouped.items():
        pin_str = ", ".join(pins)
        bullets.append(
            f"{comp}의 {pin_str} 들은 묶음구조 적용 또는 Ground 처리할 것."
        )
    return bullets


def _gen_01_010(fail_rows: list[dict]) -> list[str]:
    """CKL-01-010: narrow PCB region."""
    bullets: list[str] = []
    for r in fail_rows:
        region = r.get("region", "")
        if region:
            bullets.append(
                f"PCB의 {region} 영역은 (하단 이미지 참고) 폭 3.5mm 이상 설계 "
                f"또는 고정 Screw 설계할 것."
            )
    return bullets


def _gen_02_001(fail_rows: list[dict]) -> list[str]:
    """CKL-02-001: capacitor clearance from component."""
    bullets: list[str] = []
    for r in fail_rows:
        comp = r.get("comp", "")
        part = r.get("part_name", "")
        opp = r.get("overlapping_cmp", "")
        if comp and opp:
            bullets.append(
                f"{comp}({part}) 는 {opp} 에서 1.5mm 이상 이격할 것."
            )
    return bullets


def _gen_02_004(fail_rows: list[dict]) -> list[str]:
    """CKL-02-004: opposite-side clearance."""
    bullets: list[str] = []
    for r in fail_rows:
        opp = r.get("overlapping_cmp", "")
        part = r.get("part_name", "")
        comp = r.get("comp", "")
        if opp and comp:
            bullets.append(
                f"{opp}({part}) 는 배면 {comp}에서 0.5mm 이상 이격할 것."
            )
    return bullets


def _gen_02_009(fail_rows: list[dict]) -> list[str]:
    """CKL-02-009: inductor vs connector/shield, split by check_type and edge/vertical."""
    grouped: dict[str, dict] = defaultdict(lambda: {"edge": [], "vertical": []})
    for r in fail_rows:
        comp = r.get("comp", "")
        ind = r.get("overlapping_ind", "")
        if not comp or not ind:
            continue
        if r.get("edge") == "TRUE":
            if ind not in grouped[comp]["edge"]:
                grouped[comp]["edge"].append(ind)
        elif r.get("hori/verti") == "Vertical":
            if ind not in grouped[comp]["vertical"]:
                grouped[comp]["vertical"].append(ind)

    for comp in grouped:
        edge_set = set(grouped[comp]["edge"])
        grouped[comp]["vertical"] = [
            x for x in grouped[comp]["vertical"] if x not in edge_set
        ]

    bullets: list[str] = []
    for comp, cases in grouped.items():
        for ind in cases["edge"]:
            bullets.append(
                f"{ind}는 {comp}의 배면 edge 에 위치하므로 이격할 것."
            )
        for ind in cases["vertical"]:
            bullets.append(f"{ind}는 {comp}와 수평배치 할 것.")
    return bullets


def _gen_02_011(fail_rows: list[dict]) -> list[str]:
    """CKL-02-011: opposite-side outline overlap."""
    bullets: list[str] = []
    for r in fail_rows:
        comp = r.get("comp", "")
        opp = r.get("overlapping_cmp", "")
        if comp and opp:
            bullets.append(
                f"{comp}는 배면 {opp} outline과 겹치지 않도록 하거나 수평배치할 것."
            )
    return bullets


def _gen_02_012(fail_rows: list[dict]) -> list[str]:
    """CKL-02-012: opposite-side antenna pattern overlap."""
    bullets: list[str] = []
    for r in fail_rows:
        comp = r.get("comp", "")
        ap = r.get("overlapping_ap", "")
        if comp and ap:
            bullets.append(f"{comp}는 배면 {ap} 와 회피 배치할 것.")
    return bullets


def _gen_03_002(fail_rows: list[dict]) -> list[str]:
    """CKL-03-002: resin application, group by cmp_layer."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in fail_rows:
        layer = r.get("cmp_layer", "")
        comp = r.get("comp", "")
        if layer and comp and comp not in grouped[layer]:
            grouped[layer].append(comp)

    bullets: list[str] = []
    for layer, comps in grouped.items():
        comp_str = ", ".join(comps)
        bullets.append(f"{layer} 층에 위치한 {comp_str} 부품 수지 적용할 것.")
    return bullets


def _gen_03_003(fail_rows: list[dict]) -> list[str]:
    """CKL-03-003: edge pad clearance, group by cmp_layer."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in fail_rows:
        layer = r.get("cmp_layer", "")
        comp = r.get("comp", "")
        if layer and comp and comp not in grouped[layer]:
            grouped[layer].append(comp)

    bullets: list[str] = []
    for layer, comps in grouped.items():
        comp_str = ", ".join(comps)
        bullets.append(
            f"{layer} 층에 위치한 {comp_str} 의 edge Pad 0mm 초과 이격할 것."
        )
    return bullets


def _gen_comp_pad_via(fail_rows: list[dict], min_via: str = "1개") -> list[str]:
    """Shared: group pad by comp, via requirement message."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in fail_rows:
        comp = r.get("comp", "")
        pad = r.get("pad", "")
        if comp and pad and pad not in grouped[comp]:
            grouped[comp].append(pad)

    bullets: list[str] = []
    for comp, pads in grouped.items():
        pad_str = ", ".join(pads)
        bullets.append(f"{comp}의 {pad_str}는 via {min_via} 이상 설계할 것.")
    return bullets


def _gen_03_004(fail_rows: list[dict]) -> list[str]:
    """CKL-03-004: pad via >= 1."""
    return _gen_comp_pad_via(fail_rows, "1개")


def _gen_03_005(fail_rows: list[dict]) -> list[str]:
    """CKL-03-005: pad via >= 1."""
    return _gen_comp_pad_via(fail_rows, "1개")


def _gen_03_006(fail_rows: list[dict]) -> list[str]:
    """CKL-03-006: hole solder mask overlap."""
    bullets: list[str] = []
    for r in fail_rows:
        comp = r.get("comp", "")
        if comp:
            bullets.append(
                f"{comp}는 Hole의 solder mask와 겹치지 않게 설계할 것."
            )
    return bullets


def _gen_03_007(fail_rows: list[dict]) -> list[str]:
    """CKL-03-007: GND pad via >= 1, group pad by comp."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in fail_rows:
        comp = r.get("comp", "")
        pad = r.get("pad", "")
        if comp and pad and pad not in grouped[comp]:
            grouped[comp].append(pad)

    bullets: list[str] = []
    for comp, pads in grouped.items():
        pad_str = ", ".join(pads)
        bullets.append(
            f"{comp}의 GND 패드 {pad_str} 는 via 1개 이상 설계할 것."
        )
    return bullets


def _gen_03_008(fail_rows: list[dict]) -> list[str]:
    """CKL-03-008: pad via >= 4, group pad by comp."""
    return _gen_comp_pad_via(fail_rows, "4개")


def _gen_03_011(fail_rows: list[dict]) -> list[str]:
    """CKL-03-011: bending area placement."""
    bullets: list[str] = []
    for r in fail_rows:
        comp = r.get("comp", "")
        if comp:
            bullets.append(
                f"{comp}는 Bending 취약 돌출부 이외의 위치에 배치할 것."
            )
    return bullets


def _gen_03_012(fail_rows: list[dict]) -> list[str]:
    """CKL-03-012: PCB edge and hole clearance."""
    bullets: list[str] = []
    for r in fail_rows:
        comp = r.get("comp", "")
        if comp:
            bullets.append(
                f"{comp}는 PCB 끝단 및 hole에서 1mm 이상 이격할 것."
            )
    return bullets


def _gen_03_013(fail_rows: list[dict]) -> list[str]:
    """CKL-03-013: pad via >= 1."""
    return _gen_comp_pad_via(fail_rows, "1개")


def _gen_03_014(fail_rows: list[dict]) -> list[str]:
    """CKL-03-014: signal pattern clearance under pad."""
    bullets: list[str] = []
    for r in fail_rows:
        comp = r.get("comp", "")
        if comp:
            bullets.append(
                f"{comp}의 패드 하단에 위치한 Signal 패턴들은 Pad 기준 "
                f"0.2mm 이격할 것."
            )
    return bullets


def _gen_03_016(fail_rows: list[dict]) -> list[str]:
    """CKL-03-016: opposite-side comp overlap."""
    bullets: list[str] = []
    for r in fail_rows:
        comp = r.get("comp", "")
        opp = r.get("overlapping_cmp", "")
        if comp and opp:
            bullets.append(
                f"{comp} 는 배면의 {opp} 와 회피 배치할 것."
            )
    return bullets


# ---------------------------------------------------------------------------
# Generator registry
# ---------------------------------------------------------------------------

_GENERATORS: dict[str, callable] = {
    "CKL-01-001": _gen_01_001,
    "CKL-01-002": _gen_01_002,
    "CKL-01-003": _gen_01_003,
    "CKL-01-004": _gen_01_004,
    "CKL-01-005": _gen_01_005,
    "CKL-01-006": _gen_01_006,
    "CKL-01-007": _gen_01_007,
    "CKL-01-008": _gen_01_008,
    "CKL-01-009": _gen_01_009,
    "CKL-01-010": _gen_01_010,
    "CKL-02-001": _gen_02_001,
    "CKL-02-002": _gen_02_002,
    "CKL-02-003": _gen_02_003,
    "CKL-02-004": _gen_02_004,
    "CKL-02-005": _gen_02_005,
    "CKL-02-006": _gen_02_006,
    "CKL-02-007": _gen_02_007,
    "CKL-02-008": _gen_02_008,
    "CKL-02-009": _gen_02_009,
    "CKL-02-010": _gen_02_010,
    "CKL-02-011": _gen_02_011,
    "CKL-02-012": _gen_02_012,
    "CKL-03-001": _gen_03_001,
    "CKL-03-002": _gen_03_002,
    "CKL-03-003": _gen_03_003,
    "CKL-03-004": _gen_03_004,
    "CKL-03-005": _gen_03_005,
    "CKL-03-006": _gen_03_006,
    "CKL-03-007": _gen_03_007,
    "CKL-03-008": _gen_03_008,
    "CKL-03-009": _gen_03_009,
    "CKL-03-011": _gen_03_011,
    "CKL-03-012": _gen_03_012,
    "CKL-03-013": _gen_03_013,
    "CKL-03-014": _gen_03_014,
    "CKL-03-015": _gen_03_015,
    "CKL-03-016": _gen_03_016,
}
