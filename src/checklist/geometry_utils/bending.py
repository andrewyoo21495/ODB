"""Bending-vulnerable area detection on PCB outlines."""

from __future__ import annotations

try:
    from shapely.geometry import (
        MultiPolygon as ShapelyMultiPolygon,
        Point as ShapelyPoint,
        Polygon as ShapelyPolygon,
    )
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False


def find_bending_vulnerable_areas(
    board_polygon,
    width_threshold: float = 8.0,
    protrusion_depth: float = 2.0,
) -> list:
    """Identify bending-vulnerable areas on the PCB.

    A bending-vulnerable area is a thin protruding region where the local
    width is <= width_threshold mm and the protrusion extends >= protrusion_depth
    mm from the main body.  Uses morphological opening (erosion + dilation).

    Returns:
        list[shapely Polygon]: polygons for each bending-vulnerable region.
        Empty list if none are found or shapely is unavailable.
    """
    if not _HAS_SHAPELY or board_polygon is None:
        return []

    half_w = width_threshold / 2.0

    eroded = board_polygon.buffer(-half_w)
    if eroded.is_empty:
        return [board_polygon]

    opened = eroded.buffer(half_w)
    protrusions = board_polygon.difference(opened)
    if protrusions.is_empty:
        return []

    if isinstance(protrusions, ShapelyMultiPolygon):
        parts = list(protrusions.geoms)
    elif isinstance(protrusions, ShapelyPolygon):
        parts = [protrusions]
    else:
        parts = [g for g in protrusions.geoms
                 if isinstance(g, ShapelyPolygon)]

    vulnerable: list = []
    for part in parts:
        max_dist = 0.0
        for coord in part.exterior.coords:
            d = ShapelyPoint(coord).distance(opened)
            if d > max_dist:
                max_dist = d
        if max_dist >= protrusion_depth:
            vulnerable.append(part)

    return vulnerable
