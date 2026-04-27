"""Visualization for CKL-02-005 D-pad capacitor checks.

Renders the SMT (top) or SMB (bottom) solder-mask layer features as the
background near the target capacitor, with the capacitor footprint and the
optional Shield Can / Interposer outline overlaid.  Used to visually confirm
whether the D-pad / regular pad opening is correctly applied for each cap.
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
    """Return a LayerFeatures with only features overlapping *bbox*."""
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

def render_dpad_mask_image(
    cap,
    container,
    packages,
    mask_lf: LayerFeatures | None,
    mask_layer_name: str,
    output_path: Path,
    *,
    rule_id: str,
    layer_name: str,
    is_bottom: bool,
    location: str,            # "INSIDE" or "OUTSIDE"
    expected_pkg: str,
    actual_pkg: str,
    status: str,              # "PASS" or "FAIL"
    user_symbols: dict | None = None,
    font=None,
    margin: float = 1.5,
) -> Path:
    """Render one capacitor on top of the SMT/SMB solder-mask layer.

    Parameters
    ----------
    cap : Component
        The capacitor under evaluation.
    container : Component | None
        The Shield Can / Interposer that hosts *cap* (None if outside).
    packages : list[Package]
    mask_lf : LayerFeatures | None
        Solder-mask layer features for the same side as *cap*.  When None,
        only the geometric overlay (cap + container) is drawn.
    mask_layer_name : str
        Layer name shown in the title / legend (e.g. "smt", "smb").
    margin : float
        Extra space (mm) around the cap+container bbox.
    """
    cap_outline = _resolve_outline(cap, packages, is_bottom=is_bottom)
    cap_fp      = _resolve_footprint(cap, packages, is_bottom=is_bottom)
    cap_display = cap_fp or cap_outline
    if cap_display is None or cap_display.is_empty:
        return output_path

    cont_outline = None
    if container is not None:
        cont_outline = _resolve_outline(container, packages, is_bottom=is_bottom)

    # Build viewport bbox covering cap and (optional) container.
    geoms = [g for g in (cap_display, cont_outline)
             if g is not None and not g.is_empty]
    minx = min(g.bounds[0] for g in geoms) - margin
    miny = min(g.bounds[1] for g in geoms) - margin
    maxx = max(g.bounds[2] for g in geoms) + margin
    maxy = max(g.bounds[3] for g in geoms) + margin

    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    ax.set_facecolor("white")
    ax.set_aspect("equal")

    title = (
        f"{cap.comp_name} ({cap.part_name or ''})  —  "
        f"{mask_layer_name} ({layer_name})\n"
        f"{rule_id}: D-pad / regular pad on solder mask  [{status}]"
    )
    ax.set_title(title, fontsize=11, fontweight="bold")

    # --- background: solder-mask features in viewport ----------------------
    if mask_lf is not None:
        local = _filter_features(mask_lf, (minx, miny, maxx, maxy))
        if local.features:
            render_layer(
                ax, local,
                color="#00AA00", layer_type="SOLDER_MASK", alpha=0.45,
                user_symbols=user_symbols, font=font,
            )

    # --- container outline (dashed grey) -----------------------------------
    if cont_outline is not None and not cont_outline.is_empty:
        first = True
        for xs, ys in _shapely_to_arrays(cont_outline):
            ax.plot(
                xs, ys,
                color="#444444", linewidth=1.5, linestyle="--",
                label=("Container outline" if first else None),
                zorder=4,
            )
            first = False

    # --- capacitor footprint (PASS green / FAIL red) -----------------------
    fail = (status == "FAIL")
    edge = "darkred" if fail else "darkgreen"
    fill = "#FFB0B0" if fail else "#90EE90"
    _draw_geom(
        ax, cap_display,
        facecolor=fill, edgecolor=edge,
        alpha=0.55, linewidth=1.6,
    )
    ax.plot(cap.x, cap.y, "s", color=edge, markersize=7,
            markeredgewidth=1.5, zorder=5)

    # --- info text (location + expected vs actual pkg) ---------------------
    info_lines = [
        f"location:     {location}",
        f"expected pkg: {expected_pkg}",
        f"actual pkg:   {actual_pkg}",
    ]
    ax.text(
        0.02, 0.02, "\n".join(info_lines),
        transform=ax.transAxes,
        fontsize=9, family="monospace",
        verticalalignment="bottom",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                  edgecolor=edge, alpha=0.9),
        zorder=6,
    )

    # --- viewport ----------------------------------------------------------
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)

    # --- legend ------------------------------------------------------------
    legend_elements = [
        mpatches.Patch(facecolor="#00AA00", alpha=0.45,
                       label=f"{mask_layer_name} (solder mask)"),
        mpatches.Patch(facecolor=fill, edgecolor=edge, alpha=0.55,
                       label=f"Capacitor [{status}]"),
    ]
    if cont_outline is not None and not cont_outline.is_empty:
        legend_elements.append(
            plt.Line2D([0], [0], color="#444444", linewidth=1.5,
                       linestyle="--",
                       label=f"Container ({container.comp_name})")
        )
    ax.legend(handles=legend_elements, loc="upper left", fontsize=8)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path
