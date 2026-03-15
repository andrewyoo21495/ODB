"""Copper calculation utilities for batch processing and GUI.

Provides standalone functions for:
- Rasterizing a layer to pixel data
- Calculating copper ratios (whole-board and per-cell grid)
- Drawing sub-section overlays on matplotlib axes
- Saving layer images with overlay
"""

from __future__ import annotations

from typing import Optional
from pathlib import Path
import numpy as np

from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.path import Path as MplPath
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches

from src.models import LayerFeatures, MatrixLayer, Profile, StrokeFont, UserSymbol
from src.visualizer.layer_renderer import LAYER_COLORS, render_layer
from src.visualizer.renderer import _draw_profile
from src.visualizer.symbol_renderer import contour_to_vertices


def rasterize_layer(
    layer_name: str,
    profile: Profile,
    layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
    user_symbols: dict[str, UserSymbol],
    font: StrokeFont,
) -> Optional[dict]:
    """Render a layer off-screen and return pixel data.

    Returns a dict with keys:
        rgb       – np.ndarray (H, W, 3) uint8 rendered image
        pcb_mask  – np.ndarray (H, W) bool, True inside PCB outline
        xmin, xmax, ymin, ymax  – bounding box in data coords (mm)
        img_w, img_h            – image dimensions in pixels

    Returns None if the profile or layer is unavailable.
    """
    if not profile or not profile.surface:
        return None
    if layer_name not in layers_data:
        return None

    # Find the PCB outline (island contour)
    outline_verts = None
    for contour in profile.surface.contours:
        verts = contour_to_vertices(contour)
        if contour.is_island and len(verts) >= 3:
            outline_verts = verts
            break
    if outline_verts is None:
        return None

    # Compute tight PCB bounding box
    xmin = float(outline_verts[:, 0].min())
    xmax = float(outline_verts[:, 0].max())
    ymin = float(outline_verts[:, 1].min())
    ymax = float(outline_verts[:, 1].max())
    board_w = xmax - xmin
    board_h = ymax - ymin
    if board_w <= 0 or board_h <= 0:
        return None

    # Build a fixed-resolution off-screen figure
    _DPI = 200
    _LONG = 10.0
    if board_w >= board_h:
        fig_w, fig_h = _LONG, _LONG * board_h / board_w
    else:
        fig_w, fig_h = _LONG * board_w / board_h, _LONG
    fig_w = max(fig_w, 1.0)
    fig_h = max(fig_h, 1.0)

    calc_fig = Figure(figsize=(fig_w, fig_h), dpi=_DPI, facecolor="black")
    calc_ax = calc_fig.add_axes([0.0, 0.0, 1.0, 1.0])
    calc_ax.set_facecolor("#000000")
    calc_ax.set_xlim(xmin, xmax)
    calc_ax.set_ylim(ymin, ymax)
    calc_ax.set_aspect("equal", adjustable="box")
    calc_ax.axis("off")

    # Render the layer (without profile outline to avoid edge anti-aliasing issues)
    features, matrix_layer = layers_data[layer_name]
    color = LAYER_COLORS.get(matrix_layer.type, "#00CC00")
    render_layer(
        calc_ax, features, color=color,
        layer_type=matrix_layer.type,
        alpha=1.0, user_symbols=user_symbols,
        font=font
    )

    # Rasterize to numpy RGBA
    agg = FigureCanvasAgg(calc_fig)
    agg.draw()
    buf = agg.buffer_rgba()
    w, h = agg.get_width_height()
    img = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
    rgb = img[:, :, :3]

    # Map outline → image-pixel coordinates
    display_pts = calc_ax.transData.transform(outline_verts)
    img_pts = np.column_stack([
        display_pts[:, 0],
        h - display_pts[:, 1],
    ])

    # Build inside-PCB mask
    path = MplPath(img_pts)
    ys, xs = np.mgrid[0:h, 0:w]
    pts = np.column_stack([xs.ravel() + 0.5, ys.ravel() + 0.5])
    pcb_mask = path.contains_points(pts).reshape(h, w)

    return {
        "rgb": rgb,
        "pcb_mask": pcb_mask,
        "xmin": xmin, "xmax": xmax,
        "ymin": ymin, "ymax": ymax,
        "img_w": w, "img_h": h,
    }


def calculate_copper_ratio(
    layer_name: str,
    profile: Profile,
    layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
    user_symbols: dict[str, UserSymbol],
    font: StrokeFont,
) -> Optional[float]:
    """Copper fill ratio for the entire layer (0 – 1)."""
    data = rasterize_layer(layer_name, profile, layers_data, user_symbols, font)
    if data is None:
        return None

    rgb = data["rgb"]
    inside_mask = data["pcb_mask"]
    total_inside = int(inside_mask.sum())
    if total_inside == 0:
        return None

    # "copper" = non-black AND not the red profile-outline colour
    is_nonblack = np.any(rgb > 20, axis=2)
    is_red = (
        (rgb[:, :, 0] > 180) &
        (rgb[:, :, 1] < 60) &
        (rgb[:, :, 2] < 60)
    )
    is_copper = is_nonblack & ~is_red
    copper_inside = int((inside_mask & is_copper).sum())
    return copper_inside / total_inside


def calculate_subsection_ratios(
    layer_name: str,
    profile: Profile,
    layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
    user_symbols: dict[str, UserSymbol],
    font: StrokeFont,
    n_rows: int = 5,
    n_cols: int = 5,
) -> Optional[np.ndarray]:
    """Copper fill ratio for each cell of an n_rows × n_cols grid.

    Returns an np.ndarray of shape (n_rows, n_cols) with values in [0, 1].
    Cells that contain no PCB area are set to np.nan.
    Returns None if rasterization fails.

    Grid orientation: Row 0 is the top of the PCB (y=ymax), column 0 is left (x=xmin).
    """
    data = rasterize_layer(layer_name, profile, layers_data, user_symbols, font)
    if data is None:
        return None

    rgb = data["rgb"]
    pcb_mask = data["pcb_mask"]
    h, w = data["img_h"], data["img_w"]

    # Copper pixel classification (same thresholds as calculate_copper_ratio)
    is_nonblack = np.any(rgb > 20, axis=2)
    is_red = (
        (rgb[:, :, 0] > 180) &
        (rgb[:, :, 1] < 60) &
        (rgb[:, :, 2] < 60)
    )
    is_copper = is_nonblack & ~is_red

    ratios = np.full((n_rows, n_cols), np.nan)
    for i in range(n_rows):
        r0 = round(i * h / n_rows)
        r1 = round((i + 1) * h / n_rows)
        for j in range(n_cols):
            c0 = round(j * w / n_cols)
            c1 = round((j + 1) * w / n_cols)

            cell_pcb = pcb_mask[r0:r1, c0:c1]
            total = int(cell_pcb.sum())
            if total == 0:
                continue
            copper = int((cell_pcb & is_copper[r0:r1, c0:c1]).sum())
            ratios[i, j] = copper / total

    return ratios


def draw_subsection_overlay(
    ax,
    fig: Figure,
    ratios: np.ndarray,
    profile: Profile,
    n_rows: int = 5,
    n_cols: int = 5,
) -> Optional:
    """Draw a colour-coded grid heatmap on ax.

    Each cell is filled with a RdYlGn colour proportional to its copper ratio.
    Cells with no PCB area are drawn as translucent grey.
    A colorbar legend is added to the figure.

    Returns the colorbar object (or None if it can't be drawn).
    """
    if ratios is None or profile is None or not profile.surface:
        return None

    # Re-derive bounding box from profile
    outline_verts = None
    for contour in profile.surface.contours:
        verts = contour_to_vertices(contour)
        if contour.is_island and len(verts) >= 3:
            outline_verts = verts
            break
    if outline_verts is None:
        return None

    xmin = float(outline_verts[:, 0].min())
    xmax = float(outline_verts[:, 0].max())
    ymin = float(outline_verts[:, 1].min())
    ymax = float(outline_verts[:, 1].max())
    board_w = xmax - xmin
    board_h = ymax - ymin
    cell_w = board_w / n_cols
    cell_h = board_h / n_rows

    cmap = cm.RdYlGn
    norm = mcolors.Normalize(vmin=0.0, vmax=1.0)

    for i in range(n_rows):
        # Row 0 in ratios array = top of board = ymax
        y_bottom = ymax - (i + 1) * cell_h
        for j in range(n_cols):
            x_left = xmin + j * cell_w
            ratio = ratios[i, j]

            if np.isnan(ratio):
                facecolor = "#aaaaaa"
                alpha = 0.15
                label = ""
            else:
                facecolor = cmap(norm(ratio))
                alpha = 0.55
                label = f"{ratio * 100:.1f}%"

            rect = mpatches.Rectangle(
                (x_left, y_bottom), cell_w, cell_h,
                facecolor=facecolor,
                edgecolor="white",
                linewidth=0.8,
                alpha=alpha,
                zorder=5,
            )
            ax.add_patch(rect)

            if label:
                cx = x_left + cell_w / 2
                cy = y_bottom + cell_h / 2
                # Pick text colour for readability over the cell fill
                r, g, b, _ = cmap(norm(ratio))
                lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
                txt_color = "black" if lum > 0.40 else "white"
                ax.text(
                    cx, cy, label,
                    ha="center", va="center",
                    fontsize=7, color=txt_color,
                    fontweight="bold", zorder=6,
                )

    # Colorbar
    sm = cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    colorbar = fig.colorbar(
        sm, ax=ax,
        fraction=0.02, pad=0.02, shrink=0.6,
        label="Copper Ratio",
    )
    colorbar.set_ticks([0, 0.25, 0.50, 0.75, 1.0])
    colorbar.set_ticklabels(["0%", "25%", "50%", "75%", "100%"])

    return colorbar


def save_layer_image(
    layer_name: str,
    profile: Profile,
    layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
    user_symbols: dict[str, UserSymbol],
    font: StrokeFont,
    subsection_ratios: Optional[np.ndarray],
    output_path: str | Path,
    dpi: int = 150,
) -> None:
    """Render a layer to an image file with optional sub-section overlay.

    Creates an off-screen figure, renders the layer + PCB outline,
    optionally draws the sub-section heatmap, and saves to output_path.
    """
    output_path = Path(output_path)

    if not profile or not profile.surface:
        return
    if layer_name not in layers_data:
        return

    # Find the PCB outline
    outline_verts = None
    for contour in profile.surface.contours:
        verts = contour_to_vertices(contour)
        if contour.is_island and len(verts) >= 3:
            outline_verts = verts
            break
    if outline_verts is None:
        return

    xmin = float(outline_verts[:, 0].min())
    xmax = float(outline_verts[:, 0].max())
    ymin = float(outline_verts[:, 1].min())
    ymax = float(outline_verts[:, 1].max())
    board_w = xmax - xmin
    board_h = ymax - ymin
    if board_w <= 0 or board_h <= 0:
        return

    # Create figure
    figsize = (12, 9)
    fig = Figure(figsize=figsize, facecolor="white")
    ax = fig.add_axes([0.07, 0.07, 0.90, 0.88])
    ax.set_facecolor("#000000")
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")

    # Draw profile outline
    _draw_profile(ax, profile)

    # Render layer
    features, matrix_layer = layers_data[layer_name]
    color = LAYER_COLORS.get(matrix_layer.type, "#00CC00")
    render_layer(
        ax, features, color=color,
        layer_type=matrix_layer.type,
        alpha=0.85, user_symbols=user_symbols,
        font=font
    )

    # Draw sub-section overlay if provided
    if subsection_ratios is not None:
        draw_subsection_overlay(ax, fig, subsection_ratios, profile)

    # Save to file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=dpi, bbox_inches="tight")
