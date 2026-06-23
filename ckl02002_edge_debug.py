"""Debug CKL-02-002 connector edge=TRUE false positives on REAL data.

Usage:
    .odb/Scripts/python output/ckl02002_edge_debug.py <odb_path_or_dir>

For every managed-cap / connector pair that CKL-02-002 would flag edge=TRUE,
it prints the connector's computed edge segments (endpoints, length,
orientation H/V/DIAG, and whether the fallback short-side branch was used) plus
the cap's pad-centre distance to the nearest edge segment.  It also renders one
image per flagged connector so you can eyeball it.

This shows WHY a cap that looks like it is on a long side gets edge=TRUE:
  - fallback picked LEFT/RIGHT (connector pad hull wider than tall), or
  - a short sub-segment of a long side was misclassified as a corner diagonal,
  - or the cap pad centre is genuinely within tolerance of a corner diagonal.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main  # noqa: E402  (provides _ensure_cache / _load_from_cache)
from src.checklist.component_classifier import find_connectors
from src.checklist.reference_loader import get_managed_part_names
from src.checklist.geometry_utils import (
    find_pad_overlapping_components, get_edge_segments, is_on_outline_edge,
    does_pad_overlap_outline,
)
from src.checklist.geometry_utils.polygon import _get_pad_centers, _point_seg_dist_sq
from src.checklist.geometry_utils.overlap import _get_pad_union


def seg_orient(a, b):
    ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0
    if ang < 10 or ang > 170:
        return "H"
    if abs(ang - 90) < 10:
        return "V"
    return "DIAG"


def main_run(odb_path: str):
    cache_dir = Path("cache")
    name = main._ensure_cache(odb_path, cache_dir)
    data = main._load_from_cache(cache_dir, name)
    packages = data["eda_data"].packages
    user_symbols = data.get("user_symbols") or {}
    managed_41 = set(get_managed_part_names("capacitors_41_list"))

    out_dir = ROOT / "output"
    flagged = 0

    for conn_comps, layer, opp_comps in [
        (data["components_top"], "Top", data["components_bot"]),
        (data["components_bot"], "Bottom", data["components_top"]),
    ]:
        conn_is_bottom = (layer == "Bottom")
        cap_is_bottom = not conn_is_bottom
        connectors = find_connectors(conn_comps)
        caps = [c for c in opp_comps if (c.part_name or "") in managed_41]
        if not connectors or not caps:
            continue

        for conn in connectors:
            segs = get_edge_segments(conn, packages, is_bottom=conn_is_bottom)
            for cap in caps:
                pad_ov = find_pad_overlapping_components(
                    conn, [cap], packages, is_bottom_primary=conn_is_bottom,
                    is_bottom_candidates=cap_is_bottom,
                    user_symbols=user_symbols, min_overlap_area=0.001)
                outline_ov = does_pad_overlap_outline(
                    cap, conn, packages, is_bottom_a=cap_is_bottom,
                    is_bottom_b=conn_is_bottom, user_symbols=user_symbols)
                if not pad_ov and not outline_ov:
                    continue
                if not outline_ov:
                    continue  # case 2 -> edge hardcoded FALSE
                on_edge = is_on_outline_edge(
                    cap, conn, packages, is_bottom_a=cap_is_bottom,
                    is_bottom_b=conn_is_bottom)
                if not on_edge:
                    continue

                flagged += 1
                print(f"\n=== FLAGGED edge=TRUE: conn={conn.comp_name} "
                      f"({layer}) cap={cap.comp_name} ===")
                # hull bbox to see aspect + fallback detection
                from src.checklist.geometry_utils.polygon import (
                    _build_pad_convex_hull,
                )
                hull = _build_pad_convex_hull(conn, packages, is_bottom=conn_is_bottom)
                if hull is not None:
                    minx, miny, maxx, maxy = hull.bounds
                    print(f"   hull bbox: w={maxx-minx:.3f} h={maxy-miny:.3f} "
                          f"({'WIDER' if maxx-minx > maxy-miny else 'TALLER'})")
                print(f"   edge segments ({len(segs)}):")
                for a, b in segs:
                    L = math.hypot(b[0]-a[0], b[1]-a[1])
                    print(f"     {seg_orient(a,b):4} len={L:6.3f}  "
                          f"({a[0]:.2f},{a[1]:.2f})->({b[0]:.2f},{b[1]:.2f})")
                centers = _get_pad_centers(cap, packages, is_bottom=cap_is_bottom)
                print(f"   cap pad centres: {[(round(x,2),round(y,2)) for x,y in centers]}")
                best = 1e9
                bestseg = None
                for px, py in centers:
                    for a, b in segs:
                        d = math.sqrt(_point_seg_dist_sq(px, py, a[0], a[1], b[0], b[1]))
                        if d < best:
                            best, bestseg = d, (a, b)
                print(f"   nearest edge dist = {best:.4f} mm "
                      f"(tol=0.4)  on a {seg_orient(*bestseg)} segment")

                # render
                fig, ax = plt.subplots(figsize=(8, 8))
                cp = _get_pad_union(conn, packages, is_bottom=conn_is_bottom,
                                    user_symbols=user_symbols)
                if cp is not None:
                    for g in (cp.geoms if cp.geom_type.startswith("Multi") else [cp]):
                        xs, ys = g.exterior.xy
                        ax.fill(xs, ys, color="#6495ED", alpha=0.3, ec="navy")
                capg = _get_pad_union(cap, packages, is_bottom=cap_is_bottom,
                                      user_symbols=user_symbols)
                if capg is not None:
                    for g in (capg.geoms if capg.geom_type.startswith("Multi") else [capg]):
                        xs, ys = g.exterior.xy
                        ax.fill(xs, ys, color="limegreen", alpha=0.7, ec="darkgreen")
                for a, b in segs:
                    ax.plot([a[0], b[0]], [a[1], b[1]], "r--", lw=2.5, zorder=6)
                ax.set_aspect("equal")
                ax.set_title(f"{conn.comp_name}/{cap.comp_name} edge=TRUE "
                             f"(nearest {best:.3f}mm)")
                img = out_dir / f"ckl02002_dbg_{conn.comp_name}_{cap.comp_name}.png".replace("/", "_")
                fig.savefig(img, dpi=110, bbox_inches="tight")
                plt.close(fig)
                print(f"   saved {img.name}")

    print(f"\nTotal flagged edge=TRUE: {flagged}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python output/ckl02002_edge_debug.py <odb_path>")
        sys.exit(1)
    main_run(sys.argv[1])
