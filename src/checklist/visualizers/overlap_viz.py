"""Shared visualization for opposite-side overlap checklist rules.

Produces one PNG per primary component showing:
- The primary component footprint / pad / outline geometry
- Overlapping opposite-side components colour-coded by PASS (green) / FAIL (red)
- Optional annotations with details (edge, orientation, distance, etc.)
- Nearby non-overlapping opposite-side components drawn dimmed for context

Used by: CKL-01-001, CKL-01-003, CKL-01-004, CKL-01-005, CKL-01-006,
         CKL-01-007, CKL-02-001, CKL-02-002, CKL-02-004, CKL-02-006,
         CKL-02-008, CKL-02-009, CKL-02-010, CKL-02-011, CKL-02-012,
         CKL-03-001, CKL-03-016.
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


def _nearest_points_coords(geom_a, geom_b):
    """Return (xa, ya), (xb, yb) for the nearest points between two geometries."""
    from shapely.ops import nearest_points
    pa, pb = nearest_points(geom_a, geom_b)
    return (pa.x, pa.y), (pb.x, pb.y)


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_overlap_image(
    primary,
    packages,
    overlap_items: list[dict],
    all_opp_comps: list,
    output_path: Path,
    *,
    rule_id: str,
    title: str,
    layer_name: str,
    primary_label: str = "Primary",
    overlap_label: str = "Overlapping",
    context_radius: float = 5.0,
    primary_is_bottom: bool = False,
    overlap_is_bottom: bool = False,
    user_symbols: dict | None = None,
    inner_walls: list | None = None,
) -> Path:
    """Render a single primary component with overlapping opposite-side parts.

    Parameters
    ----------
    primary : Component
        The primary component to visualise.
    packages : list[Package]
    overlap_items : list[dict]
        Each dict must have:
          - "comp": Component object
          - "status": "PASS" or "FAIL"
        Optional keys:
          - "detail": str – extra annotation text (e.g. "Horizontal, Edge")
          - "distance": float – if present, draw a distance measurement line
          - "min_distance": float – threshold for distance colour
    all_opp_comps : list[Component]
        All opposite-side components (for dimmed context rendering).
    output_path : Path
    rule_id : str
    title : str – Short description for the chart title.
    layer_name : str – "Top" or "Bottom".
    primary_label : str – Legend label for the primary component.
    overlap_label : str – Legend label for overlapping components.
    context_radius : float – Max distance for context components (mm).
    inner_walls : list[LineString] | None
        Optional inner wall line geometries (e.g. from detect_inner_walls).
        Drawn in fluorescent yellow-green to make them stand out.

    Returns
    -------
    Path
    """
    # --- build geometries ---------------------------------------------------
    conn_pad_geom = _get_pad_union(primary, packages, is_bottom=primary_is_bottom,
                                   user_symbols=user_symbols)
    conn_outline = _resolve_outline(primary, packages, is_bottom=primary_is_bottom)
    conn_footprint = _resolve_footprint(primary, packages, is_bottom=primary_is_bottom)
    conn_display = conn_outline or conn_footprint or conn_pad_geom

    if conn_display is None:
        return output_path

    # --- figure setup -------------------------------------------------------
    has_fail = any(r["status"] == "FAIL" for r in overlap_items)
    status = "FAIL" if has_fail else ("PASS" if overlap_items else "N/A")

    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    ax.set_title(
        f"{primary.comp_name} ({primary.part_name}) — {layer_name} Layer\n"
        f"{rule_id}: {title}  [{status}]",
        fontsize=12, fontweight="bold",
    )
    ax.set_aspect("equal")

    # --- draw primary outline / pads ----------------------------------------
    if conn_outline is not None:
        _draw_geom(ax, conn_outline, "#B0C4DE", "steelblue", alpha=0.25,
                   label=f"{primary_label} outline ({primary.comp_name})",
                   linewidth=1.2)
    if conn_pad_geom is not None:
        _draw_geom(ax, conn_pad_geom, "#6495ED", "navy", alpha=0.35,
                   label=f"{primary_label} pads")

    # Primary centre marker
    ax.plot(primary.x, primary.y, "s", color="navy", markersize=8,
            markeredgewidth=2, zorder=4)

    # --- draw inner walls (fluorescent yellow-green) -------------------------
    if inner_walls:
        first = True
        for wall in inner_walls:
            geoms = list(wall.geoms) if hasattr(wall, "geoms") else [wall]
            for g in geoms:
                coords = list(g.coords)
                xs = [c[0] for c in coords]
                ys = [c[1] for c in coords]
                ax.plot(xs, ys, color="#CCFF00", linewidth=4, zorder=5,
                        solid_capstyle="round",
                        label="Inner wall" if first else None)
                first = False

    # --- draw context components (dimmed) -----------------------------------
    overlap_names = {item["comp"].comp_name for item in overlap_items}
    for comp in all_opp_comps:
        if comp.comp_name in overlap_names:
            continue
        fp = _resolve_footprint(comp, packages, is_bottom=overlap_is_bottom)
        if fp is None:
            continue
        if conn_display is not None and conn_display.distance(fp) > context_radius:
            continue
        _draw_geom(ax, fp, "#D3D3D3", "gray", alpha=0.2)

    # --- draw overlapping components ----------------------------------------
    view_pts_x, view_pts_y = [], []
    cb = _geom_bounds(conn_display)
    if cb:
        view_pts_x.extend([cb[0], cb[2]])
        view_pts_y.extend([cb[1], cb[3]])

    for item in overlap_items:
        comp = item["comp"]
        is_pass = item["status"] == "PASS"
        fill_color = "#90EE90" if is_pass else "#FFB0B0"
        edge_color = "darkgreen" if is_pass else "darkred"

        comp_pad_geom = _get_pad_union(comp, packages, is_bottom=overlap_is_bottom,
                                       user_symbols=user_symbols)
        comp_fp = _resolve_footprint(comp, packages, is_bottom=overlap_is_bottom)
        draw_geom = comp_pad_geom or comp_fp

        if draw_geom is not None:
            _draw_geom(ax, draw_geom, fill_color, edge_color, alpha=0.55,
                       linewidth=1.5)
            bb = _geom_bounds(draw_geom)
            if bb:
                view_pts_x.extend([bb[0], bb[2]])
                view_pts_y.extend([bb[1], bb[3]])
        else:
            ax.plot(comp.x, comp.y, "o", color=edge_color, markersize=6)
            view_pts_x.append(comp.x)
            view_pts_y.append(comp.y)

        # --- optional distance line -----------------------------------------
        distance = item.get("distance")
        if distance is not None and draw_geom is not None and conn_display is not None:
            min_dist = item.get("min_distance", 0)
            try:
                (px, py), (cx, cy) = _nearest_points_coords(draw_geom, conn_display)
                dist_ok = distance >= min_dist
                line_color = "green" if dist_ok else "red"
                ax.plot([px, cx], [py, cy], color=line_color, linewidth=2,
                        linestyle="--", zorder=5)
                mid_x, mid_y = (px + cx) / 2, (py + cy) / 2
                ax.annotate(
                    f"{distance:.3f} mm",
                    (mid_x, mid_y),
                    textcoords="offset points", xytext=(10, 10),
                    fontsize=8, fontweight="bold", color=line_color,
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                              edgecolor=line_color, alpha=0.9),
                    arrowprops=dict(arrowstyle="->", color=line_color, lw=1.0),
                    zorder=6,
                )
            except Exception:
                pass

        # --- annotation text ------------------------------------------------
        detail = item.get("detail", "")
        label_text = f"{comp.comp_name}\n{item['status']}"
        if detail:
            label_text += f" ({detail})"

        label_color = "darkgreen" if is_pass else "darkred"
        ax.annotate(
            label_text,
            (comp.x, comp.y),
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
                       label=f"{primary_label} outline"),
        mpatches.Patch(facecolor="#6495ED", edgecolor="navy", alpha=0.35,
                       label=f"{primary_label} pads"),
    ]
    if inner_walls:
        legend_elements.append(
            plt.Line2D([0], [0], color="#CCFF00", linewidth=4,
                       label="Inner wall")
        )
    legend_elements += [
        mpatches.Patch(facecolor="#90EE90", edgecolor="darkgreen", alpha=0.55,
                       label=f"{overlap_label} (PASS)"),
        mpatches.Patch(facecolor="#FFB0B0", edgecolor="darkred", alpha=0.55,
                       label=f"{overlap_label} (FAIL)"),
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
