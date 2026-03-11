"""Layer feature rendering - converts parsed features to matplotlib graphics."""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
from matplotlib.axes import Axes
from matplotlib.patches import Circle, PathPatch, Polygon, Rectangle
from matplotlib.path import Path as MplPath

from src.models import (
    ArcRecord, BarcodeRecord, FeaturePolarity, LayerFeatures, LineRecord,
    PadRecord, StrokeFont, SurfaceRecord, SymbolRef, TextRecord, UserSymbol,
)
from src.visualizer.symbol_renderer import (
    contour_to_vertices, get_line_width_for_symbol, symbol_to_patch,
    user_symbol_to_patches,
)


# Default layer colors by type
LAYER_COLORS = {
    "SIGNAL": "#008E5C",
    "POWER_GROUND": "#0000CC",
    "SOLDER_MASK": "#00AA00",
    "SOLDER_PASTE": "#888888",
    "SILK_SCREEN": "#FFFF00",
    "DRILL": "#FF00FF",
    "ROUT": "#FF8800",
    "COMPONENT": "#00CCCC",
    "DOCUMENT": "#666666",
    "MIXED": "#AA00AA",
    "MASK": "#008888",
    "DIELECTRIC": "#D2B48C",
    "CONDUCTIVE_PASTE": "#AA8800",
}


def render_layer(ax: Axes, features: LayerFeatures,
                 color: str = None, layer_type: str = "SIGNAL",
                 alpha: float = 0.7,
                 user_symbols: dict[str, UserSymbol] = None,
                 font: StrokeFont = None,
                 max_features: int = None):
    """Render all features of a layer onto a matplotlib axes.

    Args:
        ax: matplotlib Axes to draw on
        features: Parsed layer features
        color: Override color (if None, uses layer_type default)
        layer_type: Layer type for default color selection
        alpha: Opacity
        user_symbols: Dict of user-defined symbols for resolving references
        font: Stroke font for text rendering
        max_features: Limit number of features rendered (for performance)
    """
    if color is None:
        color = LAYER_COLORS.get(layer_type, "#CC0000")

    # Build symbol name lookup
    sym_lookup = {s.index: s for s in features.symbols}

    count = 0
    for feature in features.features:
        if max_features and count >= max_features:
            break

        # Determine effective colour/alpha: negative polarity features
        # erase underlying artwork by painting with the background colour.
        feat_polarity = getattr(feature, "polarity", FeaturePolarity.P)
        if feat_polarity == FeaturePolarity.N:
            eff_color = ax.get_facecolor()
            eff_alpha = 1.0
        else:
            eff_color = color
            eff_alpha = alpha

        if isinstance(feature, PadRecord):
            _draw_pad(ax, feature, sym_lookup, features.units,
                      user_symbols, eff_color, eff_alpha)
        elif isinstance(feature, LineRecord):
            _draw_line(ax, feature, sym_lookup, features.units,
                       eff_color, eff_alpha)
        elif isinstance(feature, ArcRecord):
            _draw_arc(ax, feature, sym_lookup, features.units,
                      eff_color, eff_alpha)
        elif isinstance(feature, TextRecord):
            _draw_text(ax, feature, font, eff_color, eff_alpha)
        elif isinstance(feature, BarcodeRecord):
            _draw_barcode(ax, feature, eff_color, eff_alpha)
        elif isinstance(feature, SurfaceRecord):
            _draw_surface(ax, feature, color, alpha)

        count += 1


def _draw_pad(ax: Axes, pad: PadRecord, sym_lookup: dict[int, SymbolRef],
              units: str, user_symbols: dict = None,
              color: str = "blue", alpha: float = 0.7):
    """Draw a pad feature."""
    sym_ref = sym_lookup.get(pad.symbol_idx)
    if not sym_ref:
        return

    # Check if it's a user-defined symbol
    if user_symbols and sym_ref.name in user_symbols:
        patches = user_symbol_to_patches(
            user_symbols[sym_ref.name],
            pad.x, pad.y, pad.rotation, pad.mirror,
            color, alpha,
        )
        for p in patches:
            ax.add_patch(p)
        return

    # Standard symbol
    patch = symbol_to_patch(
        sym_ref.name, pad.x, pad.y,
        pad.rotation, pad.mirror,
        units, sym_ref.unit_override,
        color, alpha, pad.resize_factor,
    )
    if patch:
        ax.add_patch(patch)


def _draw_line(ax: Axes, line: LineRecord, sym_lookup: dict[int, SymbolRef],
               units: str, color: str = "blue", alpha: float = 0.7):
    """Draw a line feature as a filled polygon with data-coordinate width.

    The line width comes from the referenced symbol (e.g., r10.827 → diameter
    10.827 mils → 0.010827 inches).  Rendering as a polygon ensures the trace
    width is correct regardless of zoom level.
    """
    sym_ref = sym_lookup.get(line.symbol_idx)
    width = 0.001  # Default thin line
    if sym_ref:
        width = get_line_width_for_symbol(sym_ref.name, units, sym_ref.unit_override)
    if width <= 0:
        width = 0.001

    dx = line.xe - line.xs
    dy = line.ye - line.ys
    length = math.sqrt(dx * dx + dy * dy)

    if length < 1e-10:
        # Zero-length line → draw as a dot (circle)
        ax.add_patch(Circle((line.xs, line.ys), width / 2,
                            color=color, alpha=alpha, edgecolor="none"))
        return

    # Perpendicular offset for half-width
    hw = width / 2
    nx = -dy / length * hw
    ny = dx / length * hw

    verts = [
        (line.xs + nx, line.ys + ny),
        (line.xe + nx, line.ye + ny),
        (line.xe - nx, line.ye - ny),
        (line.xs - nx, line.ys - ny),
    ]
    ax.add_patch(Polygon(verts, closed=True, color=color, alpha=alpha,
                         edgecolor="none"))


def _draw_arc(ax: Axes, arc: ArcRecord, sym_lookup: dict[int, SymbolRef],
              units: str, color: str = "blue", alpha: float = 0.7):
    """Draw an arc feature as a filled polygon with data-coordinate width."""
    sym_ref = sym_lookup.get(arc.symbol_idx)
    width = 0.001
    if sym_ref:
        width = get_line_width_for_symbol(sym_ref.name, units, sym_ref.unit_override)
    if width <= 0:
        width = 0.001

    from src.visualizer.symbol_renderer import _arc_to_points
    points = _arc_to_points(
        arc.xs, arc.ys, arc.xe, arc.ye,
        arc.xc, arc.yc, arc.clockwise, 32,
    )

    if len(points) < 2:
        return

    # Build a thick arc as a filled polygon by offsetting the polyline
    hw = width / 2
    pts = np.array(points)
    n = len(pts)

    # Compute normals at each point using adjacent segments
    outer = np.empty((n, 2))
    inner = np.empty((n, 2))
    for i in range(n):
        if i == 0:
            dx, dy = pts[1] - pts[0]
        elif i == n - 1:
            dx, dy = pts[-1] - pts[-2]
        else:
            dx, dy = pts[i + 1] - pts[i - 1]
        seg_len = math.sqrt(dx * dx + dy * dy)
        if seg_len < 1e-12:
            nx, ny = 0.0, 0.0
        else:
            nx, ny = -dy / seg_len * hw, dx / seg_len * hw
        outer[i] = pts[i, 0] + nx, pts[i, 1] + ny
        inner[i] = pts[i, 0] - nx, pts[i, 1] - ny

    verts = np.concatenate([outer, inner[::-1]])
    ax.add_patch(Polygon(verts, closed=True, color=color, alpha=alpha,
                         edgecolor="none"))


def _draw_text(ax: Axes, text: TextRecord, font: StrokeFont = None,
               color: str = "blue", alpha: float = 0.7):
    """Draw a text feature using stroke font or matplotlib text."""
    if font and text.font == "standard" and text.text:
        _draw_stroke_text(ax, text, font, color, alpha)
    elif text.text:
        ax.text(
            text.x, text.y, text.text,
            fontsize=max(2, text.ysize * 200),
            color=color, alpha=alpha,
            rotation=-text.rotation,
            ha="left", va="bottom",
        )


def _draw_stroke_text(ax: Axes, text: TextRecord, font: StrokeFont,
                      color: str, alpha: float):
    """Draw text using the ODB++ stroke font."""
    scale_x = text.xsize / font.xsize if font.xsize > 0 else 1.0
    scale_y = text.ysize / font.ysize if font.ysize > 0 else 1.0

    cursor_x = text.x
    angle_rad = math.radians(-text.rotation)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    for ch in text.text:
        font_char = font.characters.get(ch)
        if font_char is None:
            cursor_x += text.xsize
            continue

        for stroke in font_char.strokes:
            x1 = cursor_x + stroke.x1 * scale_x
            y1 = text.y + stroke.y1 * scale_y
            x2 = cursor_x + stroke.x2 * scale_x
            y2 = text.y + stroke.y2 * scale_y

            # Apply rotation if needed
            if text.rotation:
                dx1, dy1 = x1 - text.x, y1 - text.y
                dx2, dy2 = x2 - text.x, y2 - text.y
                x1 = text.x + dx1 * cos_a - dy1 * sin_a
                y1 = text.y + dx1 * sin_a + dy1 * cos_a
                x2 = text.x + dx2 * cos_a - dy2 * sin_a
                y2 = text.y + dx2 * sin_a + dy2 * cos_a

            ax.plot([x1, x2], [y1, y2], color=color, alpha=alpha,
                    linewidth=0.5, solid_capstyle="round")

        cursor_x += text.xsize


def _draw_barcode(ax: Axes, barcode: BarcodeRecord,
                  color: str = "blue", alpha: float = 0.7):
    """Draw a barcode feature as a rectangle with text label."""
    w = barcode.width if barcode.width > 0 else 0.1
    h = barcode.height if barcode.height > 0 else 0.05

    # Build rectangle corners, then apply rotation
    x0, y0 = barcode.x, barcode.y
    corners = np.array([
        [x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h],
    ])

    if barcode.rotation:
        angle_rad = math.radians(-barcode.rotation)
        cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
        rel = corners - [x0, y0]
        rotated = np.column_stack([
            rel[:, 0] * cos_a - rel[:, 1] * sin_a,
            rel[:, 0] * sin_a + rel[:, 1] * cos_a,
        ])
        corners = rotated + [x0, y0]

    patch = Polygon(corners, closed=True, facecolor=color, alpha=alpha * 0.3,
                    edgecolor=color, linewidth=0.8)
    ax.add_patch(patch)

    # Draw text label if present
    if barcode.text:
        cx = barcode.x + w / 2
        cy = barcode.y + h / 2
        ax.text(cx, cy, barcode.text,
                fontsize=max(2, h * 100), color=color, alpha=alpha,
                rotation=-barcode.rotation,
                ha="center", va="center")


def _draw_surface(ax: Axes, surface: SurfaceRecord,
                  color: str = "blue", alpha: float = 0.7):
    """Draw a surface (filled polygon with potential holes).

    ODB++ surfaces consist of islands (outer boundaries, clockwise) and
    holes (inner boundaries, counter-clockwise).  The spec orders contours
    so that an island precedes its holes, and holes precede any islands
    nested inside them.

    This function groups each island with the holes that immediately follow
    it and renders them as a single matplotlib compound Path, so holes are
    true cutouts rather than opaque overlays.

    Negative-polarity surfaces are drawn with the canvas background colour
    to erase previously rendered features.
    """
    is_negative = (surface.polarity == FeaturePolarity.N)

    # --- Group contours: each island with its subsequent holes -----------
    groups: list[tuple[np.ndarray, list[np.ndarray]]] = []
    for contour in surface.contours:
        verts = contour_to_vertices(contour)
        if len(verts) < 3:
            continue
        if contour.is_island:
            groups.append((verts, []))
        else:
            # Hole belongs to the most recent island
            if groups:
                groups[-1][1].append(verts)

    for island_verts, hole_list in groups:
        if is_negative:
            # Negative polarity: erase underlying (draw with bg colour)
            fill_color = ax.get_facecolor()
            fill_alpha = 1.0
        else:
            fill_color = color
            fill_alpha = alpha

        if not hole_list:
            # Simple island without holes – plain Polygon is sufficient
            ax.add_patch(Polygon(island_verts, closed=True,
                                 color=fill_color, alpha=fill_alpha,
                                 edgecolor="none"))
        else:
            # Build a compound Path: island boundary + hole boundaries
            all_verts = []
            all_codes = []

            # Island (ensure closed)
            n = len(island_verts)
            all_verts.extend(island_verts.tolist())
            all_verts.append(island_verts[0].tolist())
            all_codes.append(MplPath.MOVETO)
            all_codes.extend([MplPath.LINETO] * (n - 1))
            all_codes.append(MplPath.CLOSEPOLY)

            # Each hole (ensure closed)
            for hole_verts in hole_list:
                nh = len(hole_verts)
                all_verts.extend(hole_verts.tolist())
                all_verts.append(hole_verts[0].tolist())
                all_codes.append(MplPath.MOVETO)
                all_codes.extend([MplPath.LINETO] * (nh - 1))
                all_codes.append(MplPath.CLOSEPOLY)

            path = MplPath(all_verts, all_codes)
            patch = PathPatch(path, facecolor=fill_color, alpha=fill_alpha,
                              edgecolor="none")
            ax.add_patch(patch)


