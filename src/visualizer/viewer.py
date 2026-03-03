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

        # Track rendered layer artists for toggling
        self._layer_artists: dict[str, list] = {}
        self._comp_artists: dict[str, list] = {}

    def show(self, initial_layers: list[str] = None,
             figsize: tuple[float, float] = (16, 10)):
        """Launch the interactive viewer."""
        self.fig, self.ax = plt.subplots(1, 1, figsize=figsize)
        self.ax.set_aspect("equal")
        self.ax.set_title("ODB++ PCB Viewer (toggle layers with checkboxes)")

        # Draw board outline
        if self.profile and self.profile.surface:
            _draw_profile(self.ax, self.profile)

        # Get all available layer names sorted by row
        all_layers = sorted(
            self.layers_data.keys(),
            key=lambda n: self.layers_data[n][1].row,
        )

        # Determine initial visibility
        if initial_layers is None:
            # Default: show signal and component layers
            initial_layers = [
                name for name in all_layers
                if self.layers_data[name][1].type in ("SIGNAL", "COMPONENT", "SOLDER_MASK")
            ]

        # Render all layers (hidden ones with alpha=0)
        for layer_name in all_layers:
            features, matrix_layer = self.layers_data[layer_name]
            visible = layer_name in initial_layers
            color = LAYER_COLORS.get(matrix_layer.type, "#CC0000")

            # Store current artists count
            n_before = len(self.ax.patches) + len(self.ax.lines)

            if visible:
                render_layer(
                    self.ax, features,
                    color=color, layer_type=matrix_layer.type,
                    alpha=0.7, user_symbols=self.user_symbols,
                    font=self.font,
                )

            n_after = len(self.ax.patches) + len(self.ax.lines)
            # Note: tracking individual artists per layer is complex with matplotlib.
            # For simplicity, we'll use a redraw approach.

        # Component overlay
        packages = self.eda_data.packages if self.eda_data else None
        if self.components_top:
            draw_components(self.ax, self.components_top, packages,
                            color="#00CCCC", alpha=0.4)
        if self.components_bot:
            draw_components(self.ax, self.components_bot, packages,
                            color="#CCCC00", alpha=0.4)

        # Add layer toggle checkboxes
        self._setup_checkboxes(all_layers, initial_layers)

        # Add coordinate display on mouse movement
        self.ax.format_coord = self._format_coord

        units = self.profile.units if self.profile else "INCH"
        unit_label = "inches" if units == "INCH" else "mm"
        self.ax.set_xlabel(f"X ({unit_label})")
        self.ax.set_ylabel(f"Y ({unit_label})")
        self.ax.grid(True, alpha=0.2)

        plt.show()

    def _setup_checkboxes(self, all_layers: list[str], visible_layers: list[str]):
        """Create layer toggle checkboxes."""
        if not all_layers:
            return

        # Filter to keep only non-dielectric, non-document layers for the checkbox panel
        display_layers = [
            name for name in all_layers
            if self.layers_data[name][1].type not in ("DIELECTRIC",)
        ]

        if not display_layers:
            return

        # Calculate checkbox panel size
        n_layers = len(display_layers)
        checkbox_height = min(0.8, n_layers * 0.025)
        checkbox_width = 0.15

        # Position the checkbox panel on the right side
        rax = self.fig.add_axes([0.85, 0.5 - checkbox_height / 2,
                                  checkbox_width, checkbox_height])

        labels = []
        actives = []
        for name in display_layers:
            matrix_layer = self.layers_data[name][1]
            short_name = name[:20]
            labels.append(f"{short_name} ({matrix_layer.type[:4]})")
            actives.append(name in visible_layers)

        self._check = CheckButtons(rax, labels, actives)
        # Adjust font size for checkbox labels
        for text in self._check.labels:
            text.set_fontsize(6)

        self._display_layers = display_layers
        self._visible_set = set(visible_layers)
        self._check.on_clicked(self._on_checkbox_click)

        # Adjust main axes to make room for checkboxes
        self.ax.set_position([0.05, 0.05, 0.75, 0.9])

    def _on_checkbox_click(self, label: str):
        """Handle checkbox toggle - full redraw approach."""
        # Find the layer name from the label
        idx = None
        for i, text in enumerate(self._check.labels):
            if text.get_text() == label:
                idx = i
                break

        if idx is not None:
            layer_name = self._display_layers[idx]
            if layer_name in self._visible_set:
                self._visible_set.remove(layer_name)
            else:
                self._visible_set.add(layer_name)

        self._redraw()

    def _redraw(self):
        """Clear and redraw all visible layers."""
        self.ax.clear()

        if self.profile and self.profile.surface:
            _draw_profile(self.ax, self.profile)

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

        packages = self.eda_data.packages if self.eda_data else None
        if self.components_top:
            draw_components(self.ax, self.components_top, packages,
                            color="#00CCCC", alpha=0.4)
        if self.components_bot:
            draw_components(self.ax, self.components_bot, packages,
                            color="#CCCC00", alpha=0.4)

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
