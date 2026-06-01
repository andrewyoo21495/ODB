"""Bending-vulnerable area visualisation for CKL-03-011.

Renders a full-board PNG showing:
- Board outline (grey)
- Bending-vulnerable areas (red/orange overlay)
- OSC components (blue markers for PASS, red markers for FAIL)
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

def render_bending_image(
    board_poly,
    vulnerable_areas: list,
    osc_results: list[dict],
    output_path: Path,
    *,
    rule_id: str = "CKL-03-011",
    title: str = "OSC in bending-vulnerable areas",
) -> Path:
    """Render full-board bending vulnerability check image.

    Parameters
    ----------
    board_poly : Shapely Polygon
        The board outline polygon.
    vulnerable_areas : list[Shapely Polygon]
        Bending-vulnerable area polygons.
    osc_results : list[dict]
        Each dict has:
          - "comp_name": str
          - "x": float  (board coordinate)
          - "y": float  (board coordinate)
          - "layer": str ("Top" / "Bottom")
          - "status": str ("PASS" / "FAIL")
    output_path : Path
    rule_id : str
    title : str

    Returns
    -------
    Path
    """
    fig, ax = plt.subplots(1, 1, figsize=(12, 10))

    fail_count = sum(1 for r in osc_results if r["status"] == "FAIL")
    overall = "PASS" if fail_count == 0 else "FAIL"

    ax.set_title(
        f"{rule_id}: {title}  [{overall}]",
        fontsize=13, fontweight="bold",
    )
    ax.set_aspect("equal")

    # --- Board outline -------------------------------------------------------
    if board_poly is not None:
        for xs, ys in _shapely_to_arrays(board_poly):
            ax.plot(xs, ys, color="dimgray", linewidth=1.5)
            ax.fill(xs, ys, alpha=0.06, color="lightgray")

    # --- Bending-vulnerable areas --------------------------------------------
    first_vuln = True
    for area in vulnerable_areas:
        label = "Bending-vulnerable area" if first_vuln else None
        _draw_geom(ax, area, facecolor="#FF4444", edgecolor="darkred",
                   alpha=0.35, label=label)
        first_vuln = False

    # --- OSC components ------------------------------------------------------
    for r in osc_results:
        if r["status"] == "FAIL":
            ax.plot(r["x"], r["y"], "s", color="red", markersize=10,
                    markeredgecolor="darkred", markeredgewidth=1.5, zorder=5)
            ax.annotate(
                r["comp_name"],
                (r["x"], r["y"]),
                textcoords="offset points", xytext=(8, 8),
                fontsize=7, fontweight="bold", color="red",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                          edgecolor="red", alpha=0.85),
                zorder=6,
            )
        else:
            ax.plot(r["x"], r["y"], "o", color="#4488FF", markersize=8,
                    markeredgecolor="navy", markeredgewidth=1.2, zorder=5)
            ax.annotate(
                r["comp_name"],
                (r["x"], r["y"]),
                textcoords="offset points", xytext=(8, 8),
                fontsize=7, color="navy",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                          edgecolor="navy", alpha=0.75),
                zorder=6,
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
        mpatches.Patch(facecolor="#FF4444", edgecolor="darkred", alpha=0.35,
                       label="Bending-vulnerable area"),
        plt.Line2D([], [], marker="o", color="w", markerfacecolor="#4488FF",
                   markeredgecolor="navy", markersize=8,
                   label="OSC (PASS)"),
        plt.Line2D([], [], marker="s", color="w", markerfacecolor="red",
                   markeredgecolor="darkred", markersize=10,
                   label="OSC (FAIL)"),
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
