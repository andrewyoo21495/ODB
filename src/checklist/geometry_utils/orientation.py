"""Component orientation detection.

Provides:
- get_component_orientation  — Horizontal / Vertical / Square / Unknown
- get_major_axis_angle       — major-axis direction in degrees [0, 180)
- get_pair_orientation       — alignment of two components
- are_components_aligned     — boolean same-orientation check
"""

from __future__ import annotations

import math
from typing import Optional

from src.models import Component, Package
from .polygon import get_component_outline


def _classify_wh(w: float, h: float) -> str:
    """Classify orientation from width/height in board coordinates.

    Returns "Horizontal", "Vertical", "Square", or "Unknown".
    """
    if w <= 0 and h <= 0:
        return "Unknown"

    if w > 0 and h > 0:
        ratio = max(w, h) / min(w, h)
        if ratio < 1.05:
            return "Square"

    if w >= h:
        return "Horizontal"
    return "Vertical"


def get_component_orientation(comp: Component,
                              packages: list[Package]) -> str:
    """Determine a component's board-level orientation from its component outline.

    Returns:
        "Horizontal" – major axis is roughly along the board X-axis
        "Vertical"   – major axis is roughly along the board Y-axis
        "Square"     – aspect ratio is near 1:1
        "Unknown"    – no geometry data available
    """
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return "Unknown"

    pkg = packages[comp.pkg_ref]

    outline_poly = get_component_outline(comp, pkg)
    if outline_poly is not None:
        minx, miny, maxx, maxy = outline_poly.bounds
        return _classify_wh(maxx - minx, maxy - miny)

    if pkg.bbox is None:
        return "Unknown"

    w = pkg.bbox.xmax - pkg.bbox.xmin
    h = pkg.bbox.ymax - pkg.bbox.ymin

    if w <= 0 and h <= 0:
        return "Unknown"

    if w > 0 and h > 0:
        ratio = max(w, h) / min(w, h)
        if ratio < 1.05:
            return "Square"

    local_angle = 0.0 if w >= h else 90.0
    board_angle = (local_angle + comp.rotation) % 180.0

    if board_angle < 45.0 or board_angle > 135.0:
        return "Horizontal"
    return "Vertical"


def get_major_axis_angle(comp: Component,
                         packages: list[Package],
                         *, is_bottom: bool = False) -> Optional[float]:
    """Return the major-axis direction of comp as an angle in degrees [0, 180).

    Returns None when orientation cannot be determined (missing geometry or
    near-square outline).
    """
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return None

    pkg = packages[comp.pkg_ref]

    outline_poly = get_component_outline(comp, pkg, is_bottom=is_bottom)
    if outline_poly is not None:
        mrr = outline_poly.minimum_rotated_rectangle
        coords = list(mrr.exterior.coords)
        edge_a = (coords[1][0] - coords[0][0], coords[1][1] - coords[0][1])
        edge_b = (coords[2][0] - coords[1][0], coords[2][1] - coords[1][1])
        len_a = math.hypot(*edge_a)
        len_b = math.hypot(*edge_b)

        if len_a > 0 and len_b > 0:
            ratio = max(len_a, len_b) / min(len_a, len_b)
            if ratio < 1.05:
                return None

        major = edge_a if len_a >= len_b else edge_b
        angle = math.degrees(math.atan2(major[1], major[0])) % 180.0
        return angle

    if pkg.bbox is None:
        return None

    w = pkg.bbox.xmax - pkg.bbox.xmin
    h = pkg.bbox.ymax - pkg.bbox.ymin

    if w <= 0 and h <= 0:
        return None

    if w > 0 and h > 0:
        ratio = max(w, h) / min(w, h)
        if ratio < 1.05:
            return None

    local_angle = 0.0 if w >= h else 90.0
    effective_mirror = (not comp.mirror) if is_bottom else comp.mirror
    rot = -comp.rotation if effective_mirror else comp.rotation
    board_angle = (local_angle + rot) % 180.0
    return board_angle


def get_pair_orientation(comp_a: Component, comp_b: Component,
                         packages: list[Package]) -> str:
    """Determine alignment by comparing major axes of two component outlines.

    Returns "Horizontal" (parallel axes), "Vertical" (perpendicular), or
    "Unknown" when either component's axis cannot be determined.
    """
    angle_a = get_major_axis_angle(comp_a, packages)
    angle_b = get_major_axis_angle(comp_b, packages)

    if angle_a is None or angle_b is None:
        return "Unknown"

    diff = abs(angle_a - angle_b) % 180.0
    if diff > 90.0:
        diff = 180.0 - diff

    if diff < 45.0:
        return "Horizontal"
    return "Vertical"


def are_components_aligned(comp_a: Component, comp_b: Component,
                           packages: list[Package]) -> bool:
    """Return True if both components have the same orientation (both H or both V)."""
    orient_a = get_component_orientation(comp_a, packages)
    orient_b = get_component_orientation(comp_b, packages)
    if orient_a in ("Unknown", "Square") or orient_b in ("Unknown", "Square"):
        return True
    return orient_a == orient_b
