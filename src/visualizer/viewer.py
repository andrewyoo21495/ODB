"""Interactive matplotlib viewer with layer toggling."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
from matplotlib.widgets import CheckButtons

from src.models import (
    Component, EdaData, LayerFeatures, MatrixLayer, Profile,
    StrokeFont, UserSymbol,
)
from src.visualizer.layer_renderer import LAYER_COLORS, render_layer
from src.visualizer.component_overlay import draw_components
from src.visualizer.renderer import _draw_profile
from src.visualizer.symbol_renderer import contour_to_vertices

# Sentinel keys for component overlays in the checkbox list
COMP_TOP_KEY = "__components_top__"
COMP_BOT_KEY = "__components_bot__"


class PcbViewer:
    """Interactive PCB viewer with layer toggle controls."""

    def __init__(self,
                 profile: Profile,
                 layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
                 components_top: list[Component] = None,
                 components_bot: list[Component] = None,
                 eda_data: EdaData = None,
                 user_symbols: dict[str, UserSymbol] = None,
                 font: StrokeFont = None):
        self.profile = profile
        self.layers_data = layers_data
        self.components_top = components_top or []
        self.components_bot = components_bot or []
        self.eda_data = eda_data
        self.user_symbols = user_symbols or {}
        self.font = font

    def show(self, initial_visible: list[str] = None,
             figsize: tuple[float, float] = (16, 10)):
        """Launch the interactive viewer.

        Args:
            initial_visible: Layer names (and/or COMP_TOP_KEY / COMP_BOT_KEY)
                             to show initially.  None or [] = PCB outline only.
            figsize: Figure dimensions in inches.
        """
        if initial_visible is None:
            initial_visible = []

        self.fig, self.ax = plt.subplots(1, 1, figsize=figsize)
        self.ax.set_aspect("equal")
        self.ax.set_title("ODB++ PCB Viewer (toggle layers with checkboxes)")

        # Draw board outline (always visible)
        if self.profile and self.profile.surface:
            _draw_profile(self.ax, self.profile)

        # Get all available layer names sorted by row
        all_layers = sorted(
            self.layers_data.keys(),
            key=lambda n: self.layers_data[n][1].row,
        )

        # Render initially visible layers
        for layer_name in all_layers:
            if layer_name not in initial_visible:
                continue
            features, matrix_layer = self.layers_data[layer_name]
            color = LAYER_COLORS.get(matrix_layer.type, "#CC0000")
            render_layer(
                self.ax, features,
                color=color, layer_type=matrix_layer.type,
                alpha=0.7, user_symbols=self.user_symbols,
                font=self.font,
            )

        # Component overlays (only if in initial_visible)
        packages = self.eda_data.packages if self.eda_data else None
        if self.components_top and COMP_TOP_KEY in initial_visible:
            draw_components(self.ax, self.components_top, packages,
                            color="#87CEEB", alpha=0.4)
        if self.components_bot and COMP_BOT_KEY in initial_visible:
            draw_components(self.ax, self.components_bot, packages,
                            color="#FFB6C1", alpha=0.4)

        # Add layer toggle checkboxes
        self._setup_checkboxes(all_layers, initial_visible)

        # Add coordinate display on mouse movement
        self.ax.format_coord = self._format_coord

        units = self.profile.units if self.profile else "INCH"
        unit_label = "inches" if units == "INCH" else "mm"
        self.ax.set_xlabel(f"X ({unit_label})")
        self.ax.set_ylabel(f"Y ({unit_label})")
        self.ax.grid(True, alpha=0.2)

        plt.show()

    def _setup_checkboxes(self, all_layers: list[str], visible_items: list[str]):
        """Create layer toggle checkboxes including component overlays."""
        # Filter out dielectric and drill layers (not useful to visualize)
        display_layers = [
            name for name in all_layers
            if self.layers_data[name][1].type not in ("DIELECTRIC", "DRILL")
        ]

        # Build the full display items list: layers + component entries
        self._display_items: list[str] = list(display_layers)
        labels: list[str] = []
        actives: list[bool] = []

        for name in display_layers:
            matrix_layer = self.layers_data[name][1]
            labels.append(f"{name[:22]} ({matrix_layer.type[:4]})")
            actives.append(name in visible_items)

        # Add component overlay entries
        if self.components_top:
            self._display_items.append(COMP_TOP_KEY)
            labels.append(f"Components Top ({len(self.components_top)})")
            actives.append(COMP_TOP_KEY in visible_items)

        if self.components_bot:
            self._display_items.append(COMP_BOT_KEY)
            labels.append(f"Components Bot ({len(self.components_bot)})")
            actives.append(COMP_BOT_KEY in visible_items)

        if not self._display_items:
            return

        # Calculate checkbox panel dimensions
        n_items = len(self._display_items)
        item_height = 0.04
        total_needed = n_items * item_height
        max_panel_height = 0.92
        checkbox_height = min(max_panel_height, total_needed)
        checkbox_width = 0.22

        # Position the checkbox panel on the right side
        rax = self.fig.add_axes([0.78, 0.5 - checkbox_height / 2,
                                  checkbox_width, checkbox_height])

        self._check = CheckButtons(rax, labels, actives)

        # Larger font for labels
        for text in self._check.labels:
            text.set_fontsize(10)

        # Enable scrolling if the list overflows the panel
        self._scroll_enabled = total_needed > max_panel_height
        if self._scroll_enabled:
            visible_frac = checkbox_height / total_needed
            self._scroll_visible_frac = visible_frac
            self._scroll_pos = 1.0 - visible_frac  # start showing top items
            self._scroll_axes = rax
            rax.set_ylim(self._scroll_pos, self._scroll_pos + visible_frac)
            self.fig.canvas.mpl_connect('scroll_event', self._on_scroll)

        self._visible_set = set(
            item for item in visible_items if item in self._display_items
        )
        self._check.on_clicked(self._on_checkbox_click)

        # Adjust main axes to make room for the wider checkbox panel
        self.ax.set_position([0.05, 0.05, 0.70, 0.9])

    def _on_scroll(self, event):
        """Scroll the layer checkbox list when it overflows."""
        if not self._scroll_enabled:
            return
        if event.inaxes != self._scroll_axes:
            return

        step = 1.0 / len(self._display_items)
        if event.button == 'up':
            self._scroll_pos = min(1.0 - self._scroll_visible_frac,
                                   self._scroll_pos + step)
        elif event.button == 'down':
            self._scroll_pos = max(0.0, self._scroll_pos - step)

        self._scroll_axes.set_ylim(self._scroll_pos,
                                   self._scroll_pos + self._scroll_visible_frac)
        self.fig.canvas.draw_idle()

    def _on_checkbox_click(self, label: str):
        """Handle checkbox toggle - full redraw approach."""
        idx = None
        for i, text in enumerate(self._check.labels):
            if text.get_text() == label:
                idx = i
                break

        if idx is not None:
            item = self._display_items[idx]
            if item in self._visible_set:
                self._visible_set.remove(item)
            else:
                self._visible_set.add(item)

        self._redraw()

    def _redraw(self):
        """Clear and redraw all visible layers."""
        self.ax.clear()

        # Board outline is always drawn
        if self.profile and self.profile.surface:
            _draw_profile(self.ax, self.profile)

        # Render checked feature layers
        for layer_name in self._visible_set:
            if layer_name not in self.layers_data:
                continue
            features, matrix_layer = self.layers_data[layer_name]
            color = LAYER_COLORS.get(matrix_layer.type, "#CC0000")
            render_layer(
                self.ax, features,
                color=color, layer_type=matrix_layer.type,
                alpha=0.7, user_symbols=self.user_symbols,
                font=self.font,
            )

        # Component overlays (only when their checkbox is checked)
        packages = self.eda_data.packages if self.eda_data else None
        if COMP_TOP_KEY in self._visible_set and self.components_top:
            draw_components(self.ax, self.components_top, packages,
                            color="#87CEEB", alpha=0.4)
        if COMP_BOT_KEY in self._visible_set and self.components_bot:
            draw_components(self.ax, self.components_bot, packages,
                            color="#FFB6C1", alpha=0.4)

        units = self.profile.units if self.profile else "INCH"
        unit_label = "inches" if units == "INCH" else "mm"
        self.ax.set_xlabel(f"X ({unit_label})")
        self.ax.set_ylabel(f"Y ({unit_label})")
        self.ax.grid(True, alpha=0.2)
        self.ax.set_aspect("equal")
        self.ax.format_coord = self._format_coord

        self.fig.canvas.draw_idle()

    def _format_coord(self, x: float, y: float) -> str:
        """Format coordinate display string."""
        units = self.profile.units if self.profile else "INCH"
        if units == "INCH":
            return f"x={x:.6f}\" y={y:.6f}\""
        else:
            return f"x={x:.4f}mm y={y:.4f}mm"
