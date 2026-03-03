"""Component classification utility.

Classifies Component objects into named categories using a defined set of
priority-ordered rules based on comp_name prefix, part_name, and properties.
"""

from __future__ import annotations

from enum import Enum

from src.models import Component


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
