"""Diagnostic: compare fill strategies for interposer container outlines.

Usage:
    python debug_interposer.py <job_name>

<job_name> is the cache sub-folder name (e.g. designodb_rigidflex).

For each interposer it prints the raw container-frame outline structure plus
the resulting AREA of several candidate "fill the outer boundary" strategies.
The correct strategy is the one whose area jumps from the thin "bread" area
up to (roughly) the full area enclosed by the outer perimeter.
"""

from __future__ import annotations

import sys
from pathlib import Path

from shapely.geometry import Polygon as ShapelyPolygon
from shapely.ops import polygonize, unary_union
from shapely.validation import make_valid

from main import _load_from_cache
from src.checklist.component_classifier import find_interposers
from src.checklist.geometry_utils import get_component_outline


def _area(geom) -> str:
    if geom is None or getattr(geom, "is_empty", True):
        return "EMPTY"
    return f"{geom.geom_type} area={geom.area:.2f}"


def _exterior_fill(geom):
    if geom is None or geom.is_empty:
        return None
    if hasattr(geom, "exterior"):
        return ShapelyPolygon(geom.exterior)
    if hasattr(geom, "geoms"):
        return unary_union([
            ShapelyPolygon(g.exterior)
            for g in geom.geoms if hasattr(g, "exterior")
        ])
    return None


def _polygonize_fill(geom):
    try:
        faces = list(polygonize(unary_union(geom.boundary)))
        if faces:
            return unary_union(faces), len(faces)
    except Exception as e:  # noqa: BLE001
        return None, f"err:{e}"
    return None, 0


def _close_fill(geom, frac):
    try:
        minx, miny, maxx, maxy = geom.bounds
        eps = max(maxx - minx, maxy - miny) * frac
        closed = geom.buffer(eps).buffer(-eps)
        return _exterior_fill(closed)
    except Exception as e:  # noqa: BLE001
        return None


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python debug_interposer.py <job_name>")
        sys.exit(1)
    job_name = sys.argv[1]
    data = _load_from_cache(Path("cache"), job_name)
    eda = data.get("eda_data")
    packages = eda.packages if eda else []

    for side, comps in [("TOP", data.get("components_top", [])),
                        ("BOTTOM", data.get("components_bot", []))]:
        interposers = find_interposers(comps)
        if not interposers:
            continue
        is_bottom = (side == "BOTTOM")
        print(f"\n===== {side}: {len(interposers)} interposer(s) =====")
        for cont in interposers:
            print(f"\n[{cont.comp_name}] pkg_ref={cont.pkg_ref}")
            if not (0 <= cont.pkg_ref < len(packages)):
                continue
            pkg = packages[cont.pkg_ref]
            outline = get_component_outline(cont, pkg, is_bottom=is_bottom)
            if outline is None:
                print("  outline = None")
                continue

            minx, miny, maxx, maxy = outline.bounds
            bbox_area = (maxx - minx) * (maxy - miny)
            n_int = (len(outline.interiors)
                     if hasattr(outline, "interiors") else "-")
            print(f"  outline: {_area(outline)} "
                  f"valid={outline.is_valid} simple={outline.is_simple} "
                  f"interiors={n_int}")
            print(f"  bbox area={bbox_area:.2f}  (full fill should be ~this "
                  f"minus any real outer notches)")

            mv = make_valid(outline)
            print(f"  make_valid               -> {_area(mv)}")
            print(f"  exterior_fill            -> {_area(_exterior_fill(outline))}")
            pf, nf = _polygonize_fill(outline)
            print(f"  polygonize(boundary)     -> {_area(pf)}  faces={nf}")
            print(f"  close 1% + exterior_fill -> {_area(_close_fill(outline, 0.01))}")
            print(f"  close 3% + exterior_fill -> {_area(_close_fill(outline, 0.03))}")
            print(f"  convex_hull              -> {_area(outline.convex_hull)}")


if __name__ == "__main__":
    main()
