"""Layer feature rendering - converts parsed features to matplotlib graphics."""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
from matplotlib.axes import Axes
from matplotlib.collections import LineCollection, PatchCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Polygon, Rectangle

from src.models import (
    ArcRecord, BarcodeRecord, LayerFeatures, LineRecord, PadRecord,
    StrokeFont, SurfaceRecord, SymbolRef, TextRecord, UserSymbol,
)
from src.visualizer.symbol_renderer import (
    contour_to_vertices, get_line_width_for_symbol, symbol_to_patch,
    user_symbol_to_patches,
)


# Default layer colors by type
LAYER_COLORS = {
    "SIGNAL": "#CC0000",
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

        if isinstance(feature, PadRecord):
            _draw_pad(ax, feature, sym_lookup, features.units,
                      user_symbols, color, alpha)
        elif isinstance(feature, LineRecord):
            _draw_line(ax, feature, sym_lookup, features.units, color, alpha)
        elif isinstance(feature, ArcRecord):
            _draw_arc(ax, feature, sym_lookup, features.units, color, alpha)
        elif isinstance(feature, TextRecord):
            _draw_text(ax, feature, font, color, alpha)
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
    """Draw a line feature with proper width from its symbol."""
    sym_ref = sym_lookup.get(line.symbol_idx)
    width = 0.001  # Default thin line
    if sym_ref:
        width = get_line_width_for_symbol(sym_ref.name, units, sym_ref.unit_override)

    ax.plot(
        [line.xs, line.xe], [line.ys, line.ye],
        color=color, alpha=alpha,
        linewidth=max(0.1, width * _get_points_per_unit(ax, units)),
        solid_capstyle="round",
    )


def _draw_arc(ax: Axes, arc: ArcRecord, sym_lookup: dict[int, SymbolRef],
              units: str, color: str = "blue", alpha: float = 0.7):
    """Draw an arc feature."""
    sym_ref = sym_lookup.get(arc.symbol_idx)
    width = 0.001
    if sym_ref:
        width = get_line_width_for_symbol(sym_ref.name, units, sym_ref.unit_override)

    # Convert arc to polyline
    from src.visualizer.symbol_renderer import _arc_to_points
    points = _arc_to_points(
        arc.xs, arc.ys, arc.xe, arc.ye,
        arc.xc, arc.yc, arc.clockwise, 32,
    )

    if len(points) >= 2:
        xs, ys = zip(*points)
        ax.plot(
            xs, ys,
            color=color, alpha=alpha,
            linewidth=max(0.1, width * _get_points_per_unit(ax, units)),
            solid_capstyle="round",
        )


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


def _draw_surface(ax: Axes, surface: SurfaceRecord,
                  color: str = "blue", alpha: float = 0.7):
    """Draw a surface (filled polygon with potential holes)."""
    for contour in surface.contours:
        verts = contour_to_vertices(contour)
        if len(verts) >= 3:
            if contour.is_island:
                patch = Polygon(verts, closed=True, color=color, alpha=alpha,
                                edgecolor="none")
            else:
                # Holes: draw with background color
                patch = Polygon(verts, closed=True, color="white", alpha=1.0,
                                edgecolor="none")
            ax.add_patch(patch)


def _get_points_per_unit(ax: Axes, units: str) -> float:
    """Estimate the scale factor from data units to display points.

    Used for line width scaling. Returns approximate points per unit.
    """
    try:
        xlim = ax.get_xlim()
        fig = ax.get_figure()
        bbox = ax.get_window_extent(renderer=fig.canvas.get_renderer())
        data_width = xlim[1] - xlim[0]
        if data_width > 0:
            return bbox.width / data_width
    except Exception:
        pass
    # Default fallback
    return 72.0 * (1.0 if units == "INCH" else 1.0 / 25.4)
