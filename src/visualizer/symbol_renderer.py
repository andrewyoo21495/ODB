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
    scale = _get_scale_factor(units, unit_override)

    if sym.type == "round":
        d = sym.params["diameter"] * scale
        return Circle((x, y), d / 2, facecolor=color, edgecolor="none", alpha=alpha)

    elif sym.type == "square":
        s = sym.params["side"] * scale
        corners = np.array([
            [x - s / 2, y - s / 2],
            [x + s / 2, y - s / 2],
            [x + s / 2, y + s / 2],
            [x - s / 2, y + s / 2],
        ])
        if mirror:
            corners = _mirror_points(corners, x)
        if rotation:
            corners = _rotate_points(corners, x, y, rotation)
        return Polygon(corners, closed=True, facecolor=color, edgecolor="none", alpha=alpha)

    elif sym.type in ("rect", "rect_round", "rect_chamfer"):
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        if sym.type == "rect_round":
            cr = sym.params.get("corner_radius", 0) * scale
            return _make_rounded_rect(x, y, w, h, cr, sym.params.get("corners", "1234"),
                                      rotation, color, alpha, mirror=mirror)
        elif sym.type == "rect_chamfer":
            cs = sym.params.get("corner_size", 0) * scale
            return _make_chamfered_rect(x, y, w, h, cs, sym.params.get("corners", "1234"),
                                        rotation, color, alpha, mirror=mirror)
        else:
            # Use Polygon so rotation is always around the pad centre.
            # Rectangle.set_angle() rotates around the lower-left anchor,
            # which displaces the pad for any non-zero rotation.
            corners = np.array([
                [x - w / 2, y - h / 2],
                [x + w / 2, y - h / 2],
                [x + w / 2, y + h / 2],
                [x - w / 2, y + h / 2],
            ])
            if mirror:
                corners = _mirror_points(corners, x)
            if rotation:
                corners = _rotate_points(corners, x, y, rotation)
            return Polygon(corners, closed=True, facecolor=color, edgecolor="none", alpha=alpha)

    elif sym.type == "oval":
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        return _make_oval(x, y, w, h, rotation, color, alpha, mirror=mirror)

    elif sym.type == "ellipse":
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        patch = Ellipse((x, y), w, h, facecolor=color, edgecolor="none", alpha=alpha)
        # orient_def: mirror flips the rotation direction
        angle = -rotation if not mirror else rotation
        if angle:
            patch.angle = angle
        return patch

    elif sym.type == "diamond":
        w = sym.params["width"] * scale / 2
        h = sym.params["height"] * scale / 2
        verts = np.array([
            [x, y + h], [x + w, y], [x, y - h], [x - w, y], [x, y + h]
        ])
        if mirror:
            verts = _mirror_points(verts, x)
        if rotation:
            verts = _rotate_points(verts, x, y, rotation)
        return Polygon(verts, closed=True, facecolor=color, edgecolor="none", alpha=alpha)

    elif sym.type == "donut_r":
        od = sym.params["outer_diameter"] * scale
        id_ = sym.params["inner_diameter"] * scale
        return _make_donut_round(x, y, od / 2, id_ / 2, color, alpha)

    elif sym.type == "donut_s":
        od = sym.params["outer_size"] * scale
        id_ = sym.params["inner_size"] * scale
        return _make_donut_square(x, y, od, id_, rotation, color, alpha,
                                  mirror=mirror)

    elif sym.type == "donut_s_round":
        od = sym.params["outer_size"] * scale
        id_ = sym.params["inner_size"] * scale
        rad = sym.params.get("corner_radius", 0) * scale
        corners = sym.params.get("corners", "1234")
        return _make_donut_square(x, y, od, id_, rotation, color, alpha,
                                  corner_radius=rad, corners=corners,
                                  mirror=mirror)

    elif sym.type == "donut_sr":
        od = sym.params["outer_size"] * scale
        id_ = sym.params["inner_diameter"] * scale
        return _make_donut_square_round(x, y, od, id_, rotation, color, alpha,
                                        mirror=mirror)

    elif sym.type == "donut_rc":
        ow = sym.params["outer_width"] * scale
        oh = sym.params["outer_height"] * scale
        lw = sym.params["line_width"] * scale
        return _make_donut_rect(x, y, ow, oh, lw, rotation, color, alpha,
                                mirror=mirror)

    elif sym.type == "donut_rc_round":
        ow = sym.params["outer_width"] * scale
        oh = sym.params["outer_height"] * scale
        lw = sym.params["line_width"] * scale
        rad = sym.params.get("corner_radius", 0) * scale
        corners = sym.params.get("corners", "1234")
        return _make_donut_rect(x, y, ow, oh, lw, rotation, color, alpha,
                                corner_radius=rad, corners=corners,
                                mirror=mirror)

    elif sym.type == "donut_o":
        ow = sym.params["outer_width"] * scale
        oh = sym.params["outer_height"] * scale
        lw = sym.params["line_width"] * scale
        return _make_donut_oval(x, y, ow, oh, lw, rotation, color, alpha,
                                mirror=mirror)

    elif sym.type == "octagon":
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        r = sym.params["corner_size"] * scale
        verts = _octagon_vertices(x, y, w, h, r)
        if mirror:
            verts = _mirror_points(verts, x)
        if rotation:
            verts = _rotate_points(verts, x, y, rotation)
        return Polygon(verts, closed=True, facecolor=color, edgecolor="none", alpha=alpha)

    elif sym.type == "triangle":
        base = sym.params["base"] * scale
        h = sym.params["height"] * scale
        verts = np.array([
            [x - base / 2, y - h / 2],
            [x + base / 2, y - h / 2],
            [x, y + h / 2],
            [x - base / 2, y - h / 2],
        ])
        if mirror:
            verts = _mirror_points(verts, x)
        if rotation:
            verts = _rotate_points(verts, x, y, rotation)
        return Polygon(verts, closed=True, facecolor=color, edgecolor="none", alpha=alpha)

    elif sym.type in ("hex_l", "hex_s"):
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        r = sym.params["corner_size"] * scale
        verts = _hexagon_vertices(x, y, w, h, r, sym.type)
        if mirror:
            verts = _mirror_points(verts, x)
        if rotation:
            verts = _rotate_points(verts, x, y, rotation)
        return Polygon(verts, closed=True, facecolor=color, edgecolor="none", alpha=alpha)

    elif sym.type == "half_oval":
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        return _make_half_oval(x, y, w, h, rotation, color, alpha,
                               mirror=mirror)

    elif sym.type == "butterfly":
        d = sym.params["diameter"] * scale
        return _make_butterfly(x, y, d, rotation, color, alpha, round_shape=True,
                               mirror=mirror)

    elif sym.type == "sq_butterfly":
        s = sym.params["side"] * scale
        return _make_butterfly(x, y, s, rotation, color, alpha, round_shape=False,
                               mirror=mirror)

    # Thermal symbols
    elif sym.type == "thr":
        return _make_round_thermal(x, y, sym.params, scale, rotation, color, alpha,
                                    rounded_spokes=True)

    elif sym.type == "ths":
        return _make_round_thermal(x, y, sym.params, scale, rotation, color, alpha,
                                    rounded_spokes=False)

    elif sym.type == "s_ths":
        return _make_square_thermal(x, y, sym.params, scale, rotation, color, alpha,
                                     open_corners=False)

    elif sym.type == "s_ths_round":
        return _make_square_thermal(x, y, sym.params, scale, rotation, color, alpha,
                                     open_corners=False,
                                     corner_radius=sym.params.get("corner_radius", 0) * scale)

    elif sym.type == "s_tho":
        return _make_square_thermal(x, y, sym.params, scale, rotation, color, alpha,
                                     open_corners=True)

    elif sym.type == "s_thr":
        return _make_line_thermal(x, y, sym.params, scale, rotation, color, alpha)

    elif sym.type == "sr_ths":
        return _make_sr_thermal(x, y, sym.params, scale, rotation, color, alpha)

    elif sym.type in ("rc_ths", "rc_ths_round"):
        return _make_rect_thermal(x, y, sym.params, scale, rotation, color, alpha,
                                   open_corners=False)

    elif sym.type == "rc_tho":
        return _make_rect_thermal(x, y, sym.params, scale, rotation, color, alpha,
                                   open_corners=True)

    elif sym.type == "o_ths":
        return _make_oval_thermal(x, y, sym.params, scale, rotation, color, alpha)

    elif sym.type == "oblong_ths":
        return _make_oval_thermal(x, y, sym.params, scale, rotation, color, alpha)

    # Stencil symbols
    elif sym.type == "hplate":
        return _make_hplate(x, y, sym.params, scale, rotation, color, alpha,
                            mirror=mirror)

    elif sym.type == "rhplate":
        return _make_rhplate(x, y, sym.params, scale, rotation, color, alpha,
                             mirror=mirror)

    elif sym.type == "fhplate":
        return _make_fhplate(x, y, sym.params, scale, rotation, color, alpha,
                             mirror=mirror)

    elif sym.type == "radhplate":
        return _make_radhplate(x, y, sym.params, scale, rotation, color, alpha,
                               mirror=mirror)

    elif sym.type == "dshape":
        return _make_dshape(x, y, sym.params, scale, rotation, color, alpha,
                            mirror=mirror)

    elif sym.type == "cross":
        return _make_cross(x, y, sym.params, scale, rotation, color, alpha,
                           mirror=mirror)

    elif sym.type == "dogbone":
        return _make_dogbone(x, y, sym.params, scale, rotation, color, alpha,
                             mirror=mirror)

    elif sym.type == "dpack":
        return _make_dpack(x, y, sym.params, scale, rotation, color, alpha,
                           mirror=mirror)

    elif sym.type == "moire":
        return _make_moire(x, y, sym.params, scale, rotation, color, alpha)

    elif sym.type == "hole":
        d = sym.params["diameter"] * scale
        return _make_donut_round(x, y, d / 2, d / 2 * 0.8, color, alpha)

    elif sym.type == "null":
        return None

    # Fallback: small circle for unrecognized symbols (~1 mil in mm)
    return Circle((x, y), 0.025, facecolor=color, edgecolor="none", alpha=alpha * 0.5)


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


def contour_to_vertices(contour: Contour, num_arc_points: int = 32) -> np.ndarray:
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
    """Convert a user-defined symbol to matplotlib patches at a given position.

    Groups each island contour with its subsequent hole contours and renders
    them as compound Path patches so that holes are true cutouts.
    """
    patches = []

    for feature in symbol.features:
        if isinstance(feature, SurfaceRecord):
            # Transform all contour vertices first
            transformed: list[tuple[bool, np.ndarray]] = []
            for contour in feature.contours:
                verts = contour_to_vertices(contour)
                if mirror:
                    verts[:, 0] = -verts[:, 0]
                if rotation:
                    verts = _rotate_points(verts, 0, 0, rotation)
                verts[:, 0] += x
                verts[:, 1] += y
                transformed.append((contour.is_island, verts))

            # Group: each island with its subsequent holes
            groups: list[tuple[np.ndarray, list[np.ndarray]]] = []
            for is_island, verts in transformed:
                if len(verts) < 3:
                    continue
                if is_island:
                    groups.append((verts, []))
                else:
                    if groups:
                        groups[-1][1].append(verts)

            for island_verts, hole_list in groups:
                if not hole_list:
                    patches.append(Polygon(island_verts, closed=True,
                                           facecolor=color, edgecolor="none", alpha=alpha))
                else:
                    # Compound path with holes
                    all_verts = []
                    all_codes = []
                    n = len(island_verts)
                    all_verts.extend(island_verts.tolist())
                    all_verts.append(island_verts[0].tolist())
                    all_codes.append(MplPath.MOVETO)
                    all_codes.extend([MplPath.LINETO] * (n - 1))
                    all_codes.append(MplPath.CLOSEPOLY)
                    for hv in hole_list:
                        nh = len(hv)
                        all_verts.extend(hv.tolist())
                        all_verts.append(hv[0].tolist())
                        all_codes.append(MplPath.MOVETO)
                        all_codes.extend([MplPath.LINETO] * (nh - 1))
                        all_codes.append(MplPath.CLOSEPOLY)
                    path = MplPath(all_verts, all_codes)
                    patches.append(PathPatch(path, facecolor=color,
                                             alpha=alpha, edgecolor="none"))
    return patches


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_scale_factor(units: str, unit_override: str = None) -> float:
    """Get scale factor to convert symbol dimensions to mm (board coordinate units).

    All layer coordinates are normalised to MM, so this function always returns
    a factor that converts raw symbol numbers into mm.

    Standard symbol name numbers are encoded in the *sub-unit* of the file's
    declared unit:
      - INCH files → mils  (thousandths of an inch): ×0.0254 to get mm
      - MM   files → microns (thousandths of a mm):  ÷1000   to get mm

    A per-symbol ``unit_override`` from the symbol table can override this:
      - ``"I"`` → always mils (×0.0254 to get mm)
      - ``"M"`` → always microns (÷1000 to get mm)
    """
    if unit_override == "I":
        return 0.0254          # mils → mm
    if unit_override == "M":
        return 1.0 / 1000.0   # microns → mm
    # Default: encoding follows the file's declared unit
    if units == "INCH":
        return 0.0254          # mils → mm  (1 mil = 0.0254 mm)
    else:
        return 1.0 / 1000.0   # microns → mm


def _mirror_points(points: np.ndarray, cx: float) -> np.ndarray:
    """Mirror points in the X-axis around centre *cx*.

    ODB++ orient_def convention: orient_def values 4-7 and 9 require
    an X-axis mirror **before** rotation is applied.
    """
    result = points.copy()
    result[:, 0] = 2 * cx - result[:, 0]
    return result


def _rotate_points(points: np.ndarray, cx: float, cy: float,
                   angle_deg: float) -> np.ndarray:
    """Rotate points clockwise around (cx, cy)."""
    angle_rad = math.radians(-angle_deg)
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
    """Convert an arc to a list of points for polyline approximation.

    Uses the average of the start-to-centre and end-to-centre distances
    as the arc radius so that small data-precision discrepancies do not
    distort the curve.  The first and last generated points are forced to
    the exact start / end coordinates for continuity with adjacent
    segments.
    """
    r_start = math.sqrt((xs - xc) ** 2 + (ys - yc) ** 2)
    r_end = math.sqrt((xe - xc) ** 2 + (ye - yc) ** 2)
    radius = (r_start + r_end) / 2

    if radius < 1e-10:
        # Degenerate arc — centre coincides with endpoints.
        return [(xs, ys), (xe, ye)]

    start_angle = math.atan2(ys - yc, xs - xc)
    end_angle = math.atan2(ye - yc, xe - xc)

    if clockwise:
        if end_angle >= start_angle:
            end_angle -= 2 * math.pi
    else:
        if end_angle <= start_angle:
            end_angle += 2 * math.pi

    # Full-circle case: start and end points coincide.
    if abs(xs - xe) < 1e-10 and abs(ys - ye) < 1e-10:
        if clockwise:
            end_angle = start_angle - 2 * math.pi
        else:
            end_angle = start_angle + 2 * math.pi

    angles = np.linspace(start_angle, end_angle, num_points)
    points = [(xc + radius * math.cos(a), yc + radius * math.sin(a)) for a in angles]
    # Force exact start and end for geometric continuity.
    points[0] = (xs, ys)
    points[-1] = (xe, ye)

    return points


def _circle_points(cx: float, cy: float, r: float, n: int = 64) -> np.ndarray:
    """Generate points for a circle."""
    theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.column_stack([cx + r * np.cos(theta), cy + r * np.sin(theta)])


def _rect_points(cx: float, cy: float, w: float, h: float) -> np.ndarray:
    """Generate rectangle vertices centered at (cx, cy)."""
    hw, hh = w / 2, h / 2
    return np.array([
        [cx - hw, cy - hh], [cx + hw, cy - hh],
        [cx + hw, cy + hh], [cx - hw, cy + hh],
    ])


def _make_path_with_hole(outer: np.ndarray, inner: np.ndarray) -> PathPatch:
    """Create a PathPatch from outer boundary (CCW) and inner hole (CW)."""
    n_outer = len(outer)
    n_inner = len(inner)

    verts = np.concatenate([
        outer, [outer[0]],
        inner, [inner[0]],
    ])

    codes = ([MplPath.MOVETO] + [MplPath.LINETO] * (n_outer - 1) + [MplPath.CLOSEPOLY] +
             [MplPath.MOVETO] + [MplPath.LINETO] * (n_inner - 1) + [MplPath.CLOSEPOLY])

    return MplPath(verts, codes)


# ---------------------------------------------------------------------------
# Donut shapes
# ---------------------------------------------------------------------------

def _make_donut_round(x: float, y: float, outer_r: float, inner_r: float,
                      color: str, alpha: float):
    """Create a round donut patch using Path with hole."""
    n = 64
    outer = _circle_points(x, y, outer_r, n)
    inner = _circle_points(x, y, inner_r, n)[::-1]
    path = _make_path_with_hole(outer, inner)
    return PathPatch(path, facecolor=color, alpha=alpha, edgecolor="none")


def _make_donut_square(x: float, y: float, outer_size: float, inner_size: float,
                       rotation: float, color: str, alpha: float,
                       corner_radius: float = 0, corners: str = "1234",
                       mirror: bool = False):
    """Create a square donut (square outer, square inner hole)."""
    if corner_radius > 0:
        outer = _rounded_rect_points(x, y, outer_size, outer_size, corner_radius, corners)
    else:
        outer = _rect_points(x, y, outer_size, outer_size)
    inner = _rect_points(x, y, inner_size, inner_size)[::-1]
    if mirror:
        outer = _mirror_points(outer, x)
        inner = _mirror_points(inner, x)
    if rotation:
        outer = _rotate_points(outer, x, y, rotation)
        inner = _rotate_points(inner, x, y, rotation)
    path = _make_path_with_hole(outer, inner)
    return PathPatch(path, facecolor=color, alpha=alpha, edgecolor="none")


def _make_donut_square_round(x: float, y: float, outer_size: float, inner_diam: float,
                             rotation: float, color: str, alpha: float,
                             mirror: bool = False):
    """Create a square/round donut (square outer, round inner hole)."""
    outer = _rect_points(x, y, outer_size, outer_size)
    inner = _circle_points(x, y, inner_diam / 2, 64)[::-1]
    if mirror:
        outer = _mirror_points(outer, x)
    if rotation:
        outer = _rotate_points(outer, x, y, rotation)
    path = _make_path_with_hole(outer, inner)
    return PathPatch(path, facecolor=color, alpha=alpha, edgecolor="none")


def _make_donut_rect(x: float, y: float, ow: float, oh: float, lw: float,
                     rotation: float, color: str, alpha: float,
                     corner_radius: float = 0, corners: str = "1234",
                     mirror: bool = False):
    """Create a rectangle donut."""
    iw = ow - 2 * lw
    ih = oh - 2 * lw
    if corner_radius > 0:
        outer = _rounded_rect_points(x, y, ow, oh, corner_radius, corners)
    else:
        outer = _rect_points(x, y, ow, oh)
    inner = _rect_points(x, y, iw, ih)[::-1]
    if mirror:
        outer = _mirror_points(outer, x)
        inner = _mirror_points(inner, x)
    if rotation:
        outer = _rotate_points(outer, x, y, rotation)
        inner = _rotate_points(inner, x, y, rotation)
    path = _make_path_with_hole(outer, inner)
    return PathPatch(path, facecolor=color, alpha=alpha, edgecolor="none")


def _make_donut_oval(x: float, y: float, ow: float, oh: float, lw: float,
                     rotation: float, color: str, alpha: float,
                     mirror: bool = False):
    """Create an oval donut."""
    outer = _oval_points(x, y, ow, oh, 64)
    iw = ow - 2 * lw
    ih = oh - 2 * lw
    inner = _oval_points(x, y, iw, ih, 64)[::-1]
    if mirror:
        outer = _mirror_points(outer, x)
        inner = _mirror_points(inner, x)
    if rotation:
        outer = _rotate_points(outer, x, y, rotation)
        inner = _rotate_points(inner, x, y, rotation)
    path = _make_path_with_hole(outer, inner)
    return PathPatch(path, facecolor=color, alpha=alpha, edgecolor="none")


# ---------------------------------------------------------------------------
# Basic shape helpers
# ---------------------------------------------------------------------------

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


def _hexagon_vertices(x: float, y: float, w: float, h: float, r: float,
                      hex_type: str) -> np.ndarray:
    """Generate hexagon vertices.
    hex_l: horizontal hexagon (flat top/bottom)
    hex_s: vertical hexagon (flat left/right)
    """
    hw, hh = w / 2, h / 2
    if hex_type == "hex_l":
        # Horizontal hexagon: flat top and bottom, pointed left and right
        return np.array([
            [x - hw, y],
            [x - hw + r, y - hh],
            [x + hw - r, y - hh],
            [x + hw, y],
            [x + hw - r, y + hh],
            [x - hw + r, y + hh],
            [x - hw, y],
        ])
    else:  # hex_s
        # Vertical hexagon: flat left and right, pointed top and bottom
        return np.array([
            [x, y - hh],
            [x + hw, y - hh + r],
            [x + hw, y + hh - r],
            [x, y + hh],
            [x - hw, y + hh - r],
            [x - hw, y - hh + r],
            [x, y - hh],
        ])


def _oval_points(cx: float, cy: float, w: float, h: float, n: int = 64) -> np.ndarray:
    """Generate points for an oval (stadium/discorectangle shape).
    An oval is a rectangle with semicircular ends on the shorter sides.
    """
    hw, hh = w / 2, h / 2
    if w >= h:
        # Horizontal oval: semicircles on left/right
        r = hh
        straight = hw - r
        pts = []
        # Right semicircle
        for i in range(n // 2):
            angle = -math.pi / 2 + i * math.pi / (n // 2 - 1)
            pts.append([cx + straight + r * math.cos(angle), cy + r * math.sin(angle)])
        # Left semicircle
        for i in range(n // 2):
            angle = math.pi / 2 + i * math.pi / (n // 2 - 1)
            pts.append([cx - straight + r * math.cos(angle), cy + r * math.sin(angle)])
    else:
        # Vertical oval: semicircles on top/bottom
        r = hw
        straight = hh - r
        pts = []
        # Top semicircle
        for i in range(n // 2):
            angle = 0 + i * math.pi / (n // 2 - 1)
            pts.append([cx + r * math.cos(angle), cy + straight + r * math.sin(angle)])
        # Bottom semicircle
        for i in range(n // 2):
            angle = math.pi + i * math.pi / (n // 2 - 1)
            pts.append([cx + r * math.cos(angle), cy - straight + r * math.sin(angle)])
    return np.array(pts)


def _make_oval(x: float, y: float, w: float, h: float,
               rotation: float, color: str, alpha: float,
               mirror: bool = False):
    """Create an oval (stadium) shape."""
    pts = _oval_points(x, y, w, h)
    if mirror:
        pts = _mirror_points(pts, x)
    if rotation:
        pts = _rotate_points(pts, x, y, rotation)
    return Polygon(pts, closed=True, facecolor=color, edgecolor="none", alpha=alpha)


def _make_half_oval(x: float, y: float, w: float, h: float,
                    rotation: float, color: str, alpha: float,
                    mirror: bool = False):
    """Create a half-oval shape (flat bottom, rounded top)."""
    hw, hh = w / 2, h / 2
    pts = []
    # Bottom flat edge
    pts.append([x - hw, y - hh])
    pts.append([x + hw, y - hh])
    # Top semicircle
    n = 32
    for i in range(n + 1):
        angle = -math.pi / 2 + i * math.pi / n
        pts.append([x + hw * math.cos(angle), y - hh + h * (0.5 + 0.5 * math.sin(angle))])
    verts = np.array(pts)
    if mirror:
        verts = _mirror_points(verts, x)
    if rotation:
        verts = _rotate_points(verts, x, y, rotation)
    return Polygon(verts, closed=True, facecolor=color, edgecolor="none", alpha=alpha)


def _make_butterfly(x: float, y: float, size: float, rotation: float,
                    color: str, alpha: float, round_shape: bool = True,
                    mirror: bool = False):
    """Create a butterfly shape (two quarter segments opposite each other)."""
    r = size / 2
    pts = []
    n = 16
    if round_shape:
        # Two opposite quarter-circle wedges (round butterfly)
        # Top-right quadrant
        for i in range(n + 1):
            angle = 0 + i * (math.pi / 2) / n
            pts.append([x + r * math.cos(angle), y + r * math.sin(angle)])
        pts.append([x, y])
        # Bottom-left quadrant
        for i in range(n + 1):
            angle = math.pi + i * (math.pi / 2) / n
            pts.append([x + r * math.cos(angle), y + r * math.sin(angle)])
        pts.append([x, y])
    else:
        # Square butterfly: two opposite quarter-squares
        pts = [
            [x, y], [x + r, y], [x + r, y + r], [x, y + r],
            [x, y], [x - r, y], [x - r, y - r], [x, y - r],
            [x, y],
        ]
    verts = np.array(pts)
    if mirror:
        verts[:, 0] = 2 * x - verts[:, 0]
    if rotation:
        verts = _rotate_points(verts, x, y, rotation)
    return Polygon(verts, closed=True, facecolor=color, edgecolor="none", alpha=alpha)


def _rounded_rect_points(cx: float, cy: float, w: float, h: float,
                         r: float, corners: str = "1234", n_arc: int = 8) -> np.ndarray:
    """Generate rounded rectangle points. Corners numbered 1=TR, 2=TL, 3=BL, 4=BR (CCW from TR)."""
    hw, hh = w / 2, h / 2
    r = min(r, hw, hh)
    pts = []

    # Bottom-right corner (4)
    if "4" in corners:
        for i in range(n_arc + 1):
            angle = -math.pi / 2 + i * (math.pi / 2) / n_arc
            pts.append([cx + hw - r + r * math.cos(angle),
                        cy - hh + r + r * math.sin(angle)])
    else:
        pts.append([cx + hw, cy - hh])

    # Top-right corner (1)
    if "1" in corners:
        for i in range(n_arc + 1):
            angle = 0 + i * (math.pi / 2) / n_arc
            pts.append([cx + hw - r + r * math.cos(angle),
                        cy + hh - r + r * math.sin(angle)])
    else:
        pts.append([cx + hw, cy + hh])

    # Top-left corner (2)
    if "2" in corners:
        for i in range(n_arc + 1):
            angle = math.pi / 2 + i * (math.pi / 2) / n_arc
            pts.append([cx - hw + r + r * math.cos(angle),
                        cy + hh - r + r * math.sin(angle)])
    else:
        pts.append([cx - hw, cy + hh])

    # Bottom-left corner (3)
    if "3" in corners:
        for i in range(n_arc + 1):
            angle = math.pi + i * (math.pi / 2) / n_arc
            pts.append([cx - hw + r + r * math.cos(angle),
                        cy - hh + r + r * math.sin(angle)])
    else:
        pts.append([cx - hw, cy - hh])

    return np.array(pts)


def _make_rounded_rect(cx: float, cy: float, w: float, h: float, r: float,
                       corners: str, rotation: float, color: str, alpha: float,
                       mirror: bool = False):
    """Create a rounded rectangle patch."""
    pts = _rounded_rect_points(cx, cy, w, h, r, corners)
    if mirror:
        pts = _mirror_points(pts, cx)
    if rotation:
        pts = _rotate_points(pts, cx, cy, rotation)
    return Polygon(pts, closed=True, facecolor=color, edgecolor="none", alpha=alpha)


def _make_chamfered_rect(cx: float, cy: float, w: float, h: float, cs: float,
                         corners: str, rotation: float, color: str, alpha: float,
                         mirror: bool = False):
    """Create a chamfered rectangle patch. Corners: 1=TR, 2=TL, 3=BL, 4=BR."""
    hw, hh = w / 2, h / 2
    cs = min(cs, hw, hh)
    pts = []

    # Start bottom-right, go CCW
    if "4" in corners:
        pts.extend([[cx + hw, cy - hh + cs], [cx + hw - cs, cy - hh]])
    else:
        pts.append([cx + hw, cy - hh])

    if "3" in corners:
        pts.extend([[cx - hw + cs, cy - hh], [cx - hw, cy - hh + cs]])
    else:
        pts.append([cx - hw, cy - hh])

    if "2" in corners:
        pts.extend([[cx - hw, cy + hh - cs], [cx - hw + cs, cy + hh]])
    else:
        pts.append([cx - hw, cy + hh])

    if "1" in corners:
        pts.extend([[cx + hw - cs, cy + hh], [cx + hw, cy + hh - cs]])
    else:
        pts.append([cx + hw, cy + hh])

    verts = np.array(pts)
    if mirror:
        verts = _mirror_points(verts, cx)
    if rotation:
        verts = _rotate_points(verts, cx, cy, rotation)
    return Polygon(verts, closed=True, facecolor=color, edgecolor="none", alpha=alpha)


# ---------------------------------------------------------------------------
# Thermal shapes
# ---------------------------------------------------------------------------

def _make_round_thermal(x: float, y: float, params: dict, scale: float,
                        rotation: float, color: str, alpha: float,
                        rounded_spokes: bool = True):
    """Create a round thermal (thr or ths).
    A ring (donut) with spoke gaps cut out.
    """
    od = params["outer_diameter"] * scale
    id_ = params["inner_diameter"] * scale
    angle = params["angle"]
    num_spokes = params["num_spokes"]
    gap = params["gap"] * scale
    outer_r = od / 2
    inner_r = id_ / 2

    if num_spokes == 0:
        return _make_donut_round(x, y, outer_r, inner_r, color, alpha)

    # Build the thermal as ring segments between gaps
    gap_angle = 2 * math.asin(min(gap / (2 * outer_r), 1.0)) * 180 / math.pi
    segment_angle = 360.0 / num_spokes - gap_angle

    all_verts = []
    all_codes = []
    n_arc = 24

    for i in range(num_spokes):
        start_a = angle + i * (360.0 / num_spokes) + gap_angle / 2 + rotation
        end_a = start_a + segment_angle

        # Outer arc
        outer_pts = []
        for j in range(n_arc + 1):
            a = math.radians(start_a + j * (end_a - start_a) / n_arc)
            outer_pts.append([x + outer_r * math.cos(a), y + outer_r * math.sin(a)])

        # Inner arc (reversed)
        inner_pts = []
        for j in range(n_arc + 1):
            a = math.radians(end_a - j * (end_a - start_a) / n_arc)
            inner_pts.append([x + inner_r * math.cos(a), y + inner_r * math.sin(a)])

        seg_verts = outer_pts + inner_pts + [outer_pts[0]]
        seg_codes = ([MplPath.MOVETO] + [MplPath.LINETO] * (len(seg_verts) - 2) +
                     [MplPath.CLOSEPOLY])
        all_verts.extend(seg_verts)
        all_codes.extend(seg_codes)

    path = MplPath(np.array(all_verts), all_codes)
    return PathPatch(path, facecolor=color, alpha=alpha, edgecolor="none")


def _make_square_thermal(x: float, y: float, params: dict, scale: float,
                         rotation: float, color: str, alpha: float,
                         open_corners: bool = False, corner_radius: float = 0):
    """Create a square thermal (s_ths or s_tho).
    A square ring with spoke gaps.
    """
    os_ = params["outer_size"] * scale
    is_ = params["inner_size"] * scale
    angle = params["angle"]
    num_spokes = params["num_spokes"]
    gap = params["gap"] * scale / 2

    ho = os_ / 2
    hi = is_ / 2

    # For simplicity, render as an outer square minus inner square minus gap rectangles
    if corner_radius > 0:
        outer = _rounded_rect_points(x, y, os_, os_, corner_radius)
    else:
        outer = _rect_points(x, y, os_, os_)
    inner = _rect_points(x, y, is_, is_)[::-1]

    if rotation or angle:
        total_rot = rotation + angle
        outer = _rotate_points(outer, x, y, total_rot)
        inner = _rotate_points(inner, x, y, total_rot)

    # Build the path with outer and inner
    path = _make_path_with_hole(outer, inner)

    # Create base patch, then clip spoke gaps by drawing gap rectangles
    # For a simpler approach: draw the ring, spoke gaps will reduce accuracy
    # but provides reasonable visual
    base = PathPatch(path, facecolor=color, alpha=alpha, edgecolor="none")
    return base


def _make_line_thermal(x: float, y: float, params: dict, scale: float,
                       rotation: float, color: str, alpha: float):
    """Create a line thermal (s_thr) - square outer with line spokes (rounded ends)."""
    os_ = params["outer_size"] * scale
    is_ = params["inner_size"] * scale
    gap = params["gap"] * scale / 2
    line_w = (os_ - is_) / 2

    # Draw as a square donut
    outer = _rect_points(x, y, os_, os_)
    inner = _rect_points(x, y, is_, is_)[::-1]

    total_rot = rotation + params.get("angle", 45)
    if total_rot:
        outer = _rotate_points(outer, x, y, total_rot)
        inner = _rotate_points(inner, x, y, total_rot)

    path = _make_path_with_hole(outer, inner)
    return PathPatch(path, facecolor=color, alpha=alpha, edgecolor="none")


def _make_sr_thermal(x: float, y: float, params: dict, scale: float,
                     rotation: float, color: str, alpha: float):
    """Create a square-round thermal (sr_ths) - square outer, round inner."""
    os_ = params["outer_size"] * scale
    id_ = params["inner_diameter"] * scale
    angle = params["angle"]
    num_spokes = params["num_spokes"]
    gap = params["gap"] * scale / 2

    outer = _rect_points(x, y, os_, os_)
    inner = _circle_points(x, y, id_ / 2, 64)[::-1]

    total_rot = rotation + angle
    if total_rot:
        outer = _rotate_points(outer, x, y, total_rot)
        inner = _rotate_points(inner, x, y, total_rot)

    path = _make_path_with_hole(outer, inner)
    return PathPatch(path, facecolor=color, alpha=alpha, edgecolor="none")


def _make_rect_thermal(x: float, y: float, params: dict, scale: float,
                       rotation: float, color: str, alpha: float,
                       open_corners: bool = False):
    """Create a rectangular thermal (rc_ths or rc_tho)."""
    rw = params["width"] * scale
    rh = params["height"] * scale
    air_gap = params.get("air_gap", 0) * scale
    angle = params["angle"]
    gap = params["gap"] * scale / 2
    cr = params.get("corner_radius", 0) * scale

    iw = rw - 2 * air_gap
    ih = rh - 2 * air_gap

    if cr > 0:
        corners = params.get("corners", "1234")
        outer = _rounded_rect_points(x, y, rw, rh, cr, corners)
    else:
        outer = _rect_points(x, y, rw, rh)
    inner = _rect_points(x, y, iw, ih)[::-1]

    total_rot = rotation + angle
    if total_rot:
        outer = _rotate_points(outer, x, y, total_rot)
        inner = _rotate_points(inner, x, y, total_rot)

    path = _make_path_with_hole(outer, inner)
    return PathPatch(path, facecolor=color, alpha=alpha, edgecolor="none")


def _make_oval_thermal(x: float, y: float, params: dict, scale: float,
                       rotation: float, color: str, alpha: float):
    """Create an oval thermal (o_ths or oblong_ths)."""
    ow = params["outer_width"] * scale
    oh = params["outer_height"] * scale
    lw = params.get("line_width", 0) * scale
    angle = params["angle"]

    iw = ow - 2 * lw
    ih = oh - 2 * lw

    outer = _oval_points(x, y, ow, oh, 64)
    inner = _oval_points(x, y, max(iw, 0.001), max(ih, 0.001), 64)[::-1]

    total_rot = rotation + angle
    if total_rot:
        outer = _rotate_points(outer, x, y, total_rot)
        inner = _rotate_points(inner, x, y, total_rot)

    path = _make_path_with_hole(outer, inner)
    return PathPatch(path, facecolor=color, alpha=alpha, edgecolor="none")


# ---------------------------------------------------------------------------
# Stencil design symbols
# ---------------------------------------------------------------------------

def _make_hplate(x: float, y: float, params: dict, scale: float,
                 rotation: float, color: str, alpha: float,
                 mirror: bool = False):
    """Create a home plate symbol.
    Rectangular shape with one side having a triangular cut (like home plate in baseball).
    The cut is on the right side.
    """
    w = params["width"] * scale
    h = params["height"] * scale
    c = params["cut_size"] * scale
    hw, hh = w / 2, h / 2

    # Home plate: rectangle with right side cut to a point
    pts = [
        [x - hw, y - hh],
        [x + hw - c, y - hh],
        [x + hw, y],
        [x + hw - c, y + hh],
        [x - hw, y + hh],
    ]
    verts = np.array(pts)
    if mirror:
        verts[:, 0] = 2 * x - verts[:, 0]
    if rotation:
        verts = _rotate_points(verts, x, y, rotation)
    return Polygon(verts, closed=True, facecolor=color, edgecolor="none", alpha=alpha)


def _make_rhplate(x: float, y: float, params: dict, scale: float,
                  rotation: float, color: str, alpha: float,
                  mirror: bool = False):
    """Create an inverted home plate (rhplate).
    Like hplate but the cut is on the left side (inverted).
    """
    w = params["width"] * scale
    h = params["height"] * scale
    c = params["cut_size"] * scale
    hw, hh = w / 2, h / 2

    pts = [
        [x - hw + c, y - hh],
        [x + hw, y - hh],
        [x + hw, y + hh],
        [x - hw + c, y + hh],
        [x - hw, y],
    ]
    verts = np.array(pts)
    if mirror:
        verts[:, 0] = 2 * x - verts[:, 0]
    if rotation:
        verts = _rotate_points(verts, x, y, rotation)
    return Polygon(verts, closed=True, facecolor=color, edgecolor="none", alpha=alpha)


def _make_fhplate(x: float, y: float, params: dict, scale: float,
                  rotation: float, color: str, alpha: float,
                  mirror: bool = False):
    """Create a flat home plate (fhplate).
    Hexagonal shape with cuts on both vertical sides.
    """
    w = params["width"] * scale
    h = params["height"] * scale
    vc = params["vert_cut"] * scale
    hc = params["horiz_cut"] * scale
    hw, hh = w / 2, h / 2

    pts = [
        [x - hw + hc, y - hh],
        [x + hw - hc, y - hh],
        [x + hw, y - hh + vc],
        [x + hw, y + hh - vc],
        [x + hw - hc, y + hh],
        [x - hw + hc, y + hh],
        [x - hw, y + hh - vc],
        [x - hw, y - hh + vc],
    ]
    verts = np.array(pts)
    if mirror:
        verts = _mirror_points(verts, x)
    if rotation:
        verts = _rotate_points(verts, x, y, rotation)
    return Polygon(verts, closed=True, facecolor=color, edgecolor="none", alpha=alpha)


def _make_radhplate(x: float, y: float, params: dict, scale: float,
                    rotation: float, color: str, alpha: float,
                    mirror: bool = False):
    """Create a radiused inverted home plate (radhplate).
    Like inverted home plate but with curved left side.
    """
    w = params["width"] * scale
    h = params["height"] * scale
    ms = params["middle_size"] * scale
    hw, hh = w / 2, h / 2

    pts = []
    # Right side (flat)
    pts.append([x + hw, y - hh])
    pts.append([x + hw, y + hh])
    # Left side top
    pts.append([x - hw + ms, y + hh])
    # Curved left side
    n = 16
    # Approximate the curve from top-left to center-left to bottom-left
    for i in range(n + 1):
        t = i / n
        # Simple quadratic bezier approximation for the curved indent
        px = x - hw + ms * (1 - 4 * t * (1 - t))
        py = y + hh - t * 2 * hh
        pts.append([px, py])
    pts.append([x - hw + ms, y - hh])

    verts = np.array(pts)
    if mirror:
        verts[:, 0] = 2 * x - verts[:, 0]
    if rotation:
        verts = _rotate_points(verts, x, y, rotation)
    return Polygon(verts, closed=True, facecolor=color, edgecolor="none", alpha=alpha)


def _make_dshape(x: float, y: float, params: dict, scale: float,
                 rotation: float, color: str, alpha: float,
                 mirror: bool = False):
    """Create a D-shape (radiused home plate).
    Rectangle with one side replaced by a semicircular arc.
    """
    w = params["width"] * scale
    h = params["height"] * scale
    r = params["relief"] * scale
    hw, hh = w / 2, h / 2

    pts = []
    # Left side flat
    pts.append([x - hw, y - hh])
    # Bottom
    pts.append([x + hw - r, y - hh])
    # Right side: semicircular arc
    n = 24
    arc_cx = x + hw - r
    arc_r = min(r, hh)
    for i in range(n + 1):
        angle = -math.pi / 2 + i * math.pi / n
        pts.append([arc_cx + arc_r * math.cos(angle),
                    y + arc_r * math.sin(angle)])
    # Top
    pts.append([x - hw, y + hh])

    verts = np.array(pts)
    if mirror:
        verts[:, 0] = 2 * x - verts[:, 0]
    if rotation:
        verts = _rotate_points(verts, x, y, rotation)
    return Polygon(verts, closed=True, facecolor=color, edgecolor="none", alpha=alpha)


def _make_cross(x: float, y: float, params: dict, scale: float,
                rotation: float, color: str, alpha: float,
                mirror: bool = False):
    """Create a cross symbol.
    Two intersecting orthogonal line segments forming a plus/cross shape.
    """
    w = params["width"] * scale
    h = params["height"] * scale
    hs = params["horiz_line_width"] * scale  # horizontal bar height
    vs = params["vert_line_width"] * scale  # vertical bar width
    hw, hh = w / 2, h / 2

    # Cross shape vertices (12-point polygon)
    hvs = vs / 2
    hhs = hs / 2
    pts = [
        [x - hvs, y - hh],
        [x + hvs, y - hh],
        [x + hvs, y - hhs],
        [x + hw, y - hhs],
        [x + hw, y + hhs],
        [x + hvs, y + hhs],
        [x + hvs, y + hh],
        [x - hvs, y + hh],
        [x - hvs, y + hhs],
        [x - hw, y + hhs],
        [x - hw, y - hhs],
        [x - hvs, y - hhs],
    ]
    verts = np.array(pts)
    if mirror:
        verts = _mirror_points(verts, x)
    if rotation:
        verts = _rotate_points(verts, x, y, rotation)
    return Polygon(verts, closed=True, facecolor=color, edgecolor="none", alpha=alpha)


def _make_dogbone(x: float, y: float, params: dict, scale: float,
                  rotation: float, color: str, alpha: float,
                  mirror: bool = False):
    """Create a dogbone symbol.
    Similar to a cross but with only a horizontal bar through a vertical bar.
    """
    w = params["width"] * scale
    h = params["height"] * scale
    hs = params["horiz_line_width"] * scale
    vs = params["vert_line_width"] * scale
    hw, hh = w / 2, h / 2

    hvs = vs / 2
    hhs = hs / 2
    # Dogbone: T-shape or cross-like with asymmetric arms
    pts = [
        [x - hvs, y - hh],
        [x + hvs, y - hh],
        [x + hvs, y - hhs],
        [x + hw, y - hhs],
        [x + hw, y + hhs],
        [x + hvs, y + hhs],
        [x + hvs, y + hh],
        [x - hvs, y + hh],
        [x - hvs, y + hhs],
        [x - hw, y + hhs],
        [x - hw, y - hhs],
        [x - hvs, y - hhs],
    ]
    verts = np.array(pts)
    if mirror:
        verts = _mirror_points(verts, x)
    if rotation:
        verts = _rotate_points(verts, x, y, rotation)
    return Polygon(verts, closed=True, facecolor=color, edgecolor="none", alpha=alpha)


def _make_dpack(x: float, y: float, params: dict, scale: float,
                rotation: float, color: str, alpha: float,
                mirror: bool = False):
    """Create a D-Pack symbol.
    A grid of small rectangular pads arranged in rows and columns.
    """
    w = params["width"] * scale
    h = params["height"] * scale
    hg = params["horiz_gap"] * scale
    vg = params["vert_gap"] * scale
    hn = params["num_rows"]
    vn = params["num_cols"]
    cr = params.get("corner_radius", 0) * scale

    # Individual pad sizes
    pad_w = (w - hg * (hn - 1)) / hn if hn > 0 else w
    pad_h = (h - vg * (vn - 1)) / vn if vn > 0 else h

    if pad_w <= 0 or pad_h <= 0:
        return Circle((x, y), 0.001, facecolor=color, edgecolor="none", alpha=alpha * 0.5)

    all_verts = []
    all_codes = []

    hw, hh = w / 2, h / 2

    for row in range(hn):
        for col in range(vn):
            px = x - hw + row * (pad_w + hg) + pad_w / 2
            py = y - hh + col * (pad_h + vg) + pad_h / 2

            if cr > 0:
                rect_pts = _rounded_rect_points(px, py, pad_w, pad_h, cr)
            else:
                rect_pts = _rect_points(px, py, pad_w, pad_h)

            n_pts = len(rect_pts)
            all_verts.extend(rect_pts.tolist())
            all_verts.append(rect_pts[0].tolist())
            all_codes.extend([MplPath.MOVETO] + [MplPath.LINETO] * (n_pts - 1) +
                             [MplPath.CLOSEPOLY])

    if not all_verts:
        return Circle((x, y), 0.001, facecolor=color, edgecolor="none", alpha=alpha * 0.5)

    verts_arr = np.array(all_verts)
    if mirror:
        verts_arr = _mirror_points(verts_arr, x)
    if rotation:
        verts_arr = _rotate_points(verts_arr, x, y, rotation)

    path = MplPath(verts_arr, all_codes)
    return PathPatch(path, facecolor=color, alpha=alpha, edgecolor="none")


def _make_moire(x: float, y: float, params: dict, scale: float,
                rotation: float, color: str, alpha: float):
    """Create a moire symbol.
    Concentric rings with crosshair lines, used as alignment targets.
    """
    rw = params["ring_width"] * scale
    rg = params["ring_gap"] * scale
    nr = params["num_rings"]
    lw = params["line_width"] * scale
    ll = params["line_length"] * scale
    la = params["line_angle"]

    all_verts = []
    all_codes = []
    n = 64

    # Draw concentric rings
    current_r = rw  # Start from center: first ring outer radius
    for i in range(nr):
        outer_r = current_r
        inner_r = current_r - rw
        if inner_r < 0:
            inner_r = 0

        if inner_r > 0:
            outer_pts = _circle_points(x, y, outer_r, n)
            inner_pts = _circle_points(x, y, inner_r, n)[::-1]

            all_verts.extend(outer_pts.tolist())
            all_verts.append(outer_pts[0].tolist())
            all_codes.extend([MplPath.MOVETO] + [MplPath.LINETO] * (n - 1) +
                             [MplPath.CLOSEPOLY])

            all_verts.extend(inner_pts.tolist())
            all_verts.append(inner_pts[0].tolist())
            all_codes.extend([MplPath.MOVETO] + [MplPath.LINETO] * (n - 1) +
                             [MplPath.CLOSEPOLY])
        else:
            # Filled circle for innermost ring
            pts = _circle_points(x, y, outer_r, n)
            all_verts.extend(pts.tolist())
            all_verts.append(pts[0].tolist())
            all_codes.extend([MplPath.MOVETO] + [MplPath.LINETO] * (n - 1) +
                             [MplPath.CLOSEPOLY])

        current_r += rg + rw

    # Draw crosshair lines
    hlw = lw / 2
    hll = ll / 2
    total_rot = rotation + la

    for line_angle in [0, 90]:
        a = math.radians(total_rot + line_angle)
        cos_a = math.cos(a)
        sin_a = math.sin(a)
        # Line as thin rectangle
        perp_cos = math.cos(a + math.pi / 2)
        perp_sin = math.sin(a + math.pi / 2)

        line_pts = [
            [x + hll * cos_a + hlw * perp_cos, y + hll * sin_a + hlw * perp_sin],
            [x + hll * cos_a - hlw * perp_cos, y + hll * sin_a - hlw * perp_sin],
            [x - hll * cos_a - hlw * perp_cos, y - hll * sin_a - hlw * perp_sin],
            [x - hll * cos_a + hlw * perp_cos, y - hll * sin_a + hlw * perp_sin],
        ]
        all_verts.extend(line_pts)
        all_verts.append(line_pts[0])
        all_codes.extend([MplPath.MOVETO, MplPath.LINETO, MplPath.LINETO,
                          MplPath.LINETO, MplPath.CLOSEPOLY])

    if not all_verts:
        return Circle((x, y), 0.001, facecolor=color, edgecolor="none", alpha=alpha * 0.5)

    path = MplPath(np.array(all_verts), all_codes)
    return PathPatch(path, facecolor=color, alpha=alpha, edgecolor="none")
