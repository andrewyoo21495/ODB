"""Symbol geometry generation for rendering.

Converts standard and user-defined symbols into matplotlib-compatible shapes.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
from matplotlib.patches import (
    Circle, Ellipse, FancyBboxPatch, PathPatch, Polygon, Rectangle, Wedge,
)
from matplotlib.path import Path as MplPath

from src.models import (
    ArcSegment, Contour, LineSegment, SurfaceRecord, UserSymbol,
)
from src.parsers.symbol_resolver import resolve_symbol


def symbol_to_patch(symbol_name: str, x: float, y: float,
                    rotation: float = 0.0, mirror: bool = False,
                    units: str = "INCH", unit_override: str = None,
                    color: str = "blue", alpha: float = 0.8,
                    resize_factor: float = None) -> Optional[object]:
    """Create a matplotlib patch for a standard symbol at a given position.

    Args:
        symbol_name: Standard symbol name (e.g., 'r120')
        x, y: Center position in board coordinates
        rotation: Rotation angle in degrees (clockwise)
        mirror: Whether the symbol is mirrored
        units: File coordinate units ('INCH' or 'MM')
        unit_override: Symbol-specific unit override ('I' or 'M')
        color: Fill color
        alpha: Opacity

    Returns:
        matplotlib patch or None if symbol cannot be rendered
    """
    sym = resolve_symbol(symbol_name)

    # Convert symbol dimensions to board coordinate units
    scale = _get_scale_factor(units, unit_override)

    if sym.type == "round":
        d = sym.params["diameter"] * scale
        return Circle((x, y), d / 2, color=color, alpha=alpha)

    elif sym.type == "square":
        s = sym.params["side"] * scale
        patch = Rectangle((x - s / 2, y - s / 2), s, s, color=color, alpha=alpha)
        if rotation:
            patch.set_angle(-rotation)  # matplotlib uses CCW
        return patch

    elif sym.type in ("rect", "rect_round", "rect_chamfer"):
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        patch = Rectangle((x - w / 2, y - h / 2), w, h, color=color, alpha=alpha)
        if rotation:
            patch.set_angle(-rotation)
        return patch

    elif sym.type == "oval":
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        patch = Ellipse((x, y), w, h, color=color, alpha=alpha)
        if rotation:
            patch.angle = -rotation
        return patch

    elif sym.type == "ellipse":
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        patch = Ellipse((x, y), w, h, color=color, alpha=alpha)
        if rotation:
            patch.angle = -rotation
        return patch

    elif sym.type == "diamond":
        w = sym.params["width"] * scale / 2
        h = sym.params["height"] * scale / 2
        verts = np.array([
            [x, y + h], [x + w, y], [x, y - h], [x - w, y], [x, y + h]
        ])
        if rotation:
            verts = _rotate_points(verts, x, y, rotation)
        return Polygon(verts, closed=True, color=color, alpha=alpha)

    elif sym.type == "donut_r":
        od = sym.params["outer_diameter"] * scale
        id_ = sym.params["inner_diameter"] * scale
        # Draw as two circles with path clipping
        return _make_donut_round(x, y, od / 2, id_ / 2, color, alpha)

    elif sym.type == "octagon":
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        r = sym.params["corner_size"] * scale
        verts = _octagon_vertices(x, y, w, h, r)
        return Polygon(verts, closed=True, color=color, alpha=alpha)

    elif sym.type == "triangle":
        base = sym.params["base"] * scale
        h = sym.params["height"] * scale
        verts = np.array([
            [x - base / 2, y - h / 2],
            [x + base / 2, y - h / 2],
            [x, y + h / 2],
            [x - base / 2, y - h / 2],
        ])
        if rotation:
            verts = _rotate_points(verts, x, y, rotation)
        return Polygon(verts, closed=True, color=color, alpha=alpha)

    # Fallback: small circle for unrecognized symbols
    return Circle((x, y), 0.001 if units == "INCH" else 0.025,
                  color=color, alpha=alpha * 0.5)


def get_line_width_for_symbol(symbol_name: str, units: str = "INCH",
                              unit_override: str = None) -> float:
    """Get the line width for a symbol used as a line/arc aperture."""
    sym = resolve_symbol(symbol_name)
    scale = _get_scale_factor(units, unit_override)

    if sym.type == "round":
        return sym.params.get("diameter", 0) * scale
    elif sym.type == "square":
        return sym.params.get("side", 0) * scale
    elif sym.type in ("rect", "rect_round", "rect_chamfer"):
        return min(sym.params.get("width", 0), sym.params.get("height", 0)) * scale
    elif sym.type == "oval":
        return min(sym.params.get("width", 0), sym.params.get("height", 0)) * scale
    else:
        return max(sym.width, sym.height) * scale if sym.width > 0 else 0.001


def contour_to_vertices(contour: Contour, num_arc_points: int = 16) -> np.ndarray:
    """Convert a Contour (with line and arc segments) to a vertex array.

    Arc segments are approximated with straight line segments.
    """
    points = [(contour.start.x, contour.start.y)]

    for seg in contour.segments:
        if isinstance(seg, LineSegment):
            points.append((seg.end.x, seg.end.y))
        elif isinstance(seg, ArcSegment):
            arc_pts = _arc_to_points(
                points[-1][0], points[-1][1],
                seg.end.x, seg.end.y,
                seg.center.x, seg.center.y,
                seg.clockwise, num_arc_points,
            )
            points.extend(arc_pts[1:])  # Skip first (already in list)

    return np.array(points)


def user_symbol_to_patches(symbol: UserSymbol, x: float, y: float,
                           rotation: float = 0.0, mirror: bool = False,
                           color: str = "blue", alpha: float = 0.8) -> list:
    """Convert a user-defined symbol to matplotlib patches at a given position."""
    patches = []

    for feature in symbol.features:
        if isinstance(feature, SurfaceRecord):
            for contour in feature.contours:
                verts = contour_to_vertices(contour)
                # Transform: mirror, rotate, translate
                if mirror:
                    verts[:, 1] = -verts[:, 1]
                if rotation:
                    verts = _rotate_points(verts, 0, 0, rotation)
                verts[:, 0] += x
                verts[:, 1] += y

                if contour.is_island:
                    patches.append(Polygon(verts, closed=True,
                                           color=color, alpha=alpha))
    return patches


def _get_scale_factor(units: str, unit_override: str = None) -> float:
    """Get scale factor to convert symbol dimensions to board coordinate units.

    Symbol dimensions are in mils (imperial) or microns (metric).
    Board coordinates are in inches or mm.
    """
    if unit_override == "I":
        # Explicit imperial: mils
        if units == "INCH":
            return 1.0 / 1000.0  # mils to inches
        else:
            return 0.0254  # mils to mm
    elif unit_override == "M":
        # Explicit metric: microns
        if units == "MM":
            return 1.0 / 1000.0  # microns to mm
        else:
            return 1.0 / 25400.0  # microns to inches
    else:
        # Default: mils if INCH, microns if MM
        if units == "INCH":
            return 1.0 / 1000.0
        else:
            return 1.0 / 1000.0


def _rotate_points(points: np.ndarray, cx: float, cy: float,
                   angle_deg: float) -> np.ndarray:
    """Rotate points clockwise around (cx, cy)."""
    angle_rad = math.radians(-angle_deg)  # Negative for clockwise
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    result = points.copy()
    result[:, 0] -= cx
    result[:, 1] -= cy

    new_x = result[:, 0] * cos_a - result[:, 1] * sin_a
    new_y = result[:, 0] * sin_a + result[:, 1] * cos_a

    result[:, 0] = new_x + cx
    result[:, 1] = new_y + cy

    return result


def _arc_to_points(xs: float, ys: float, xe: float, ye: float,
                   xc: float, yc: float, clockwise: bool,
                   num_points: int = 16) -> list[tuple[float, float]]:
    """Convert an arc to a list of points for polyline approximation."""
    radius = math.sqrt((xs - xc) ** 2 + (ys - yc) ** 2)
    if radius < 1e-10:
        return [(xe, ye)]

    start_angle = math.atan2(ys - yc, xs - xc)
    end_angle = math.atan2(ye - yc, xe - xc)

    if clockwise:
        if end_angle >= start_angle:
            end_angle -= 2 * math.pi
    else:
        if end_angle <= start_angle:
            end_angle += 2 * math.pi

    # Check for full circle
    if abs(xs - xe) < 1e-10 and abs(ys - ye) < 1e-10:
        if clockwise:
            end_angle = start_angle - 2 * math.pi
        else:
            end_angle = start_angle + 2 * math.pi

    angles = np.linspace(start_angle, end_angle, num_points)
    points = [(xc + radius * math.cos(a), yc + radius * math.sin(a)) for a in angles]

    # Ensure last point is exact
    points[-1] = (xe, ye)

    return points


def _make_donut_round(x: float, y: float, outer_r: float, inner_r: float,
                      color: str, alpha: float):
    """Create a round donut patch using Path with hole."""
    n = 64
    theta = np.linspace(0, 2 * np.pi, n, endpoint=False)

    # Outer circle (CCW)
    outer_x = x + outer_r * np.cos(theta)
    outer_y = y + outer_r * np.sin(theta)

    # Inner circle (CW for hole)
    inner_x = x + inner_r * np.cos(theta[::-1])
    inner_y = y + inner_r * np.sin(theta[::-1])

    verts = np.concatenate([
        np.column_stack([outer_x, outer_y]),
        [[outer_x[0], outer_y[0]]],  # close outer
        np.column_stack([inner_x, inner_y]),
        [[inner_x[0], inner_y[0]]],  # close inner
    ])

    codes = ([MplPath.MOVETO] + [MplPath.LINETO] * (n - 1) + [MplPath.CLOSEPOLY] +
             [MplPath.MOVETO] + [MplPath.LINETO] * (n - 1) + [MplPath.CLOSEPOLY])

    path = MplPath(verts, codes)
    return PathPatch(path, facecolor=color, alpha=alpha, edgecolor="none")


def _octagon_vertices(x: float, y: float, w: float, h: float, r: float) -> np.ndarray:
    """Generate octagon vertices centered at (x, y)."""
    hw, hh = w / 2, h / 2
    return np.array([
        [x - hw + r, y - hh],
        [x + hw - r, y - hh],
        [x + hw, y - hh + r],
        [x + hw, y + hh - r],
        [x + hw - r, y + hh],
        [x - hw + r, y + hh],
        [x - hw, y + hh - r],
        [x - hw, y - hh + r],
        [x - hw + r, y - hh],
    ])
