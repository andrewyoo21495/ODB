"""Narrow-width area visualisation for CKL-01-010.

Renders a full-board PNG showing:
- Board outline (grey)
- Narrow-width areas (width <= 3.5 mm) highlighted in red/orange
- Region labels (region1, region2, ...) annotated on each narrow area
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon as MplPolygon
import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shapely_to_arrays(geom):
    """Yield (xs, ys) arrays for each ring of a Shapely geometry."""
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        xs, ys = geom.exterior.xy
        yield np.array(xs), np.array(ys)
    elif geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        for part in geom.geoms:
            yield from _shapely_to_arrays(part)


def _draw_geom(ax, geom, facecolor, edgecolor, alpha=0.45, label=None):
    """Fill a Shapely geometry on *ax*."""
    for xs, ys in _shapely_to_arrays(geom):
        verts = list(zip(xs, ys))
        ax.add_patch(MplPolygon(verts, closed=True, facecolor=facecolor,
                                edgecolor=edgecolor, alpha=alpha,
                                linewidth=0.8, label=label))
        label = None  # only label first patch


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_narrow_width_image(
    board_poly,
    narrow_areas: list,
    region_labels: list[str],
    output_path: Path,
    *,
    rule_id: str = "CKL-01-010",
    title: str = "Narrow-width areas (width <= 3.5 mm)",
) -> Path:
    """Render full-board narrow-width area check image.

    Parameters
    ----------
    board_poly : Shapely Polygon
        The board outline polygon.
    narrow_areas : list[Shapely Polygon]
        Narrow-width area polygons (width <= 3.5 mm).
    region_labels : list[str]
        Labels for each narrow area (e.g. ["region1", "region2", ...]).
        Must be same length as *narrow_areas*.
    output_path : Path
    rule_id : str
    title : str

    Returns
    -------
    Path
    """
    fig, ax = plt.subplots(1, 1, figsize=(12, 10))

    status = "FAIL" if narrow_areas else "PASS"
    ax.set_title(
        f"{rule_id}: {title}  [{status}]",
        fontsize=13, fontweight="bold",
    )
    ax.set_aspect("equal")

    # --- Board outline -------------------------------------------------------
    if board_poly is not None:
        for xs, ys in _shapely_to_arrays(board_poly):
            ax.plot(xs, ys, color="dimgray", linewidth=1.5)
            ax.fill(xs, ys, alpha=0.06, color="lightgray")

    # --- Narrow-width areas --------------------------------------------------
    colors = [
        "#FF4444", "#FF8800", "#CC44CC", "#4488FF",
        "#44BB44", "#BBBB00", "#FF6688", "#8844FF",
    ]
    for idx, (area, label) in enumerate(zip(narrow_areas, region_labels)):
        color = colors[idx % len(colors)]
        _draw_geom(ax, area, facecolor=color, edgecolor="darkred",
                   alpha=0.40, label=label)

        # Annotate region label at centroid
        centroid = area.centroid
        ax.annotate(
            label,
            (centroid.x, centroid.y),
            fontsize=9, fontweight="bold", color="black",
            ha="center", va="center",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                      edgecolor=color, alpha=0.9, linewidth=1.5),
            zorder=10,
        )

    # --- Viewport ------------------------------------------------------------
    if board_poly is not None:
        bx_min, by_min, bx_max, by_max = board_poly.bounds
        span = max(bx_max - bx_min, by_max - by_min, 1.0)
        cx = (bx_min + bx_max) / 2
        cy = (by_min + by_max) / 2
        margin = span * 0.08
        ax.set_xlim(cx - span / 2 - margin, cx + span / 2 + margin)
        ax.set_ylim(cy - span / 2 - margin, cy + span / 2 + margin)

    # --- Legend --------------------------------------------------------------
    legend_elements = [
        plt.Line2D([], [], color="dimgray", linewidth=1.5,
                   label="Board outline"),
        mpatches.Patch(facecolor="#FF4444", edgecolor="darkred", alpha=0.40,
                       label="Narrow-width area (<= 3.5 mm)"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", fontsize=9)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.grid(True, alpha=0.2)

    # --- Save ----------------------------------------------------------------
    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path
