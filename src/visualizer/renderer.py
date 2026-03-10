"""Main rendering orchestrator for PCB visualization."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from src.models import (
    Component, EdaData, LayerFeatures, MatrixLayer, Profile,
    StrokeFont, UserSymbol,
)
from src.visualizer.component_overlay import draw_components, draw_pin_markers
from src.visualizer.layer_renderer import LAYER_COLORS, render_layer
from src.visualizer.symbol_renderer import contour_to_vertices


def render_board(profile: Profile,
                 layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
                 components_top: list[Component] = None,
                 components_bot: list[Component] = None,
                 eda_data: EdaData = None,
                 user_symbols: dict[str, UserSymbol] = None,
                 font: StrokeFont = None,
                 visible_layers: list[str] = None,
                 figsize: tuple[float, float] = (14, 10),
                 title: str = "ODB++ PCB View") -> tuple[Figure, Axes]:
    """Render a PCB board with selected layers.

    Args:
        profile: Board outline profile
        layers_data: dict of layer_name -> (LayerFeatures, MatrixLayer)
        components_top: Top-side components
        components_bot: Bottom-side components
        eda_data: EDA data for package outlines
        user_symbols: User-defined symbols
        font: Stroke font for text rendering
        visible_layers: List of layer names to show (None = all)
        figsize: Figure size
        title: Plot title

    Returns:
        (Figure, Axes) tuple
    """
    fig, ax = plt.subplots(1, 1, figsize=figsize)
    ax.set_aspect("equal")
    ax.set_title(title)

    # Draw board outline
    if profile and profile.surface:
        _draw_profile(ax, profile)

    # Determine which layers to render
    if visible_layers is None:
        visible_layers = list(layers_data.keys())

    # Render layers in order (bottom to top for proper z-ordering)
    for layer_name in visible_layers:
        if layer_name not in layers_data:
            continue

        features, matrix_layer = layers_data[layer_name]
        color = LAYER_COLORS.get(matrix_layer.type, "#CC0000")

        render_layer(
            ax, features,
            color=color,
            layer_type=matrix_layer.type,
            alpha=0.7,
            user_symbols=user_symbols,
            font=font,
        )

    # Extract component-layer features for pad rendering fallback.
    comp_layer_top = next(
        (lf for name, (lf, _) in layers_data.items() if "comp_+_top" in name),
        None,
    )
    comp_layer_bot = next(
        (lf for name, (lf, _) in layers_data.items() if "comp_+_bot" in name),
        None,
    )

    # Build FID-based pin-to-feature lookup for accurate pad rendering.
    fid_resolved = {}
    if eda_data and eda_data.layer_names:
        from src.visualizer.fid_lookup import build_fid_map, resolve_fid_features
        fid_map = build_fid_map(eda_data)
        if fid_map:
            fid_resolved = resolve_fid_features(
                fid_map, eda_data.layer_names, layers_data,
            )

    # Draw component overlays
    packages = eda_data.packages if eda_data else None
    if components_top:
        draw_components(ax, components_top, packages, color="#00CCCC", alpha=0.4,
                        comp_layer_features=comp_layer_top,
                        user_symbols=user_symbols,
                        fid_resolved=fid_resolved, comp_side="T")
    if components_bot:
        draw_components(ax, components_bot, packages, color="#CCCC00", alpha=0.4,
                        comp_layer_features=comp_layer_bot,
                        user_symbols=user_symbols,
                        fid_resolved=fid_resolved, comp_side="B")

    # Set axis labels
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.grid(False)

    fig.tight_layout()
    return fig, ax


def render_single_layer(features: LayerFeatures,
                        matrix_layer: MatrixLayer,
                        profile: Profile = None,
                        user_symbols: dict[str, UserSymbol] = None,
                        font: StrokeFont = None,
                        figsize: tuple[float, float] = (14, 10)) -> tuple[Figure, Axes]:
    """Render a single layer in isolation."""
    fig, ax = plt.subplots(1, 1, figsize=figsize)
    ax.set_aspect("equal")
    ax.set_title(f"Layer: {matrix_layer.name} ({matrix_layer.type})")

    if profile and profile.surface:
        _draw_profile(ax, profile, fill=False, outline_color="#AAAAAA")

    color = LAYER_COLORS.get(matrix_layer.type, "#CC0000")
    render_layer(ax, features, color=color, layer_type=matrix_layer.type,
                 alpha=0.8, user_symbols=user_symbols, font=font)

    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.grid(False)

    fig.tight_layout()
    return fig, ax


def _draw_profile(ax: Axes, profile: Profile,
                  fill: bool = True, outline_color: str = "#FF0000"):
    """Draw the board outline from profile data."""
    if not profile.surface:
        return

    for contour in profile.surface.contours:
        verts = contour_to_vertices(contour)
        if len(verts) < 3:
            continue

        if fill and contour.is_island:
            from matplotlib.patches import Polygon
            patch = Polygon(verts, closed=True,
                            facecolor="#000000", edgecolor=outline_color,
                            linewidth=1.0, linestyle='-',
                            alpha=0.95, zorder=0)
            ax.add_patch(patch)
        else:
            ax.plot(verts[:, 0], verts[:, 1],
                    color=outline_color, linewidth=2.0,
                    linestyle='-', alpha=0.9)

        # Auto-fit axes to board outline
        if contour.is_island:
            margin_x = (verts[:, 0].max() - verts[:, 0].min()) * 0.05
            margin_y = (verts[:, 1].max() - verts[:, 1].min()) * 0.05
            ax.set_xlim(verts[:, 0].min() - margin_x, verts[:, 0].max() + margin_x)
            ax.set_ylim(verts[:, 1].min() - margin_y, verts[:, 1].max() + margin_y)


def export_image(fig: Figure, output_path: str | Path, dpi: int = 150):
    """Export the current figure to an image file."""
    fig.savefig(str(output_path), dpi=dpi, bbox_inches="tight")
    print(f"Exported: {output_path}")
