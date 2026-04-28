"""Visualization for CKL-02-005 D-pad capacitor checks.

Produces one image per board side (Top/Bottom) showing the SMT or SMB
solder-mask layer as the background, with all evaluated D-pad list
capacitors drawn over it — green for PASS, red for FAIL — and the
Shield Can / Interposer "inside regions" (convex hulls of their
pad/outline points) drawn faintly behind for context.

Coordinate convention
---------------------
ODB++ stores ALL layer features (top and bottom) in the same absolute
top-view board coordinate system.  ``_resolve_footprint(is_bottom=True)``
returns geometries in this same coordinate system (the package mirror is
applied around the component centroid, not the board origin).  Therefore
no coordinate transformation is needed to align layer features with cap /
container footprints — both are already in native board coords.

The mask layer is rendered at native board coordinates (``flip_x=False``)
for both Top and Bottom side so that it stays aligned with the component
footprint overlays.
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
    _resolve_footprint,
    _resolve_outline,
)
from src.models import (
    ArcRecord, BarcodeRecord, LayerFeatures, LineRecord,
    PadRecord, SurfaceRecord, TextRecord,
)
from src.visualizer.layer_renderer import render_layer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shapely_to_arrays(geom):
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        xs, ys = geom.exterior.xy
        yield np.array(xs), np.array(ys)
    elif geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        for part in geom.geoms:
            yield from _shapely_to_arrays(part)


def _draw_geom(ax, geom, **kw):
    for xs, ys in _shapely_to_arrays(geom):
        verts = list(zip(xs, ys))
        ax.add_patch(MplPolygon(verts, closed=True, **kw))


def _feature_in_bbox(feat, bbox) -> bool:
    minx, miny, maxx, maxy = bbox
    if isinstance(feat, PadRecord):
        return minx <= feat.x <= maxx and miny <= feat.y <= maxy
    if isinstance(feat, (LineRecord, ArcRecord)):
        return any(
            minx <= x <= maxx and miny <= y <= maxy
            for x, y in ((feat.xs, feat.ys), (feat.xe, feat.ye))
        )
    if isinstance(feat, (TextRecord, BarcodeRecord)):
        return minx <= feat.x <= maxx and miny <= feat.y <= maxy
    if isinstance(feat, SurfaceRecord):
        for contour in feat.contours:
            x, y = contour.start.x, contour.start.y
            if minx <= x <= maxx and miny <= y <= maxy:
                return True
        return False
    return False


def _filter_features(features: LayerFeatures, bbox) -> LayerFeatures:
    """Return a LayerFeatures with only features near *bbox* (board coordinates)."""
    return LayerFeatures(
        units=features.units,
        id=features.id,
        feature_count=features.feature_count,
        symbols=features.symbols,
        attr_names=features.attr_names,
        attr_texts=features.attr_texts,
        features=[f for f in features.features if _feature_in_bbox(f, bbox)],
    )


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_dpad_side_image(
    cap_items: list[dict],
    containers: list,
    packages,
    mask_lf: LayerFeatures | None,
    mask_layer_name: str,
    output_path: Path,
    *,
    rule_id: str,
    layer_name: str,
    is_bottom: bool,
    user_symbols: dict | None = None,
    font=None,
    margin: float = 2.0,
) -> Path:
    """Render one side's D-pad evaluation as a single PNG.

    Parameters
    ----------
    cap_items : list[dict]
        One entry per evaluated capacitor on this side. Each dict must have:
          - "cap":      Component
          - "status":   "PASS" or "FAIL"
          - "location": "INSIDE" or "OUTSIDE"
        Optional:
          - "host":     Component (the container this cap sits inside)
    containers : list[Component]
        All Shield Cans / Interposers on this side (used for context overlay).
    mask_lf : LayerFeatures | None
        Solder-mask features for the same side as the caps.
    mask_layer_name : str
        Layer name shown in title / legend (e.g. "smt", "smb").
    is_bottom : bool
        When True, the X axis is reversed after drawing (``ax.invert_xaxis()``)
        to produce a "view from below" without shifting any coordinates.
        All geometries — layer features and cap/container footprints — are
        already in the same top-view board coordinate system and require no
        additional transformation.
    """
    # Resolve geometries (all in top-view board coordinates).
    cont_hulls:  list[tuple] = []   # (Component, convex-hull polygon)
    cont_frames: list[tuple] = []   # (Component, outline polygon)
    for cont in containers:
        hull = _resolve_footprint(cont, packages, is_bottom=is_bottom)
        if hull is not None and not hull.is_empty:
            cont_hulls.append((cont, hull))
        frame = _resolve_outline(cont, packages, is_bottom=is_bottom)
        if frame is not None and not frame.is_empty:
            cont_frames.append((cont, frame))

    cap_geoms: list[tuple[dict, object]] = []
    for item in cap_items:
        fp = _resolve_footprint(item["cap"], packages, is_bottom=is_bottom)
        if fp is not None and not fp.is_empty:
            cap_geoms.append((item, fp))

    # Viewport bbox in board coordinates (same space as all geometries).
    all_geoms = [g for _, g in cap_geoms] + [h for _, h in cont_hulls]
    if not all_geoms:
        return output_path
    minx = min(g.bounds[0] for g in all_geoms) - margin
    miny = min(g.bounds[1] for g in all_geoms) - margin
    maxx = max(g.bounds[2] for g in all_geoms) + margin
    maxy = max(g.bounds[3] for g in all_geoms) + margin

    fig_w = max(8.0, min(16.0, (maxx - minx) * 0.5 + 4))
    fig_h = max(8.0, min(16.0, (maxy - miny) * 0.5 + 4))
    fig, ax = plt.subplots(1, 1, figsize=(fig_w, fig_h))
    ax.set_facecolor("white")
    ax.set_aspect("equal")

    n_pass = sum(1 for it in cap_items if it["status"] == "PASS")
    n_fail = sum(1 for it in cap_items if it["status"] == "FAIL")
    overall = "FAIL" if n_fail else ("PASS" if n_pass else "N/A")
    ax.set_title(
        f"{rule_id}  —  {mask_layer_name} ({layer_name})\n"
        f"D-pad caps:  PASS={n_pass}  FAIL={n_fail}   overall=[{overall}]",
        fontsize=11, fontweight="bold",
    )

    # Background: solder-mask features near the viewport.
    # Rendered at native board coordinates (flip_x=False) so they stay
    # aligned with the cap and container footprint overlays.
    if mask_lf is not None:
        local = _filter_features(mask_lf, (minx, miny, maxx, maxy))
        if local.features:
            render_layer(
                ax, local,
                color="#00AA00", layer_type="SOLDER_MASK", alpha=0.35,
                user_symbols=user_symbols, font=font,
                flip_x=False,
            )

    # Container "inside regions" (convex hull, faint blue fill).
    for cont, hull in cont_hulls:
        _draw_geom(
            ax, hull,
            facecolor="#B0C4DE", edgecolor="steelblue",
            alpha=0.18, linewidth=1.0,
        )

    # Container frame outlines (dashed grey).
    for cont, frame in cont_frames:
        first = True
        for xs, ys in _shapely_to_arrays(frame):
            ax.plot(
                xs, ys,
                color="#444444", linewidth=1.2, linestyle="--",
                zorder=3,
                label=("Container frame" if first else None),
            )
            first = False
        try:
            cx, cy = frame.centroid.x, frame.centroid.y
            ax.text(cx, cy, cont.comp_name,
                    fontsize=7, color="#222222",
                    ha="center", va="center",
                    alpha=0.8, zorder=4,
                    bbox=dict(boxstyle="round,pad=0.2",
                              facecolor="white", edgecolor="#888888",
                              alpha=0.7))
        except Exception:
            pass

    # Capacitors coloured by PASS/FAIL.
    for item, fp in cap_geoms:
        cap  = item["cap"]
        fail = (item["status"] == "FAIL")
        edge = "darkred" if fail else "darkgreen"
        fill = "#FFB0B0" if fail else "#90EE90"
        _draw_geom(
            ax, fp,
            facecolor=fill, edgecolor=edge,
            alpha=0.7, linewidth=1.4, zorder=5,
        )
        label = f"{cap.comp_name}\n{item['location']}/{item['status']}"
        ax.annotate(
            label,
            (cap.x, cap.y),
            textcoords="offset points", xytext=(8, 8),
            fontsize=6, color=edge,
            bbox=dict(boxstyle="round,pad=0.2",
                      facecolor="white", edgecolor=edge, alpha=0.85),
            arrowprops=dict(arrowstyle="-", color=edge, lw=0.6),
            zorder=6,
        )

    # Viewport — native board coordinates, no axis inversion.
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)

    # Legend.
    legend_elements = [
        mpatches.Patch(facecolor="#00AA00", alpha=0.35,
                       label=f"{mask_layer_name} (solder mask)"),
        mpatches.Patch(facecolor="#B0C4DE", edgecolor="steelblue",
                       alpha=0.5,
                       label="Container inside region (convex hull)"),
        plt.Line2D([0], [0], color="#444444", linewidth=1.2,
                   linestyle="--", label="Container frame"),
        mpatches.Patch(facecolor="#90EE90", edgecolor="darkgreen",
                       alpha=0.7, label="Cap PASS"),
        mpatches.Patch(facecolor="#FFB0B0", edgecolor="darkred",
                       alpha=0.7, label="Cap FAIL"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", fontsize=8)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path
