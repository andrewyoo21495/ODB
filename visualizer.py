"""
PCB Visualizer
Renders ODB++ layer data using Matplotlib.
Supports per-layer rendering and full board (all layers) rendering.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple, List, TYPE_CHECKING

if TYPE_CHECKING:
    import matplotlib.axes


from models import ODBModel, LayerData, Layer, Surface, Pad, Line, Arc, TextFeature
from parsers.symbol_resolver import SymbolResolver


# ---------------------------------------------------------------------------
# Default layer color scheme
# ---------------------------------------------------------------------------

_LAYER_COLORS = {
    'SIGNAL':       {'TOP': '#CC0000', 'BOTTOM': '#0000CC', 'INNER': '#CC6600'},
    'POWER':        {'TOP': '#FF6600', 'BOTTOM': '#FF6600', 'INNER': '#FF6600'},
    'SOLDER_MASK':  {'TOP': '#00CC44', 'BOTTOM': '#009933', 'INNER': '#009933'},
    'SILK_SCREEN':  {'TOP': '#FFFFFF', 'BOTTOM': '#FFFF00', 'INNER': '#FFFF00'},
    'DRILL':        '#888888',
    'COMPONENT':    {'TOP': '#FF88FF', 'BOTTOM': '#88FFFF', 'INNER': '#AAAAAA'},
    'DOCUMENT':     '#AAAAAA',
    'ROUT':         '#999900',
}

_DEFAULT_COLOR = '#AAAAAA'
_BG_COLOR = '#1a1a1a'


def _get_layer_color(layer: Layer) -> str:
    entry = _LAYER_COLORS.get(layer.layer_type)
    if entry is None:
        return _DEFAULT_COLOR
    if isinstance(entry, str):
        return entry
    return entry.get(layer.side, _DEFAULT_COLOR)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _diamond_points(cx, cy, w, h):
    """Return vertices for a diamond (rhombus) centered at (cx, cy)."""
    hw, hh = w / 2, h / 2
    return [(cx, cy + hh), (cx + hw, cy), (cx, cy - hh), (cx - hw, cy)]


def _octagon_points(cx, cy, w, h, cut_x, cut_y):
    """Return vertices for a chamfered-corner octagon."""
    hw, hh = w / 2, h / 2
    cx_off, cy_off = cut_x / 2, cut_y / 2
    return [
        (cx - hw + cx_off, cy + hh),
        (cx + hw - cx_off, cy + hh),
        (cx + hw, cy + hh - cy_off),
        (cx + hw, cy - hh + cy_off),
        (cx + hw - cx_off, cy - hh),
        (cx - hw + cx_off, cy - hh),
        (cx - hw, cy - hh + cy_off),
        (cx - hw, cy + hh - cy_off),
    ]


# ---------------------------------------------------------------------------
# Main visualizer class
# ---------------------------------------------------------------------------

class PCBVisualizer:
    """
    Renders ODB++ layer data.

    Usage:
        viz = PCBVisualizer(model)
        viz.render_layer('comp_top')
        viz.render_all_layers(output_path='board.png')
    """

    def __init__(self, model: ODBModel):
        self.model = model
        self._sym_resolver = SymbolResolver()

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def render_layer(
        self,
        layer_name: str,
        ax: Optional['matplotlib.axes.Axes'] = None,
        show_components: bool = True,
        title: Optional[str] = None,
    ) -> 'matplotlib.axes.Axes':
        """
        Render a single layer onto a Matplotlib axes.

        Args:
            layer_name: Name of the layer to render.
            ax: Existing axes to draw on; created if None.
            show_components: Whether to annotate component reference designators.
            title: Axes title; defaults to '<layer_name> (<type>)'.

        Returns:
            The Matplotlib axes object.
        """
        import matplotlib.pyplot as plt

        if ax is None:
            _fig, ax = plt.subplots(figsize=(16, 12))

        ax.set_aspect('equal')
        ax.set_facecolor(_BG_COLOR)

        ld = self.model.layer_data.get(layer_name)
        if ld is None:
            ax.set_title(f"{layer_name} (not found)")
            return ax

        color = _get_layer_color(ld.layer)
        neg_color = _BG_COLOR  # Negative polarity features erase underlying features

        # Draw order: surfaces → lines → arcs → pads → text → components
        self._draw_surfaces(ax, ld, color, neg_color)
        self._draw_lines(ax, ld, color, neg_color)
        self._draw_arcs(ax, ld, color, neg_color)
        self._draw_pads(ax, ld, color, neg_color)
        self._draw_texts(ax, ld, color)

        if show_components and ld.components:
            self._draw_components(ax, ld)

        layer_title = title or f"{layer_name} ({ld.layer.layer_type})"
        ax.set_title(layer_title, color='white', fontsize=10)
        ax.tick_params(colors='#888888')
        for spine in ax.spines.values():
            spine.set_edgecolor('#444444')

        return ax

    def render_all_layers(
        self,
        output_path: Optional[str] = None,
        cols: int = 4,
    ) -> None:
        """
        Render all layers in a grid layout.

        Args:
            output_path: If given, save the figure to this path instead of showing.
            cols: Number of columns in the grid.
        """
        import matplotlib.pyplot as plt

        layer_names = [l.name for l in self.model.layers
                       if l.name in self.model.layer_data]
        if not layer_names:
            print("No layer data to render.")
            return

        n = len(layer_names)
        cols = min(cols, n)
        rows = (n + cols - 1) // cols

        fig, axes = plt.subplots(rows, cols, figsize=(cols * 6, rows * 5))
        fig.patch.set_facecolor('#0d0d0d')

        # Flatten axes array for easy indexing
        ax_flat = []
        if rows == 1 and cols == 1:
            ax_flat = [axes]
        elif rows == 1 or cols == 1:
            ax_flat = list(axes)
        else:
            for row in axes:
                ax_flat.extend(row)

        for i, layer_name in enumerate(layer_names):
            self.render_layer(layer_name, ax=ax_flat[i], show_components=True)

        # Hide unused subplots
        for j in range(n, len(ax_flat)):
            ax_flat[j].set_visible(False)

        fig.tight_layout()

        if output_path:
            plt.savefig(output_path, dpi=150, bbox_inches='tight',
                        facecolor=fig.get_facecolor())
            print(f"Saved to {output_path}")
        else:
            plt.show()

    # ------------------------------------------------------------------
    # Internal drawing methods
    # ------------------------------------------------------------------

    def _draw_surfaces(self, ax, ld: LayerData, color: str, neg_color: str) -> None:
        from matplotlib.patches import PathPatch
        from matplotlib.path import Path

        for surf in ld.surfaces:
            fill_color = color if surf.polarity == 'P' else neg_color
            if not surf.islands:
                continue

            verts = []
            codes = []
            for island in surf.islands:
                if len(island) < 2:
                    continue
                verts.extend(island)
                verts.append(island[0])  # Close polygon
                codes.append(Path.MOVETO)
                codes.extend([Path.LINETO] * (len(island) - 1))
                codes.append(Path.CLOSEPOLY)

            if verts:
                path = Path(verts, codes)
                patch = PathPatch(path, facecolor=fill_color,
                                  edgecolor='none', alpha=0.85)
                ax.add_patch(patch)

    def _draw_lines(self, ax, ld: LayerData, color: str, neg_color: str) -> None:
        for ln in ld.lines:
            line_color = color if ln.polarity == 'P' else neg_color
            sym = self._sym_resolver.resolve(ln.symbol_name)
            lw = SymbolResolver.get_line_width(sym)
            # Scale line width to points (approximate)
            lw_pts = max(0.5, lw * 72)
            ax.plot([ln.x1, ln.x2], [ln.y1, ln.y2],
                    color=line_color, linewidth=lw_pts,
                    solid_capstyle='round', solid_joinstyle='round')

    def _draw_arcs(self, ax, ld: LayerData, color: str, neg_color: str) -> None:
        import numpy as np
        from matplotlib.patches import PathPatch
        from matplotlib.path import Path

        for arc in ld.arcs:
            arc_color = color if arc.polarity == 'P' else neg_color
            sym = self._sym_resolver.resolve(arc.symbol_name)
            lw_pts = max(0.5, SymbolResolver.get_line_width(sym) * 72)

            # Draw arc as a series of line segments
            points = self._arc_to_polyline(arc)
            if len(points) >= 2:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                ax.plot(xs, ys, color=arc_color, linewidth=lw_pts,
                        solid_capstyle='round')

    def _draw_pads(self, ax, ld: LayerData, color: str, neg_color: str) -> None:
        for pad in ld.pads:
            pad_color = color if pad.polarity == 'P' else neg_color
            sym = self._sym_resolver.resolve(pad.symbol_name)
            patch = self._make_pad_patch(sym, pad.x, pad.y, pad.rotation,
                                          pad.mirror, pad_color, ax)
            if patch is not None:
                ax.add_patch(patch)

    def _draw_texts(self, ax, ld: LayerData, color: str) -> None:
        for txt in ld.texts:
            txt_color = color if txt.polarity == 'P' else _BG_COLOR
            ax.text(txt.x, txt.y, txt.text,
                    color=txt_color, fontsize=4,
                    rotation=txt.rotation, ha='left', va='bottom')

    def _draw_components(self, ax, ld: LayerData) -> None:
        for comp in ld.components:
            ax.text(comp.x, comp.y, comp.refdes,
                    color='white', fontsize=5, ha='center', va='center',
                    fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.1', fc='black', alpha=0.4,
                              ec='none'))

    # ------------------------------------------------------------------
    # Patch factory
    # ------------------------------------------------------------------

    def _make_pad_patch(self, sym_info, x, y, rotation, mirror, color, ax):
        """Create a Matplotlib Patch for a pad symbol."""
        from matplotlib.patches import Circle, Rectangle, Ellipse, Polygon
        from matplotlib.transforms import Affine2D
        import numpy as np

        t = Affine2D().rotate_deg(rotation)
        if mirror:
            t = t.scale(-1, 1)
        t = t.translate(x, y) + ax.transData

        stype = sym_info.get('type', 'unknown')

        if stype == 'circle':
            d = sym_info.get('diameter', 0.01)
            patch = Circle((x, y), d / 2, color=color)
            patch.set_transform(ax.transData)
            return patch

        elif stype == 'rect':
            w, h = sym_info.get('w', 0.01), sym_info.get('h', 0.01)
            patch = Rectangle((-w / 2, -h / 2), w, h, color=color)
            patch.set_transform(t)
            return patch

        elif stype == 'oval':
            w, h = sym_info.get('w', 0.01), sym_info.get('h', 0.01)
            patch = Ellipse((0, 0), w, h, color=color)
            patch.set_transform(t)
            return patch

        elif stype == 'diamond':
            w, h = sym_info.get('w', 0.01), sym_info.get('h', 0.01)
            pts = _diamond_points(0, 0, w, h)
            patch = Polygon(pts, closed=True, color=color)
            patch.set_transform(t)
            return patch

        elif stype == 'octagon':
            w = sym_info.get('w', 0.01)
            h = sym_info.get('h', w)
            cx = sym_info.get('cx', w * 0.3)
            cy = sym_info.get('cy', h * 0.3)
            pts = _octagon_points(0, 0, w, h, cx, cy)
            patch = Polygon(pts, closed=True, color=color)
            patch.set_transform(t)
            return patch

        elif stype == 'donut_round':
            # Approximate: draw outer circle (inner hole not handled here)
            od = sym_info.get('od', 0.02)
            patch = Circle((x, y), od / 2, color=color, fill=False,
                           linewidth=max(0.5, (od - sym_info.get('id', 0)) / 2 * 72))
            patch.set_transform(ax.transData)
            return patch

        elif stype == 'rndrect':
            # Approximate with rectangle; proper rounded rect needs FancyBboxPatch
            from matplotlib.patches import FancyBboxPatch
            w, h = sym_info.get('w', 0.01), sym_info.get('h', 0.01)
            r = min(sym_info.get('r', 0), w / 2, h / 2)
            patch = FancyBboxPatch(
                (-w / 2, -h / 2), w, h,
                boxstyle=f'round,pad={r}',
                color=color,
            )
            patch.set_transform(t)
            return patch

        else:
            # Fallback: small circle
            patch = Circle((x, y), 0.005, color=color)
            patch.set_transform(ax.transData)
            return patch

    # ------------------------------------------------------------------
    # Arc to polyline approximation
    # ------------------------------------------------------------------

    @staticmethod
    def _arc_to_polyline(arc: Arc, segments: int = 32) -> List[Tuple[float, float]]:
        """Approximate an ODB++ arc as a list of (x, y) points."""
        import math

        xc, yc = arc.xc, arc.yc
        r_start = math.hypot(arc.xs - xc, arc.ys - yc)
        r_end = math.hypot(arc.xe - xc, arc.ye - yc)
        r = (r_start + r_end) / 2
        if r < 1e-12:
            return [(arc.xs, arc.ys), (arc.xe, arc.ye)]

        angle_start = math.atan2(arc.ys - yc, arc.xs - xc)
        angle_end = math.atan2(arc.ye - yc, arc.xe - xc)

        if arc.clockwise:
            if angle_end > angle_start:
                angle_end -= 2 * math.pi
        else:
            if angle_end < angle_start:
                angle_end += 2 * math.pi

        angles = [
            angle_start + (angle_end - angle_start) * i / segments
            for i in range(segments + 1)
        ]
        return [(xc + r * math.cos(a), yc + r * math.sin(a)) for a in angles]
