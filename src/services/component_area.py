"""Shared component footprint-area helpers.

A component's footprint area is taken from its largest package outline polygon
(body / courtyard), falling back to the package bounding box.  The area is
invariant under the placement transform (mirror / rotate / translate), so the
package-local shape is sufficient.

Used by the Interposer Analyzer and the Volume Analyzer hub features.
"""

from __future__ import annotations

import math


def outline_area(outline) -> float:
    """Area (mm^2) of a single package outline in package-local space."""
    p = outline.params or {}
    t = outline.type
    if t in ("CR", "CT"):
        r = p.get("radius", 0.0)
        return math.pi * r * r
    if t == "RC":
        return abs(p.get("width", 0.0) * p.get("height", 0.0))
    if t == "SQ":
        hs = p.get("half_side", 0.0)
        return (2 * hs) * (2 * hs)
    if t == "CONTOUR" and outline.contour is not None:
        from src.visualizer.symbol_renderer import contour_to_vertices
        verts = contour_to_vertices(outline.contour)
        if len(verts) >= 3:
            try:
                from shapely.geometry import Polygon as SPoly
                return abs(SPoly(verts).area)
            except Exception:
                return 0.0
    return 0.0


def component_area(comp, pkg) -> float:
    """Component footprint area: largest package outline, else bbox area."""
    if pkg and getattr(pkg, "outlines", None):
        largest = max((outline_area(o) for o in pkg.outlines), default=0.0)
        if largest > 0:
            return largest
    if pkg and getattr(pkg, "bbox", None):
        b = pkg.bbox
        return abs((b.xmax - b.xmin) * (b.ymax - b.ymin))
    return 0.0
