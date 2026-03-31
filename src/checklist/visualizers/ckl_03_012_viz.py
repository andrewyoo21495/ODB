"""Visualization for CKL-03-012: OSC clearance to PCB edge and BOTHHOLE.

Produces one PNG per OSC component showing:
- The OSC pad geometry
- The board outline
- Nearby BOTHHOLE footprints
- Distance annotations to the PCB outline and nearest BOTHHOLE
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon as MplPolygon
import numpy as np

from src.checklist.geometry_utils import (
    build_board_polygon,
    _get_pad_union,
    _resolve_footprint,
    pad_distance_to_component,
    pad_distance_to_outline,
)

_MIN_CLEARANCE_MM = 1.0


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
    elif geom.geom_type in ("Point", "MultiPoint"):
        yield from _shapely_to_arrays(geom.buffer(0.05))
    elif geom.geom_type in ("LineString", "MultiLineString"):
        yield from _shapely_to_arrays(geom.buffer(0.01))


def _draw_geom(ax, geom, facecolor, edgecolor, alpha=0.45, label=None):
    """Fill a Shapely geometry on *ax*."""
    for xs, ys in _shapely_to_arrays(geom):
        verts = list(zip(xs, ys))
        ax.add_patch(MplPolygon(verts, closed=True, facecolor=facecolor,
                                edgecolor=edgecolor, alpha=alpha,
                                linewidth=0.8, label=label))
        label = None  # only label first patch


def _nearest_points_coords(geom_a, geom_b):
    """Return (xa, ya), (xb, yb) for the nearest points between two geometries."""
    from shapely.ops import nearest_points
    pa, pb = nearest_points(geom_a, geom_b)
    return (pa.x, pa.y), (pb.x, pb.y)


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_osc_clearance_image(
    osc, packages, board_poly, all_bothholes,
    dist_pcb: float, dist_bth: float,
    nearest_bth,
    output_path: Path,
    layer_name: str = "Top",
) -> Path:
    """Render a single OSC component's clearance situation to a PNG.

    Parameters
    ----------
    osc : Component
    packages : list[Package]
    board_poly : Shapely Polygon (board outline)
    all_bothholes : list[Component]
    dist_pcb : float – measured distance to PCB outline
    dist_bth : float – measured distance to nearest BOTHHOLE
    nearest_bth : Component | None – the nearest BOTHHOLE component
    output_path : Path
    layer_name : str

    Returns
    -------
    Path – *output_path*
    """
    pad_geom = _get_pad_union(osc, packages)
    if pad_geom is None:
        return output_path

    # --- figure setup --------------------------------------------------------
    pcb_ok = dist_pcb >= _MIN_CLEARANCE_MM or dist_pcb == float("inf")
    bth_ok = dist_bth >= _MIN_CLEARANCE_MM or dist_bth == float("inf")
    status = "PASS" if (pcb_ok and bth_ok) else "FAIL"

    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    ax.set_title(
        f"{osc.comp_name} ({osc.part_name}) — {layer_name} Layer\n"
        f"CKL-03-012: PCB edge & BOTHHOLE clearance  [{status}]",
        fontsize=12, fontweight="bold",
    )
    ax.set_aspect("equal")

    # --- board outline -------------------------------------------------------
    if board_poly is not None:
        for xs, ys in _shapely_to_arrays(board_poly):
            ax.plot(xs, ys, color="royalblue", linewidth=1.2)
            ax.fill(xs, ys, alpha=0.04, color="royalblue")

    # --- OSC pads ------------------------------------------------------------
    pad_color = "#90EE90" if status == "PASS" else "#FFB0B0"
    pad_edge = "darkgreen" if status == "PASS" else "darkred"
    _draw_geom(ax, pad_geom, pad_color, pad_edge, alpha=0.55,
               label=f"OSC pads ({osc.comp_name})")

    # Component centre marker
    ax.plot(osc.x, osc.y, "x", color="blue", markersize=10,
            markeredgewidth=2)

    # --- distance annotation: PCB outline ------------------------------------
    if board_poly is not None and dist_pcb < float("inf"):
        outline = board_poly.boundary
        (px, py), (ox, oy) = _nearest_points_coords(pad_geom, outline)
        line_color = "green" if pcb_ok else "red"
        ax.plot([px, ox], [py, oy], color=line_color, linewidth=2,
                linestyle="--", zorder=5)
        mid_x, mid_y = (px + ox) / 2, (py + oy) / 2
        ax.annotate(
            f"PCB edge: {dist_pcb:.3f} mm",
            (mid_x, mid_y),
            textcoords="offset points", xytext=(10, 10),
            fontsize=8, fontweight="bold", color=line_color,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                      edgecolor=line_color, alpha=0.9),
            arrowprops=dict(arrowstyle="->", color=line_color, lw=1.0),
            zorder=6,
        )

    # --- nearby BOTHHOLEs and distance annotation ----------------------------
    if nearest_bth is not None:
        fp_bth = _resolve_footprint(nearest_bth, packages)
        if fp_bth is not None:
            _draw_geom(ax, fp_bth, "#FFD080", "darkorange", alpha=0.5,
                       label=f"BOTHHOLE ({nearest_bth.comp_name})")

            if dist_bth < float("inf"):
                (px, py), (bx, by) = _nearest_points_coords(pad_geom, fp_bth)
                line_color = "green" if bth_ok else "red"
                ax.plot([px, bx], [py, by], color=line_color, linewidth=2,
                        linestyle="--", zorder=5)
                mid_x, mid_y = (px + bx) / 2, (py + by) / 2
                ax.annotate(
                    f"BOTHHOLE: {dist_bth:.3f} mm",
                    (mid_x, mid_y),
                    textcoords="offset points", xytext=(10, -15),
                    fontsize=8, fontweight="bold", color=line_color,
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                              edgecolor=line_color, alpha=0.9),
                    arrowprops=dict(arrowstyle="->", color=line_color, lw=1.0),
                    zorder=6,
                )

    # Also draw other nearby BOTHHOLEs (dimmed) for context
    for bth in all_bothholes:
        if nearest_bth is not None and bth.comp_name == nearest_bth.comp_name:
            continue
        fp = _resolve_footprint(bth, packages)
        if fp is not None:
            _draw_geom(ax, fp, "#E0D0A0", "tan", alpha=0.3)

    # --- viewport: zoom to OSC pad extent with margin for context ------------
    pad_bounds = pad_geom.bounds  # (minx, miny, maxx, maxy)
    span_x = pad_bounds[2] - pad_bounds[0]
    span_y = pad_bounds[3] - pad_bounds[1]
    span = max(span_x, span_y, 1.0)
    # Extend viewport to include nearest BOTHHOLE and PCB edge line if present
    view_pts_x = [pad_bounds[0], pad_bounds[2]]
    view_pts_y = [pad_bounds[1], pad_bounds[3]]

    if nearest_bth is not None:
        fp_bth = _resolve_footprint(nearest_bth, packages)
        if fp_bth is not None:
            bb = fp_bth.bounds
            view_pts_x.extend([bb[0], bb[2]])
            view_pts_y.extend([bb[1], bb[3]])

    if board_poly is not None and dist_pcb < float("inf"):
        outline = board_poly.boundary
        _, (ox, oy) = _nearest_points_coords(pad_geom, outline)
        view_pts_x.append(ox)
        view_pts_y.append(oy)

    vx_min, vx_max = min(view_pts_x), max(view_pts_x)
    vy_min, vy_max = min(view_pts_y), max(view_pts_y)
    v_span = max(vx_max - vx_min, vy_max - vy_min, 1.0)
    v_cx = (vx_min + vx_max) / 2
    v_cy = (vy_min + vy_max) / 2
    margin = v_span * 0.4
    ax.set_xlim(v_cx - v_span / 2 - margin, v_cx + v_span / 2 + margin)
    ax.set_ylim(v_cy - v_span / 2 - margin, v_cy + v_span / 2 + margin)

    # --- legend --------------------------------------------------------------
    legend_elements = [
        mpatches.Patch(facecolor=pad_color, edgecolor=pad_edge, alpha=0.55,
                       label=f"OSC pads"),
        plt.Line2D([], [], color="royalblue", linewidth=1.2,
                   label="Board outline"),
        plt.Line2D([], [], color="green", linewidth=2, linestyle="--",
                   label=f"Distance >= {_MIN_CLEARANCE_MM} mm (OK)"),
        plt.Line2D([], [], color="red", linewidth=2, linestyle="--",
                   label=f"Distance < {_MIN_CLEARANCE_MM} mm (FAIL)"),
    ]
    if nearest_bth is not None:
        legend_elements.insert(1,
            mpatches.Patch(facecolor="#FFD080", edgecolor="darkorange",
                           alpha=0.5, label="BOTHHOLE (nearest)"))
    ax.legend(handles=legend_elements, loc="upper left", fontsize=8)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.grid(True, alpha=0.3)

    # --- save ----------------------------------------------------------------
    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path
