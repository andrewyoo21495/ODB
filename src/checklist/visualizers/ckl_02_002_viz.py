"""Visualization for CKL-02-002: Managed capacitors vs connectors.

Produces one PNG per connector showing:
- The connector footprint / pad geometry
- All opposite-side components overlapping the connector (dimmed)
- Managed capacitors colour-coded by PASS (green) / FAIL (red)
- Annotations with capacitor name and status details
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
    _resolve_outline,
    find_components_inside_outline,
    find_pad_overlapping_components,
    get_pair_orientation,
    is_on_edge,
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


def _draw_geom(ax, geom, facecolor, edgecolor, alpha=0.45, label=None,
               linewidth=0.8):
    """Fill a Shapely geometry on *ax*."""
    for xs, ys in _shapely_to_arrays(geom):
        verts = list(zip(xs, ys))
        ax.add_patch(MplPolygon(verts, closed=True, facecolor=facecolor,
                                edgecolor=edgecolor, alpha=alpha,
                                linewidth=linewidth, label=label))
        label = None  # only label first patch


def _geom_bounds(geom):
    """Return (minx, miny, maxx, maxy) or None."""
    if geom is None or geom.is_empty:
        return None
    return geom.bounds


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_connector_cap_image(
    conn,
    conn_layer: str,
    packages,
    opp_managed_caps: list,
    all_opp_comps: list,
    cap_results: dict,
    output_path: Path,
) -> Path:
    """Render a single connector with opposite-side capacitors to a PNG.

    Parameters
    ----------
    conn : Component
        The connector component.
    conn_layer : str
        "Top" or "Bottom".
    packages : list[Package]
    opp_managed_caps : list[Component]
        Managed capacitors on the opposite side.
    all_opp_comps : list[Component]
        All components on the opposite side (for context overlay).
    cap_results : dict
        Mapping from cap.comp_name -> {"status": "PASS"/"FAIL",
        "edge": bool, "orientation": str}.
    output_path : Path

    Returns
    -------
    Path
    """
    # --- build geometries ---------------------------------------------------
    conn_pad_geom = _get_pad_union(conn, packages)
    conn_outline = _resolve_outline(conn, packages)
    conn_footprint = _resolve_footprint(conn, packages)

    # Use the largest available geometry for the connector display
    conn_display = conn_outline or conn_footprint or conn_pad_geom

    if conn_display is None:
        # Nothing to draw
        return output_path

    # --- figure setup -------------------------------------------------------
    has_fail = any(r["status"] == "FAIL" for r in cap_results.values())
    status = "FAIL" if has_fail else ("PASS" if cap_results else "N/A")

    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    ax.set_title(
        f"{conn.comp_name} ({conn.part_name}) — {conn_layer} Layer\n"
        f"CKL-02-002: Managed capacitor alignment  [{status}]",
        fontsize=12, fontweight="bold",
    )
    ax.set_aspect("equal")

    # --- draw connector outline / footprint ---------------------------------
    if conn_outline is not None:
        _draw_geom(ax, conn_outline, "#B0C4DE", "steelblue", alpha=0.25,
                   label=f"Connector outline ({conn.comp_name})",
                   linewidth=1.2)
    if conn_pad_geom is not None:
        _draw_geom(ax, conn_pad_geom, "#6495ED", "navy", alpha=0.35,
                   label="Connector pads")

    # Connector centre marker
    ax.plot(conn.x, conn.y, "s", color="navy", markersize=8,
            markeredgewidth=2, zorder=4)

    # --- draw non-managed opposite-side components (dimmed context) ----------
    managed_names = {c.comp_name for c in opp_managed_caps}
    for comp in all_opp_comps:
        if comp.comp_name in managed_names:
            continue
        fp = _resolve_footprint(comp, packages)
        if fp is None:
            continue
        # Check if this component is close enough to the connector to show
        if conn_display is not None:
            if conn_display.distance(fp) > 5.0:
                continue
        _draw_geom(ax, fp, "#D3D3D3", "gray", alpha=0.2)

    # --- draw managed capacitors with PASS/FAIL colouring -------------------
    view_pts_x = []
    view_pts_y = []

    # Include connector bounds in viewport
    cb = _geom_bounds(conn_display)
    if cb:
        view_pts_x.extend([cb[0], cb[2]])
        view_pts_y.extend([cb[1], cb[3]])

    for cap in opp_managed_caps:
        info = cap_results.get(cap.comp_name)
        if info is None:
            continue

        is_pass = info["status"] == "PASS"
        fill_color = "#90EE90" if is_pass else "#FFB0B0"
        edge_color = "darkgreen" if is_pass else "darkred"

        cap_pad_geom = _get_pad_union(cap, packages)
        cap_fp = _resolve_footprint(cap, packages)
        draw_geom = cap_pad_geom or cap_fp

        if draw_geom is not None:
            _draw_geom(ax, draw_geom, fill_color, edge_color, alpha=0.55,
                       linewidth=1.5)
            bb = _geom_bounds(draw_geom)
            if bb:
                view_pts_x.extend([bb[0], bb[2]])
                view_pts_y.extend([bb[1], bb[3]])
        else:
            # Fallback: marker at component centre
            ax.plot(cap.x, cap.y, "o", color=edge_color, markersize=6)
            view_pts_x.append(cap.x)
            view_pts_y.append(cap.y)

        # Annotation
        edge_str = "Edge" if info.get("edge") else ""
        orient_str = info.get("orientation", "")
        detail = ", ".join(filter(None, [orient_str, edge_str]))
        label_text = f"{cap.comp_name}\n{info['status']}"
        if detail:
            label_text += f" ({detail})"

        label_color = "darkgreen" if is_pass else "darkred"
        ax.annotate(
            label_text,
            (cap.x, cap.y),
            textcoords="offset points", xytext=(14, 14),
            fontsize=7, color=label_color,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                      edgecolor=label_color, alpha=0.85),
            arrowprops=dict(arrowstyle="->", color=label_color, lw=0.8),
            zorder=6,
        )

    # --- viewport -----------------------------------------------------------
    if not view_pts_x:
        plt.close(fig)
        return output_path

    vx_min, vx_max = min(view_pts_x), max(view_pts_x)
    vy_min, vy_max = min(view_pts_y), max(view_pts_y)
    v_span = max(vx_max - vx_min, vy_max - vy_min, 1.0)
    v_cx = (vx_min + vx_max) / 2
    v_cy = (vy_min + vy_max) / 2
    margin = v_span * 0.3
    ax.set_xlim(v_cx - v_span / 2 - margin, v_cx + v_span / 2 + margin)
    ax.set_ylim(v_cy - v_span / 2 - margin, v_cy + v_span / 2 + margin)

    # --- legend -------------------------------------------------------------
    legend_elements = [
        mpatches.Patch(facecolor="#B0C4DE", edgecolor="steelblue", alpha=0.25,
                       label="Connector outline"),
        mpatches.Patch(facecolor="#6495ED", edgecolor="navy", alpha=0.35,
                       label="Connector pads"),
        mpatches.Patch(facecolor="#90EE90", edgecolor="darkgreen", alpha=0.55,
                       label="Managed cap (PASS)"),
        mpatches.Patch(facecolor="#FFB0B0", edgecolor="darkred", alpha=0.55,
                       label="Managed cap (FAIL)"),
        mpatches.Patch(facecolor="#D3D3D3", edgecolor="gray", alpha=0.2,
                       label="Other components"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", fontsize=8)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.grid(True, alpha=0.3)

    # --- save ---------------------------------------------------------------
    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path
