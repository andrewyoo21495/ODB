"""Distance measurement and CSV component list utilities.

Provides:
- center_distance           — Euclidean distance between component centres
- edge_distance             — minimum footprint boundary distance
- load_component_list       — load a managed component CSV
- filter_components_by_list — filter by CSV membership
"""

from __future__ import annotations

import csv
import math
from typing import Sequence

from src.models import Component
from .polygon import _resolve_footprint

try:
    _HAS_SHAPELY = True
    from shapely.geometry import Point as ShapelyPoint  # noqa: F401
except ImportError:
    _HAS_SHAPELY = False


def center_distance(comp_a: Component, comp_b: Component) -> float:
    """Euclidean distance between component centres (mm)."""
    dx = comp_a.x - comp_b.x
    dy = comp_a.y - comp_b.y
    return math.sqrt(dx * dx + dy * dy)


def edge_distance(comp_a: Component, comp_b: Component,
                  packages: list) -> float:
    """Minimum distance between footprint polygon boundaries (mm).

    Returns float('inf') if footprint polygons cannot be built.
    Falls back to center_distance if shapely is unavailable.
    """
    if not _HAS_SHAPELY:
        return center_distance(comp_a, comp_b)

    fp_a = _resolve_footprint(comp_a, packages)
    fp_b = _resolve_footprint(comp_b, packages)

    if fp_a is None or fp_b is None:
        return float("inf")

    return fp_a.distance(fp_b)


# ---------------------------------------------------------------------------
# CSV component list loading
# ---------------------------------------------------------------------------

def load_component_list(csv_path: str) -> list[dict]:
    """Load a managed component list CSV file.

    Expected columns: comp, part_name, size (matching references/*.csv format).
    Returns a list of dicts with those keys.
    """
    entries: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append({
                "comp": row.get("comp", "").strip(),
                "part_name": row.get("part_name", "").strip(),
                "size": row.get("size", "").strip(),
            })
    return entries


def filter_components_by_list(components: list[Component],
                              csv_entries: list[dict]) -> list[Component]:
    """Return components whose comp_name matches an entry in the CSV list."""
    names = {e["comp"] for e in csv_entries if e.get("comp")}
    return [c for c in components if c.comp_name in names]
