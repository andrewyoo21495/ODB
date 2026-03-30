"""Component classification utility.

Classifies Component objects into named categories using a defined set of
priority-ordered rules based on comp_name prefix, part_name, and properties.

Also provides individual finder functions (find_ics, find_capacitors, etc.)
for use in checklist rules.
"""

from __future__ import annotations

from enum import Enum
from typing import Sequence

from src.models import Component, Package


class ComponentCategory(str, Enum):
    CONNECTOR = "Connector"
    SIM_SOCKET = "SIM_Socket"
    INDUCTOR = "Inductor"
    CAPACITOR = "Capacitor"
    IC = "IC"
    INP = "INP"
    UNKNOWN = "Unknown"


def classify_component(comp: Component) -> ComponentCategory:
    """Return the category for *comp* using priority-ordered rules.

    Rules (first match wins):
        1. Connector  – comp_name starts with "SOC"
        2. SIM_Socket – comp_name starts with "SIM"
        3. Inductor   – properties TYPE or DEVICE_TYPE == "inductor" (case-insensitive),
                        OR part_name starts with "2703-"
        4. Capacitor  – properties TYPE or DEVICE_TYPE == "capacitor" (case-insensitive),
                        OR part_name starts with "2203-"
        5. IC         – comp_name starts with "U" but NOT "USB"
        6. INP        – comp_name starts with "INP"
        7. Unknown    – everything else
    """
    name = comp.comp_name or ""
    part = comp.part_name or ""
    props = comp.properties or {}

    comp_type = props.get("TYPE", "").lower()
    device_type = props.get("DEVICE_TYPE", "").lower()

    if name.startswith("SOC"):
        return ComponentCategory.CONNECTOR

    if name.startswith("SIM"):
        return ComponentCategory.SIM_SOCKET

    if comp_type == "inductor" or device_type == "inductor" or part.startswith("2703-"):
        return ComponentCategory.INDUCTOR

    if comp_type == "capacitor" or device_type == "capacitor" or part.startswith("2203-"):
        return ComponentCategory.CAPACITOR

    if name.startswith("U") and not name.startswith("USB"):
        return ComponentCategory.IC

    if name.startswith("INP"):
        return ComponentCategory.INP

    return ComponentCategory.UNKNOWN


# ---------------------------------------------------------------------------
# Component finder functions
# ---------------------------------------------------------------------------

def find_ics(components: Sequence[Component]) -> list[Component]:
    """Return IC components.

    Matches when comp_name starts with 'U' (excluding 'USB'), or
    DEVICE_TYPE property is one of 'IC', 'Linear IC', 'Microprocessor IC',
    or 'Memory IC' (case-insensitive).

    When TYPE is 'IC' but DEVICE_TYPE indicates a non-IC component
    (e.g. Capacitor, Resistor, Inductor, Connector, etc.), DEVICE_TYPE
    takes precedence and the component is NOT treated as an IC.
    Exception: TYPE='IC' with DEVICE_TYPE='Filter' is still treated as an IC.
    """
    _IC_DEVICE_TYPES = {"ic", "linear ic", "microprocessor ic", "memory ic"}
    result = []
    for c in components:
        name = c.comp_name or ""
        props = c.properties or {}
        comp_type = props.get("TYPE", "").lower()
        device_type = props.get("DEVICE_TYPE", "").lower()
        if (
            (name.startswith("U") and not name.startswith("USB"))
            or device_type in _IC_DEVICE_TYPES
            or (comp_type == "ic" and device_type == "filter")
        ):
            result.append(c)
    return result


def find_pmics(components: Sequence[Component]) -> list[Component]:
    """Return PMIC components from among the ICs.

    An IC is considered a PMIC if its 'FNC' property contains 'POWER'
    or its 'SSHEET' property contains 'PMIC' (both case-insensitive).
    """
    result = []
    for c in find_ics(components):
        props = c.properties or {}
        fnc = props.get("FNC", "").upper()
        ssheet = props.get("SSHEET", "").upper()
        if "POWER" in fnc or "PMIC" in ssheet:
            result.append(c)
    return result


def find_interposers(components: Sequence[Component]) -> list[Component]:
    """Return Interposer components: comp_name starts with 'INP'."""
    return [c for c in components if (c.comp_name or "").startswith("INP")]


def find_connectors(components: Sequence[Component]) -> list[Component]:
    """Return Connector components.

    Matches when device_type (DEVICE_TYPE property) is 'Connector' or
    comp_name starts with 'SOC', excluding comp_names starting with
    'ANT', 'SIM', 'RFS', or 'BTC'.
    """
    _CONNECTOR_EXCLUSIONS = ("ANT", "SIM", "RFS", "BTC")
    result = []
    for c in components:
        name = c.comp_name or ""
        if name.startswith(_CONNECTOR_EXCLUSIONS):
            continue
        device_type = (c.properties or {}).get("DEVICE_TYPE", "").lower()
        if device_type == "connector" or name.startswith("SOC"):
            result.append(c)
    return result


def find_simsockets(components: Sequence[Component]) -> list[Component]:
    """Return SIM socket components: comp_name starts with 'SIM'."""
    return [c for c in components if (c.comp_name or "").startswith("SIM")]


def find_inductors(components: Sequence[Component]) -> list[Component]:
    """Return Inductor components.

    Matches when pkg_type (PKG_TYPE property) or pkg_device_type
    (PKG_DEVICE_TYPE property) is 'Inductor' (case-insensitive),
    or part_name starts with '2703-'.
    """
    result = []
    for c in components:
        props = c.properties or {}
        pkg_type = props.get("PKG_TYPE", "").lower()
        pkg_device_type = props.get("PKG_DEVICE_TYPE", "").lower()
        part = c.part_name or ""
        if pkg_type == "inductor" or pkg_device_type == "inductor" or part.startswith("2703-"):
            result.append(c)
    return result


def find_capacitors(components: Sequence[Component]) -> list[Component]:
    """Return Capacitor components.

    Matches when pkg_type (PKG_TYPE property) or pkg_device_type
    (PKG_DEVICE_TYPE property) is 'Capacitor' (case-insensitive),
    or part_name starts with '2203-'.
    """
    result = []
    for c in components:
        props = c.properties or {}
        pkg_type = props.get("PKG_TYPE", "").lower()
        pkg_device_type = props.get("PKG_DEVICE_TYPE", "").lower()
        part = c.part_name or ""
        if pkg_type == "capacitor" or pkg_device_type == "capacitor" or part.startswith("2203-"):
            result.append(c)
    return result


def find_oscillators(components: Sequence[Component]) -> list[Component]:
    """Return Oscillator components: comp_name starts with 'OSC'."""
    return [c for c in components if (c.comp_name or "").startswith("OSC")]


def find_bothholes(components: Sequence[Component]) -> list[Component]:
    """Return BOTHHOLE components: comp_name starts with 'BOTHHOLE'."""
    return [c for c in components if (c.comp_name or "").startswith("BOTHHOLE")]


def find_shield_cans(components: Sequence[Component]) -> list[Component]:
    """Return Shield Can components: comp_name starts with 'SC'."""
    return [c for c in components if (c.comp_name or "").upper().startswith("SC")]


def find_mics(components: Sequence[Component]) -> list[Component]:
    """Return MIC components: comp_name starts with 'MIC'."""
    return [c for c in components if (c.comp_name or "").startswith("MIC")]


def find_rf_components(components: Sequence[Component]) -> list[Component]:
    """Return RF Receptacle components: comp_name starts with 'RF'."""
    return [c for c in components if (c.comp_name or "").startswith("RF")]


# ---------------------------------------------------------------------------
# BGA detection
# ---------------------------------------------------------------------------

def is_bga_type(comp: Component, packages: list[Package]) -> bool:
    """Return True if *comp* has circular (BGA-style) pads.

    Inspects the EDA package pin outlines.  If >50% of pins that have
    outline data use a circular shape (``CR`` or ``CT``), the component
    is classified as BGA.  Returns False when no outline data is available.
    """
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return False

    pkg = packages[comp.pkg_ref]
    if not pkg.pins:
        return False

    circular = 0
    non_circular = 0
    for pin in pkg.pins:
        for outline in pin.outlines:
            if outline.type in ("CR", "CT"):
                circular += 1
            elif outline.type in ("RC", "SQ", "CONTOUR"):
                non_circular += 1
            break  # only consider the first outline per pin

    total = circular + non_circular
    if total == 0:
        return False

    return circular / total > 0.5


def find_bga_ics(
    components: Sequence[Component],
    packages: list[Package],
) -> list[Component]:
    """Return IC components that are BGA type (circular pads)."""
    return [c for c in find_ics(components) if is_bga_type(c, packages)]


def find_filters(
    components: Sequence[Component],
    packages: list | None = None,
    *,
    pin_count: int | None = None,
) -> list[Component]:
    """Return Filter components: comp_name starts with 'F'.

    Parameters
    ----------
    packages
        EDA package list – required when *pin_count* is specified so that the
        number of pins can be looked up from the package definition.
    pin_count
        If given, only filters with exactly this many pins are returned.
    """
    result: list[Component] = []
    for c in components:
        name = c.comp_name or ""
        if not name.startswith("F"):
            continue
        # Exclude names that start with common non-filter prefixes
        if any(name.startswith(p) for p in ("FB", "FPC")):
            continue
        if pin_count is not None and packages is not None:
            pkg = packages[c.pkg_ref] if c.pkg_ref < len(packages) else None
            if pkg is None or len(pkg.pins) != pin_count:
                continue
        result.append(c)
    return result
