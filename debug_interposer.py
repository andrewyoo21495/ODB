"""Diagnostic: dump interposer outline / interior geometry structure.

Usage:
    python debug_interposer.py <job_name>

<job_name> is the cache sub-folder name (e.g. designodb_rigidflex).
Run it against a job that contains interposers (INP*/INT*).

It prints, for each interposer on each side, the geometry produced by the
outline / interior resolvers so we can see exactly why the purple INSIDE
region is only covering the donut "ring" instead of the full outer area.
"""

from __future__ import annotations

import sys
from pathlib import Path

from main import _load_from_cache
from src.checklist.component_classifier import find_interposers
from src.checklist.geometry_utils import (
    get_component_outline,
    get_container_interior,
    get_outer_outline_filled,
)


def _describe(geom) -> str:
    if geom is None:
        return "None"
    if getattr(geom, "is_empty", False):
        return f"{geom.geom_type}(EMPTY)"
    gt = geom.geom_type
    if gt == "Polygon":
        holes = len(geom.interiors)
        return (f"Polygon area={geom.area:.3f} holes={holes} "
                f"bounds={tuple(round(b, 2) for b in geom.bounds)}")
    if gt in ("MultiPolygon", "GeometryCollection"):
        parts = list(geom.geoms)
        areas = ", ".join(f"{p.area:.2f}" for p in parts)
        holes = sum(len(p.interiors) for p in parts if hasattr(p, "interiors"))
        return (f"{gt} n={len(parts)} total_area={geom.area:.3f} "
                f"holes={holes} part_areas=[{areas}] "
                f"bounds={tuple(round(b, 2) for b in geom.bounds)}")
    return f"{gt} area={getattr(geom, 'area', 0):.3f}"


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python debug_interposer.py <job_name>")
        sys.exit(1)
    job_name = sys.argv[1]
    cache_dir = Path("cache")

    data = _load_from_cache(cache_dir, job_name)
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
            if 0 <= cont.pkg_ref < len(packages):
                pkg = packages[cont.pkg_ref]
                print(f"  pkg.name={pkg.name!r}  n_outlines={len(pkg.outlines)}")
                otypes = {}
                for o in pkg.outlines:
                    otypes[o.type] = otypes.get(o.type, 0) + 1
                print(f"  outline types: {otypes}")
                outline = get_component_outline(cont, pkg, is_bottom=is_bottom)
                print(f"  get_component_outline   -> {_describe(outline)}")
                ci = get_container_interior(cont, pkg, is_bottom=is_bottom)
                cif = get_outer_outline_filled(
                    cont, pkg, is_bottom=is_bottom)
                print(f"  get_container_interior     -> {_describe(ci)}")
                print(f"  get_outer_outline_filled   -> {_describe(cif)}")


if __name__ == "__main__":
    main()
