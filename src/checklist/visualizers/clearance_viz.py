"""Shared visualization for PCB edge / component clearance rules.

Produces one PNG per component showing:
- The component pad geometry
- The board outline
- Nearby reference components (e.g. BOTHHOLE footprints)
- Distance annotations to the PCB outline and nearest reference component

Used by: CKL-03-012.
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
    _get_pad_union,
    _resolve_footprint,
)


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

def render_clearance_image(
    comp,
    packages,
    board_poly,
    ref_comps: list,
    distances: list[dict],
    output_path: Path,
    *,
    rule_id: str,
    title: str,
    layer_name: str = "Top",
    comp_label: str = "Component",
    ref_label: str = "Reference",
    min_clearance: float = 1.0,
) -> Path:
    """Render a component's clearance to board edge and reference components.

    Parameters
    ----------
    comp : Component
        The primary component to visualise.
    packages : list[Package]
    board_poly : Shapely Polygon | None
        Board outline geometry.
    ref_comps : list[Component]
        Reference components (e.g. BOTHHOLEs) to display.
    distances : list[dict]
        Each dict has:
          - "label": str – annotation label (e.g. "PCB edge", "BOTHHOLE")
          - "value": float – measured distance
          - "target_geom": Shapely geometry | None – the target to draw a line to
          - "target_comp": Component | None – if this is a component, draw its footprint
        The first entry is typically the board-edge distance.
    output_path : Path
    rule_id : str
    title : str
    layer_name : str
    comp_label : str
    ref_label : str
    min_clearance : float

    Returns
    -------
    Path
    """
    pad_geom = _get_pad_union(comp, packages)
    if pad_geom is None:
        return output_path

    # --- figure setup --------------------------------------------------------
    all_ok = all(
        d["value"] >= min_clearance or d["value"] == float("inf")
        for d in distances
    )
    status = "PASS" if all_ok else "FAIL"

    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    ax.set_title(
        f"{comp.comp_name} ({comp.part_name}) — {layer_name} Layer\n"
        f"{rule_id}: {title}  [{status}]",
        fontsize=12, fontweight="bold",
    )
    ax.set_aspect("equal")

    # --- board outline -------------------------------------------------------
    if board_poly is not None:
        for xs, ys in _shapely_to_arrays(board_poly):
            ax.plot(xs, ys, color="royalblue", linewidth=1.2)
            ax.fill(xs, ys, alpha=0.04, color="royalblue")

    # --- component pads ------------------------------------------------------
    pad_color = "#90EE90" if status == "PASS" else "#FFB0B0"
    pad_edge = "darkgreen" if status == "PASS" else "darkred"
    _draw_geom(ax, pad_geom, pad_color, pad_edge, alpha=0.55,
               label=f"{comp_label} pads ({comp.comp_name})")

    # Component centre marker
    ax.plot(comp.x, comp.y, "x", color="blue", markersize=10,
            markeredgewidth=2)

    # --- distance annotations ------------------------------------------------
    view_pts_x, view_pts_y = [], []
    pad_bounds = pad_geom.bounds
    view_pts_x.extend([pad_bounds[0], pad_bounds[2]])
    view_pts_y.extend([pad_bounds[1], pad_bounds[3]])

    xytext_offsets = [(10, 10), (10, -15), (-15, 10), (-15, -15)]
    for idx, d in enumerate(distances):
        dist_val = d["value"]
        if dist_val == float("inf"):
            continue

        target_geom = d.get("target_geom")
        target_comp = d.get("target_comp")

        # Draw target component footprint if provided
        if target_comp is not None:
            fp = _resolve_footprint(target_comp, packages)
            if fp is not None:
                _draw_geom(ax, fp, "#FFD080", "darkorange", alpha=0.5,
                           label=f"{ref_label} ({target_comp.comp_name})")
                bb = fp.bounds
                view_pts_x.extend([bb[0], bb[2]])
                view_pts_y.extend([bb[1], bb[3]])
                if target_geom is None:
                    target_geom = fp

        if target_geom is None:
            continue

        # Distance measurement line
        try:
            (px, py), (tx, ty) = _nearest_points_coords(pad_geom, target_geom)
        except Exception:
            continue

        dist_ok = dist_val >= min_clearance
        line_color = "green" if dist_ok else "red"
        ax.plot([px, tx], [py, ty], color=line_color, linewidth=2,
                linestyle="--", zorder=5)
        mid_x, mid_y = (px + tx) / 2, (py + ty) / 2
        view_pts_x.append(tx)
        view_pts_y.append(ty)

        offset = xytext_offsets[idx % len(xytext_offsets)]
        ax.annotate(
            f"{d['label']}: {dist_val:.3f} mm",
            (mid_x, mid_y),
            textcoords="offset points", xytext=offset,
            fontsize=8, fontweight="bold", color=line_color,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                      edgecolor=line_color, alpha=0.9),
            arrowprops=dict(arrowstyle="->", color=line_color, lw=1.0),
            zorder=6,
        )

    # --- draw other reference components (dimmed) ----------------------------
    highlighted = {d.get("target_comp") for d in distances if d.get("target_comp")}
    for rc in ref_comps:
        if rc in highlighted:
            continue
        fp = _resolve_footprint(rc, packages)
        if fp is not None:
            _draw_geom(ax, fp, "#E0D0A0", "tan", alpha=0.3)

    # --- viewport ------------------------------------------------------------
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
                       label=f"{comp_label} pads"),
        plt.Line2D([], [], color="royalblue", linewidth=1.2,
                   label="Board outline"),
        plt.Line2D([], [], color="green", linewidth=2, linestyle="--",
                   label=f"Distance >= {min_clearance} mm (OK)"),
        plt.Line2D([], [], color="red", linewidth=2, linestyle="--",
                   label=f"Distance < {min_clearance} mm (FAIL)"),
    ]
    if any(d.get("target_comp") for d in distances):
        legend_elements.insert(1,
            mpatches.Patch(facecolor="#FFD080", edgecolor="darkorange",
                           alpha=0.5, label=f"{ref_label} (nearest)"))
    ax.legend(handles=legend_elements, loc="upper left", fontsize=8)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.grid(True, alpha=0.3)

    # --- save ----------------------------------------------------------------
    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path
