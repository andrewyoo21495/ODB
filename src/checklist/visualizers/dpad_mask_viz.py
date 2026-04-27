"""Visualization for CKL-02-005 D-pad capacitor checks.

Produces one image per board side (Top/Bottom) showing the SMT or SMB
solder-mask layer as the background, with all evaluated D-pad list
capacitors drawn over it — green for PASS, red for FAIL — and the
Shield Can / Interposer "inside regions" (convex hulls of their
pad/outline points) drawn faintly behind for context.

For Bottom-side images, the X axis is flipped to match the convention
used by the interactive viewer (``render_layer(flip_x=True)``).  Both
the SMB layer features and the overlaid cap/container geometries are
mirrored about ``x=0`` so they remain visually aligned.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon as MplPolygon
import numpy as np

from shapely.affinity import scale as shapely_scale

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


def _flip_geom(geom, flip: bool):
    """Return *geom* mirrored about x=0 when *flip* is True."""
    if not flip or geom is None or geom.is_empty:
        return geom
    return shapely_scale(geom, xfact=-1, yfact=1, origin=(0, 0))


def _flip_x(x: float, flip: bool) -> float:
    return -x if flip else x


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
    """Return a LayerFeatures with only features near *bbox* (in native coords)."""
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
        When True, apply an X-axis mirror to the layer features (via
        ``render_layer(flip_x=True)``) and to all overlaid geometries so
        the bottom side reads correctly (matching the interactive viewer).
    """
    # 1) Resolve geometries in NATIVE board coordinates.  These are used
    #    both for filtering mask features and as the basis for the
    #    optional X-mirror applied for display.
    cont_hulls_native:  list[tuple] = []  # (Component, hull_geom)
    cont_frames_native: list[tuple] = []
    for cont in containers:
        hull = _resolve_footprint(cont, packages, is_bottom=is_bottom)
        if hull is not None and not hull.is_empty:
            cont_hulls_native.append((cont, hull))
        frame = _resolve_outline(cont, packages, is_bottom=is_bottom)
        if frame is not None and not frame.is_empty:
            cont_frames_native.append((cont, frame))

    cap_geoms_native: list[tuple[dict, object]] = []
    for item in cap_items:
        fp = _resolve_footprint(item["cap"], packages, is_bottom=is_bottom)
        if fp is not None and not fp.is_empty:
            cap_geoms_native.append((item, fp))

    # 2) Native bbox covering all evaluated geometries — used to filter the
    #    raw mask features before render_layer applies its own X-flip.
    native_geoms = [g for _, g in cap_geoms_native]
    native_geoms += [h for _, h in cont_hulls_native]
    if not native_geoms:
        return output_path
    n_minx = min(g.bounds[0] for g in native_geoms) - margin
    n_miny = min(g.bounds[1] for g in native_geoms) - margin
    n_maxx = max(g.bounds[2] for g in native_geoms) + margin
    n_maxy = max(g.bounds[3] for g in native_geoms) + margin

    # 3) Display bbox (after optional X-mirror) — used for ax limits.
    if is_bottom:
        d_minx, d_maxx = -n_maxx, -n_minx
    else:
        d_minx, d_maxx = n_minx, n_maxx
    d_miny, d_maxy = n_miny, n_maxy

    fig_w = max(8.0, min(16.0, (d_maxx - d_minx) * 0.5 + 4))
    fig_h = max(8.0, min(16.0, (d_maxy - d_miny) * 0.5 + 4))
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

    # 4) Background: solder-mask features within native bbox, drawn with
    #    flip_x=is_bottom so the bottom side mirrors correctly.
    if mask_lf is not None:
        local = _filter_features(mask_lf, (n_minx, n_miny, n_maxx, n_maxy))
        if local.features:
            render_layer(
                ax, local,
                color="#00AA00", layer_type="SOLDER_MASK", alpha=0.35,
                user_symbols=user_symbols, font=font,
                flip_x=is_bottom,
            )

    # 5) Overlays — flip the geometries here too when bottom-side, so they
    #    align with the mirrored layer features.
    for cont, hull in cont_hulls_native:
        _draw_geom(
            ax, _flip_geom(hull, is_bottom),
            facecolor="#B0C4DE", edgecolor="steelblue",
            alpha=0.18, linewidth=1.0,
        )

    for cont, frame in cont_frames_native:
        d_frame = _flip_geom(frame, is_bottom)
        first = True
        for xs, ys in _shapely_to_arrays(d_frame):
            ax.plot(
                xs, ys,
                color="#444444", linewidth=1.2, linestyle="--",
                zorder=3,
                label=("Container frame" if first else None),
            )
            first = False
        try:
            cx, cy = d_frame.centroid.x, d_frame.centroid.y
            ax.text(cx, cy, cont.comp_name,
                    fontsize=7, color="#222222",
                    ha="center", va="center",
                    alpha=0.8, zorder=4,
                    bbox=dict(boxstyle="round,pad=0.2",
                              facecolor="white", edgecolor="#888888",
                              alpha=0.7))
        except Exception:
            pass

    for item, fp in cap_geoms_native:
        cap   = item["cap"]
        fail  = (item["status"] == "FAIL")
        edge  = "darkred" if fail else "darkgreen"
        fill  = "#FFB0B0" if fail else "#90EE90"
        _draw_geom(
            ax, _flip_geom(fp, is_bottom),
            facecolor=fill, edgecolor=edge,
            alpha=0.7, linewidth=1.4, zorder=5,
        )
        label = f"{cap.comp_name}\n{item['location']}/{item['status']}"
        ax.annotate(
            label,
            (_flip_x(cap.x, is_bottom), cap.y),
            textcoords="offset points", xytext=(8, 8),
            fontsize=6, color=edge,
            bbox=dict(boxstyle="round,pad=0.2",
                      facecolor="white", edgecolor=edge, alpha=0.85),
            arrowprops=dict(arrowstyle="-", color=edge, lw=0.6),
            zorder=6,
        )

    # 6) Viewport
    ax.set_xlim(d_minx, d_maxx)
    ax.set_ylim(d_miny, d_maxy)

    # 7) Legend
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
    ax.set_xlabel("X (mm)" + ("  [mirrored]" if is_bottom else ""))
    ax.set_ylabel("Y (mm)")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path
