"""Test script for bending-vulnerable area detection.

Loads the sample rigid-flex ODB data, builds the board polygon,
runs the morphological-opening algorithm, and produces a diagnostic
visualisation image showing:
  - Original board outline (blue)
  - Opened (main body) outline (green dashed)
  - Detected bending-vulnerable areas (red filled)

Output: debug_bending_vulnerable.png
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
    find_bending_vulnerable_areas,
)


def main():
    # ------------------------------------------------------------------
    # 1. Load data from cache
    # ------------------------------------------------------------------
    cache_name = sys.argv[1] if len(sys.argv) > 1 else "designodb_rigidflex"
    cache_dir = Path("cache")
    print(f"Using cache: {cache_name}")
    data = _load_from_cache(cache_dir, cache_name)
    profile = data.get("profile")
    if profile is None:
        print("ERROR: No profile found in cache.")
        return

    # ------------------------------------------------------------------
    # 2. Build board polygon
    # ------------------------------------------------------------------
    board_poly = build_board_polygon(profile)
    if board_poly is None:
        print("ERROR: Could not build board polygon.")
        return

    bounds = board_poly.bounds  # (minx, miny, maxx, maxy)
    board_w = bounds[2] - bounds[0]
    board_h = bounds[3] - bounds[1]
    print(f"Board bounding box: {bounds}")
    print(f"Board size: {board_w:.2f} x {board_h:.2f} mm")
    print(f"Board area: {board_poly.area:.2f} mm²")

    # ------------------------------------------------------------------
    # 3. Run bending-vulnerable area detection
    # ------------------------------------------------------------------
    WIDTH_THRESHOLD = 8.0   # mm
    PROTRUSION_DEPTH = 2.0  # mm

    vulnerable_areas = find_bending_vulnerable_areas(
        board_poly,
        width_threshold=WIDTH_THRESHOLD,
        protrusion_depth=PROTRUSION_DEPTH,
    )

    print(f"\n--- Bending-Vulnerable Area Detection ---")
    print(f"Width threshold:    ≤ {WIDTH_THRESHOLD} mm")
    print(f"Protrusion depth:   ≥ {PROTRUSION_DEPTH} mm")
    print(f"Vulnerable areas found: {len(vulnerable_areas)}")

    for i, area in enumerate(vulnerable_areas):
        b = area.bounds
        area_w = b[2] - b[0]
        area_h = b[3] - b[1]
        print(f"  Area {i+1}: bounds=({b[0]:.2f}, {b[1]:.2f}, {b[2]:.2f}, {b[3]:.2f}), "
              f"size={area_w:.2f}x{area_h:.2f} mm, area={area.area:.2f} mm²")

    # ------------------------------------------------------------------
    # 4. Also show intermediate results for debugging
    # ------------------------------------------------------------------
    half_w = WIDTH_THRESHOLD / 2.0
    eroded = board_poly.buffer(-half_w)
    opened = eroded.buffer(half_w)
    all_protrusions = board_poly.difference(opened)

    print(f"\nIntermediate results:")
    print(f"  Eroded polygon empty? {eroded.is_empty}")
    if not eroded.is_empty:
        print(f"  Eroded area: {eroded.area:.2f} mm²")
    print(f"  Opened area: {opened.area:.2f} mm²")
    print(f"  Protrusion area (before depth filter): {all_protrusions.area:.2f} mm²")

    # ------------------------------------------------------------------
    # 5. Visualise
    # ------------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(18, 8))

    # --- Left: overview with all intermediate steps ---
    ax = axes[0]
    ax.set_title("Morphological Opening Steps", fontsize=12, fontweight="bold")
    ax.set_aspect("equal")

    # Board outline
    bx, by = board_poly.exterior.xy
    ax.plot(bx, by, color="royalblue", linewidth=1.5, label="Board outline")
    ax.fill(bx, by, alpha=0.08, color="royalblue")

    # Opened polygon
    if not opened.is_empty:
        if opened.geom_type == "MultiPolygon":
            for geom in opened.geoms:
                ox, oy = geom.exterior.xy
                ax.plot(ox, oy, color="green", linewidth=1.2, linestyle="--",
                        label="Opened (main body)")
        else:
            ox, oy = opened.exterior.xy
            ax.plot(ox, oy, color="green", linewidth=1.2, linestyle="--",
                    label="Opened (main body)")

    # Eroded polygon
    if not eroded.is_empty:
        if eroded.geom_type == "MultiPolygon":
            for geom in eroded.geoms:
                ex, ey = geom.exterior.xy
                ax.plot(ex, ey, color="orange", linewidth=1.0, linestyle=":",
                        label="Eroded (−4mm)")
        else:
            ex, ey = eroded.exterior.xy
            ax.plot(ex, ey, color="orange", linewidth=1.0, linestyle=":",
                    label="Eroded (−4mm)")

    # All protrusion regions (before depth filter) – light red
    if not all_protrusions.is_empty:
        parts = (list(all_protrusions.geoms)
                 if all_protrusions.geom_type in ("MultiPolygon", "GeometryCollection")
                 else [all_protrusions])
        for p in parts:
            if hasattr(p, "exterior"):
                px, py = p.exterior.xy
                ax.fill(px, py, alpha=0.25, color="salmon",
                        label="Narrow region (all)")

    # Bending-vulnerable areas – solid red
    for area in vulnerable_areas:
        vx, vy = area.exterior.xy
        ax.fill(vx, vy, alpha=0.5, color="red", label="Bending-vulnerable")
        ax.plot(vx, vy, color="darkred", linewidth=1.5)

    # Deduplicate legend
    handles, labels = ax.get_legend_handles_labels()
    seen = {}
    unique_handles, unique_labels = [], []
    for h, l in zip(handles, labels):
        if l not in seen:
            seen[l] = True
            unique_handles.append(h)
            unique_labels.append(l)
    ax.legend(unique_handles, unique_labels, fontsize=9, loc="upper left")
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    margin = 2.0
    ax.set_xlim(bounds[0] - margin, bounds[2] + margin)
    ax.set_ylim(bounds[1] - margin, bounds[3] + margin)
    ax.grid(True, alpha=0.3)

    # --- Right: zoomed view of vulnerable areas ---
    ax2 = axes[1]
    ax2.set_title("Bending-Vulnerable Areas (zoomed)", fontsize=12, fontweight="bold")
    ax2.set_aspect("equal")

    # Board outline
    ax2.plot(bx, by, color="royalblue", linewidth=1.0, alpha=0.5)
    ax2.fill(bx, by, alpha=0.05, color="royalblue")

    if vulnerable_areas:
        # Compute combined bounding box of vulnerable areas
        all_bounds = [a.bounds for a in vulnerable_areas]
        zoom_xmin = min(b[0] for b in all_bounds) - 3
        zoom_ymin = min(b[1] for b in all_bounds) - 3
        zoom_xmax = max(b[2] for b in all_bounds) + 3
        zoom_ymax = max(b[3] for b in all_bounds) + 3

        for i, area in enumerate(vulnerable_areas):
            vx, vy = area.exterior.xy
            ax2.fill(vx, vy, alpha=0.5, color="red")
            ax2.plot(vx, vy, color="darkred", linewidth=2.0)
            # Label
            centroid = area.centroid
            ax2.annotate(f"Area {i+1}\n{area.area:.1f}mm²",
                         (centroid.x, centroid.y),
                         fontsize=8, fontweight="bold", color="darkred",
                         ha="center", va="center",
                         bbox=dict(boxstyle="round,pad=0.3",
                                   facecolor="white", alpha=0.8))

        ax2.set_xlim(zoom_xmin, zoom_xmax)
        ax2.set_ylim(zoom_ymin, zoom_ymax)
    else:
        ax2.text(0.5, 0.5, "No bending-vulnerable areas detected",
                 transform=ax2.transAxes, ha="center", va="center",
                 fontsize=14, color="green", fontweight="bold")
        ax2.set_xlim(bounds[0] - margin, bounds[2] + margin)
        ax2.set_ylim(bounds[1] - margin, bounds[3] + margin)

    ax2.set_xlabel("X (mm)")
    ax2.set_ylabel("Y (mm)")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = "debug_bending_vulnerable.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\nVisualization saved: {out_path}")


if __name__ == "__main__":
    main()
