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
    get_edge_segments,
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


def _rings_to_arrays(geom):
    """Yield (xs, ys) arrays for *every* ring of a geometry — exterior AND
    interior rings (holes).

    Unlike :func:`_shapely_to_arrays` (exteriors only, for fills), this is used
    to *stroke* frame outlines that may be donut/frame shaped, e.g. an
    interposer's container-frame outline whose inner ring must also be drawn.
    """
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        xs, ys = geom.exterior.xy
        yield np.array(xs), np.array(ys)
        for interior in geom.interiors:
            ixs, iys = interior.xy
            yield np.array(ixs), np.array(iys)
    elif geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        for part in geom.geoms:
            yield from _rings_to_arrays(part)
    elif geom.geom_type == "LineString":
        xs, ys = geom.xy
        yield np.array(xs), np.array(ys)
    elif geom.geom_type == "MultiLineString":
        for part in geom.geoms:
            yield from _rings_to_arrays(part)


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
    outer_outline=None,
    inset_line=None,
    interposer_outer_outline=None,
    interposer_inner_outline=None,
    show_edge_segments: bool = False,
    annotate_pass: bool = True,
    annotate_primary: bool = False,
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
    inset_line : LineString | MultiLineString | None
        Optional inner-wall inset line (outer outline eroded inward). Drawn
        as a solid red line for debugging inner-wall detection.
    show_edge_segments : bool
        When True, overlay *primary*'s edge segments (the exact lines used by
        ``is_on_edge`` / ``is_on_outline_edge``) as red dashed lines, so the
        edge decision can be verified visually. Used by the edge-based rules.
    annotate_pass : bool
        When False, PASS overlap items are drawn as green geometry only,
        without the per-component text label/arrow (FAIL items still get a
        red label). Keeps cluttered images readable when only failures need
        callouts. Defaults to True (label every item).
    annotate_primary : bool
        When True, draw the *primary* component's name as a text label next to
        its centre marker (by default the primary has only a marker, no tag).
        Defaults to False.

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
    if annotate_primary:
        ax.annotate(
            primary.comp_name,
            (primary.x, primary.y),
            textcoords="offset points", xytext=(0, -16),
            fontsize=8, fontweight="bold", color="navy", ha="center",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                      edgecolor="navy", alpha=0.9),
            zorder=7,
        )

    # --- draw edge segments (red dashed; debug overlay of the edge decision) --
    # Disabled for now (kept for future debugging). Re-enable this block and the
    # legend entry below, plus the show_edge_segments=True args in the rules.
    # The exact segments is_on_edge / is_on_outline_edge test against, so the
    # operator can verify which part of the connector counts as the "edge".
    # edge_segments = (
    #     get_edge_segments(primary, packages, is_bottom=primary_is_bottom)
    #     if show_edge_segments else []
    # )
    # _has_edge_segs = bool(edge_segments)
    # _first_edge = True
    # for (x1, y1), (x2, y2) in edge_segments:
    #     ax.plot([x1, x2], [y1, y2], color="red", linewidth=2.0,
    #             linestyle="--", zorder=7,
    #             label="Edge (review line)" if _first_edge else None)
    #     _first_edge = False
    _has_edge_segs = False

    # --- draw outermost outline boundary (black dashed) -------------------------
    # outer_outline is the filled unary_union of all pkg.outlines — the
    # same geometry used as the CONTAINER FRAME and perimeter reference
    # for detect_inner_walls().
    # When it is None the package has no component-level outlines at all,
    # which also means detect_inner_walls() cannot work.
    _has_outer_outline = (outer_outline is not None and not outer_outline.is_empty)
    if _has_outer_outline:
        _first_outer = True
        for xs, ys in _shapely_to_arrays(outer_outline):
            ax.plot(xs, ys, color="#444444", linewidth=1.2, linestyle="--",
                    zorder=6,
                    label="Container frame" if _first_outer else None)
            _first_outer = False

    # --- draw inner-wall inset line (red, debugging) --------------------------
    # The inset line is the outer outline eroded inward by the inner-wall
    # inset distance; SC pads that cross it are flagged as inner walls.
    _has_inset_line = (inset_line is not None and not inset_line.is_empty)
    if _has_inset_line:
        _first_inset = True
        inset_geoms = (list(inset_line.geoms)
                       if hasattr(inset_line, "geoms") else [inset_line])
        for g in inset_geoms:
            if hasattr(g, "exterior"):
                xs, ys = g.exterior.xy
            else:
                xs, ys = g.xy
            ax.plot(xs, ys, color="red", linewidth=1.5, linestyle="-",
                    zorder=6,
                    label="Inner-wall inset line" if _first_inset else None)
            _first_inset = False

    # --- draw interposer outer / inner border outlines (dashed) ---------------
    # Drawn with _rings_to_arrays so a frame-shaped (donut) outline strokes
    # both its outer and inner rings — the container-frame interposer outline.
    _has_inp_outer = (interposer_outer_outline is not None
                      and not interposer_outer_outline.is_empty)
    if _has_inp_outer:
        _first = True
        for xs, ys in _rings_to_arrays(interposer_outer_outline):
            ax.plot(xs, ys, color="black", linewidth=1.5, linestyle="--",
                    zorder=6,
                    label="Interposer outline" if _first else None)
            _first = False

    _has_inp_inner = (interposer_inner_outline is not None
                      and not interposer_inner_outline.is_empty)
    if _has_inp_inner:
        _first = True
        for xs, ys in _rings_to_arrays(interposer_inner_outline):
            ax.plot(xs, ys, color="black", linewidth=1.5, linestyle="--",
                    zorder=6,
                    label="Interposer inner outline" if _first else None)
            _first = False

    # --- draw inner wall pads (orange/red to distinguish from perimeter) ------
    if inner_walls:
        first = True
        for wall in inner_walls:
            geoms = list(wall.geoms) if hasattr(wall, "geoms") else [wall]
            for g in geoms:
                lbl = "Inner wall pad" if first else None
                if g.geom_type == "Polygon":
                    xs, ys = g.exterior.xy
                    ax.fill(xs, ys, color="#FF6600", alpha=0.65, zorder=5,
                            label=lbl)
                    ax.plot(xs, ys, color="#CC4400", linewidth=1.5,
                            zorder=5)
                else:
                    coords = list(g.coords)
                    xs = [c[0] for c in coords]
                    ys = [c[1] for c in coords]
                    ax.plot(xs, ys, color="#FF6600", linewidth=4,
                            solid_capstyle="round", zorder=5, label=lbl)
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
        # When annotate_pass is False, PASS items show colour only (no tag).
        if is_pass and not annotate_pass:
            continue
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
    # Edge (review line) legend entry — disabled with the overlay above.
    # if _has_edge_segs:
    #     legend_elements.append(
    #         plt.Line2D([0], [0], color="red", linewidth=2.0,
    #                    linestyle="--", label="Edge (review line)")
    #     )
    if _has_outer_outline:
        legend_elements.append(
            plt.Line2D([0], [0], color="#444444", linewidth=1.2,
                       linestyle="--", label="Container frame")
        )
    if _has_inset_line:
        legend_elements.append(
            plt.Line2D([0], [0], color="red", linewidth=1.5,
                       label="Inner-wall inset line")
        )
    if _has_inp_outer:
        legend_elements.append(
            plt.Line2D([0], [0], color="black", linewidth=1.5,
                       linestyle="--", label="Interposer outline")
        )
    if _has_inp_inner:
        legend_elements.append(
            plt.Line2D([0], [0], color="black", linewidth=1.5,
                       linestyle="--", label="Interposer inner outline")
        )
    if inner_walls:
        legend_elements.append(
            mpatches.Patch(facecolor="#FF6600", edgecolor="#CC4400",
                           alpha=0.65, label="Inner wall pad")
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
