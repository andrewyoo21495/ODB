"""Debug script for CKL-03-015: PCB outline clearance (pad-based).

Visualises the board outline, the 0.65mm inset boundary, and flagged
component pads on Top and Bottom layers.  Produces:

  - debug_clearance_images/overview_top.png   — full-board view, Top layer
  - debug_clearance_images/overview_bot.png   — full-board view, Bottom layer
  - debug_clearance_images/TOP_<comp>.png     — zoomed per-component, Top
  - debug_clearance_images/BOT_<comp>.png     — zoomed per-component, Bottom

Pads in the clearance zone are shown in red; safe pads in green.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon as MplPolygon
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from main import _load_from_cache
from src.checklist.geometry_utils import (
    build_board_polygon,
    build_inset_boundary,
    components_with_pads_in_clearance_zone,
    _get_pad_union,
)
from src.models import Component, Package

_CLEARANCE_MM = 0.65
_EXCLUDED_PREFIXES = ("ANT", "CN", "TP")


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
        # buffer to make visible
        yield from _shapely_to_arrays(geom.buffer(0.05))
    elif geom.geom_type in ("LineString", "MultiLineString"):
        yield from _shapely_to_arrays(geom.buffer(0.01))


def _draw_board_and_inset(ax, board_poly, inset_poly):
    """Draw board outline (blue) and inset boundary (orange dashed)."""
    for xs, ys in _shapely_to_arrays(board_poly):
        ax.plot(xs, ys, color="royalblue", linewidth=1.2, label="Board outline")
        ax.fill(xs, ys, alpha=0.04, color="royalblue")

    for xs, ys in _shapely_to_arrays(inset_poly):
        ax.plot(xs, ys, color="orange", linewidth=0.8, linestyle="--",
                label=f"Inset ({_CLEARANCE_MM}mm)")


def _draw_pad_geom(ax, pad_geom, color, edge_color, alpha=0.45, label=None):
    """Fill a Shapely pad geometry on *ax*."""
    for xs, ys in _shapely_to_arrays(pad_geom):
        verts = list(zip(xs, ys))
        ax.add_patch(MplPolygon(verts, closed=True, facecolor=color,
                                edgecolor=edge_color, alpha=alpha,
                                linewidth=0.8, label=label))
        label = None  # only label the first patch


# ---------------------------------------------------------------------------
# Overview (full-board) image
# ---------------------------------------------------------------------------

def draw_overview(board_poly, inset_poly, components, packages,
                  violations_set, layer_name, output_path):
    """Draw full-board overview with all pads colour-coded."""
    fig, ax = plt.subplots(1, 1, figsize=(14, 10))
    ax.set_title(f"CKL-03-015 Pad Clearance — {layer_name} Layer",
                 fontsize=13, fontweight="bold")
    ax.set_aspect("equal")

    _draw_board_and_inset(ax, board_poly, inset_poly)

    violation_names = {c.comp_name for c, _ in violations_set}

    # Draw all component pads
    for comp in components:
        pad_geom = _get_pad_union(comp, packages) if packages else None
        if pad_geom is None:
            continue

        is_violation = comp.comp_name in violation_names
        color = "#FF6060" if is_violation else "#60CC60"
        edge = "darkred" if is_violation else "darkgreen"
        _draw_pad_geom(ax, pad_geom, color, edge, alpha=0.4)

        if is_violation:
            # Find the distance for this component
            dist = next(
                (d for c, d in violations_set if c.comp_name == comp.comp_name),
                None,
            )
            centroid = pad_geom.centroid
            ax.annotate(
                f"{comp.comp_name}\n{dist:.3f}mm",
                (centroid.x, centroid.y),
                textcoords="offset points", xytext=(8, 8),
                fontsize=6, color="darkred",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                          edgecolor="darkred", alpha=0.85),
                arrowprops=dict(arrowstyle="->", color="darkred", lw=0.6),
            )

    # Legend
    legend_elements = [
        mpatches.Patch(facecolor="#FF6060", edgecolor="darkred", alpha=0.5,
                       label=f"Pad in clearance zone (<{_CLEARANCE_MM}mm)"),
        mpatches.Patch(facecolor="#60CC60", edgecolor="darkgreen", alpha=0.5,
                       label="Pad OK"),
        plt.Line2D([], [], color="royalblue", linewidth=1.2,
                   label="Board outline"),
        plt.Line2D([], [], color="orange", linewidth=0.8, linestyle="--",
                   label=f"Inset boundary ({_CLEARANCE_MM}mm)"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", fontsize=8)

    bounds = board_poly.bounds
    margin = 2.0
    ax.set_xlim(bounds[0] - margin, bounds[2] + margin)
    ax.set_ylim(bounds[1] - margin, bounds[3] + margin)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> Saved overview: {output_path}")


# ---------------------------------------------------------------------------
# Per-component zoomed image
# ---------------------------------------------------------------------------

def draw_component_detail(comp, packages, board_poly, inset_poly,
                          dist, output_path):
    """Draw a zoomed view of a single flagged component's pads."""
    pad_geom = _get_pad_union(comp, packages) if packages else None
    if pad_geom is None:
        return

    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    ax.set_title(
        f"{comp.comp_name}  (part={comp.part_name})\n"
        f"Min pad-to-outline distance: {dist:.3f} mm",
        fontsize=11, fontweight="bold",
    )
    ax.set_aspect("equal")

    # Board outline and inset
    _draw_board_and_inset(ax, board_poly, inset_poly)

    # Clearance zone fill (between board and inset)
    clearance_zone = board_poly.difference(inset_poly)
    for xs, ys in _shapely_to_arrays(clearance_zone):
        ax.fill(xs, ys, alpha=0.12, color="red")

    # The component's pads — red fill
    _draw_pad_geom(ax, pad_geom, "#FF6060", "darkred", alpha=0.55,
                   label="Pad geometry")

    # Component centre marker
    ax.plot(comp.x, comp.y, "x", color="blue", markersize=10,
            markeredgewidth=2, label="Comp centre")

    # Individual toeprint dots
    if comp.toeprints:
        for tp in comp.toeprints:
            ax.plot(tp.x, tp.y, ".", color="magenta", markersize=4)

    # Zoom to pad extent with margin
    pad_bounds = pad_geom.bounds  # (minx, miny, maxx, maxy)
    span_x = pad_bounds[2] - pad_bounds[0]
    span_y = pad_bounds[3] - pad_bounds[1]
    span = max(span_x, span_y, 1.0)
    cx = (pad_bounds[0] + pad_bounds[2]) / 2
    cy = (pad_bounds[1] + pad_bounds[3]) / 2
    margin = span * 0.8
    ax.set_xlim(cx - span / 2 - margin, cx + span / 2 + margin)
    ax.set_ylim(cy - span / 2 - margin, cy + span / 2 + margin)

    legend_elements = [
        mpatches.Patch(facecolor="#FF6060", edgecolor="darkred", alpha=0.55,
                       label="Pad geometry"),
        mpatches.Patch(facecolor="red", alpha=0.12,
                       label="Clearance zone"),
        plt.Line2D([], [], color="royalblue", linewidth=1.2,
                   label="Board outline"),
        plt.Line2D([], [], color="orange", linewidth=0.8, linestyle="--",
                   label=f"Inset ({_CLEARANCE_MM}mm)"),
        plt.Line2D([], [], marker="x", color="blue", linestyle="None",
                   markersize=8, label="Comp centre"),
        plt.Line2D([], [], marker=".", color="magenta", linestyle="None",
                   markersize=5, label="Toeprints"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", fontsize=8)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> Saved detail: {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("CKL-03-015 DEBUG: PCB Outline Pad Clearance")
    print("=" * 70)

    cache_name = sys.argv[1] if len(sys.argv) > 1 else "designodb_rigidflex"
    data = _load_from_cache(Path("cache"), cache_name)

    components_top = data.get("components_top", [])
    components_bot = data.get("components_bot", [])
    profile = data.get("profile")
    eda = data.get("eda_data")
    packages = eda.packages if eda else []

    print(f"Loaded: {len(components_top)} top, {len(components_bot)} bottom, "
          f"{len(packages)} packages")

    board_poly = build_board_polygon(profile)
    if board_poly is None:
        print("ERROR: Could not build board polygon.")
        return

    inset_poly = build_inset_boundary(board_poly, _CLEARANCE_MM)
    if inset_poly is None:
        print("ERROR: Could not build inset boundary.")
        return

    bounds = board_poly.bounds
    print(f"Board bounds: ({bounds[0]:.2f}, {bounds[1]:.2f}) - "
          f"({bounds[2]:.2f}, {bounds[3]:.2f})")

    out_dir = Path("debug_clearance_images")
    out_dir.mkdir(exist_ok=True)

    for comps, layer_name in [
        (components_top, "Top"),
        (components_bot, "Bottom"),
    ]:
        print(f"\n{'=' * 50}")
        print(f"Layer: {layer_name}  ({len(comps)} components)")
        print("=" * 50)

        violations = components_with_pads_in_clearance_zone(
            comps, board_poly, inset_poly, packages,
        )

        fail_list = [
            (c, d) for c, d in violations
            if d < _CLEARANCE_MM and not c.comp_name.startswith(_EXCLUDED_PREFIXES)
        ]
        print(f"  Violations (pad in clearance zone): {len(fail_list)}")
        for comp, dist in fail_list:
            print(f"    {comp.comp_name:15s}  part={comp.part_name or '?':20s}  "
                  f"dist={dist:.3f} mm")

        # Overview image
        tag = layer_name.lower()[:3]
        draw_overview(
            board_poly, inset_poly, comps, packages,
            fail_list, layer_name,
            out_dir / f"overview_{tag}.png",
        )

        # Per-component detail images
        for comp, dist in fail_list:
            safe = comp.comp_name.replace("/", "_")
            draw_component_detail(
                comp, packages, board_poly, inset_poly, dist,
                out_dir / f"{tag.upper()}_{safe}.png",
            )

    print(f"\nAll images saved to: {out_dir}/")


if __name__ == "__main__":
    main()
