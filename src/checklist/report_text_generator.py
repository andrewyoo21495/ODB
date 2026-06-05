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
    """CKL-02-005: D-pad application, split by location."""
    inside: dict[str, list[str]] = defaultdict(list)
    outside: dict[str, list[str]] = defaultdict(list)

    for r in fail_rows:
        comp = r.get("comp", "")
        part = r.get("part_name", "")
        loc = r.get("location", "")
        container = r.get("container", "")
        entry = f"{comp}({part})"

        if loc == "INSIDE":
            if entry not in inside[container]:
                inside[container].append(entry)
        elif loc == "OUTSIDE":
            if entry not in outside[container]:
                outside[container].append(entry)

    bullets: list[str] = []
    for _container, entries in inside.items():
        for entry in entries:
            bullets.append(f"{entry}는 D-pad 적용할 것.")
    for _container, entries in outside.items():
        for entry in entries:
            bullets.append(f"{entry}는 일반 Pad 적용할 것.")
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


# ---------------------------------------------------------------------------
# Generator registry
# ---------------------------------------------------------------------------

_GENERATORS: dict[str, callable] = {
    "CKL-01-001": _gen_01_001,
    "CKL-01-002": _gen_01_002,
    "CKL-01-003": _gen_01_003,
    "CKL-02-002": _gen_02_002,
    "CKL-02-003": _gen_02_003,
    "CKL-02-005": _gen_02_005,
    "CKL-02-006": _gen_02_006,
    "CKL-02-007": _gen_02_007,
    "CKL-02-008": _gen_02_008,
    "CKL-02-010": _gen_02_010,
    "CKL-03-001": _gen_03_001,
    "CKL-03-009": _gen_03_009,
    "CKL-03-015": _gen_03_015,
}
