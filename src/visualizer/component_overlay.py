"""Component overlay rendering - full geometry from EDA package data.

For each placed component the renderer looks up its Package via pkg_ref
(a 0-based index into EdaData.packages) and draws:

  * Pin pad shapes  – RC / CR / SQ / CT / CONTOUR outlines stored on each Pin
  * Package outlines – courtyard / silkscreen shapes stored on the Package itself
  * Fallback         – dashed bounding-box when no pin geometry is available

All outline coordinates are in package-local space and are transformed to
board coordinates by applying mirror → rotate → translate.
"""

from __future__ import annotations

import math

import numpy as np
from matplotlib.axes import Axes
from matplotlib.patches import Circle, Polygon, Rectangle

from src.models import BBox, Component, Package, PinOutline
from src.visualizer.symbol_renderer import contour_to_vertices


def draw_components(ax: Axes, components: list[Component],
                    packages: list[Package] = None,
                    color: str = "#00CCCC", alpha: float = 0.5,
                    show_labels: bool = True, font_size: float = 4):
    """Draw component geometries derived from EDA package definitions.

    Args:
        ax:           matplotlib Axes to draw on.
        components:   Placed components (top or bottom layer).
        packages:     Package definitions from EdaData.packages.
                      comp.pkg_ref is the 0-based index into this list.
        color:        Fill / stroke colour for pads and outlines.
        alpha:        Opacity for pad fills.
        show_labels:  Whether to annotate each component with its ref-des.
        font_size:    Font size for ref-des labels.
    """
    pkg_lookup: dict[int, Package] = (
        {i: pkg for i, pkg in enumerate(packages)} if packages else {}
    )

    for comp in components:
        pkg = pkg_lookup.get(comp.pkg_ref)
        drew = _draw_component_geometry(ax, comp, pkg, color, alpha)

        if not drew:
            # Fallback: dashed bounding box from Package.bbox or toeprints
            bbox = _get_component_bbox(comp, pkg)
            if bbox:
                _draw_comp_outline(ax, bbox, color, alpha)

        if show_labels:
            ax.annotate(
                comp.comp_name,
                (comp.x, comp.y),
                fontsize=font_size,
                color=color,
                alpha=min(1.0, alpha + 0.3),
                ha="center", va="center",
                fontweight="bold",
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _draw_component_geometry(ax: Axes, comp: Component,
                              pkg: Package | None,
                              color: str, alpha: float) -> bool:
    """Render pin pads and package outlines for one component.

    Returns True when at least one patch was added to *ax*.
    """
    if pkg is None:
        return False

    drew_any = False

    # -- Pin-level pad shapes ------------------------------------------------
    for pin in pkg.pins:
        if pin.outlines:
            for outline in pin.outlines:
                patch = _outline_to_patch(outline, comp, color, alpha)
                if patch is not None:
                    ax.add_patch(patch)
                    drew_any = True
        else:
            # No explicit outline – draw a small circle at the pin centre
            bx, by = _transform_point(pin.center.x, pin.center.y, comp)
            fhs = pin.finished_hole_size
            r = fhs / 2 if fhs > 0 else 0.004
            ax.add_patch(Circle((bx, by), r,
                                facecolor=color, edgecolor=color,
                                alpha=alpha * 0.7, linewidth=0))
            drew_any = True

    # -- Package-level courtyard / silkscreen outlines -----------------------
    for outline in pkg.outlines:
        patch = _outline_to_patch(outline, comp, color, alpha * 0.5,
                                  filled=False, linestyle="--")
        if patch is not None:
            ax.add_patch(patch)
            drew_any = True

    return drew_any


def _outline_to_patch(outline: PinOutline, comp: Component,
                      color: str, alpha: float,
                      filled: bool = True,
                      linestyle: str = "-"):
    """Convert a PinOutline to a board-coordinate matplotlib patch.

    Returns None for unknown or degenerate shapes.
    """
    p = outline.params
    fc = color if filled else "none"

    # -- Circle (CR) or rounded/chamfered circle (CT) -----------------------
    if outline.type in ("CR", "CT"):
        xc, yc = _transform_point(p.get("xc", 0.0), p.get("yc", 0.0), comp)
        r = p.get("radius", 0.001)
        if r <= 0:
            return None
        return Circle((xc, yc), r,
                      facecolor=fc, edgecolor=color,
                      alpha=alpha, linewidth=0.4, linestyle=linestyle)

    # -- Rectangle (RC) – lower-left corner + width + height ----------------
    if outline.type == "RC":
        llx = p.get("llx", 0.0)
        lly = p.get("lly", 0.0)
        w   = p.get("width", 0.0)
        h   = p.get("height", 0.0)
        if w <= 0 or h <= 0:
            return None
        corners = np.array([
            [llx,     lly],
            [llx + w, lly],
            [llx + w, lly + h],
            [llx,     lly + h],
        ])
        pts = _transform_pts(corners, comp)
        return Polygon(pts, closed=True,
                       facecolor=fc, edgecolor=color,
                       alpha=alpha, linewidth=0.4, linestyle=linestyle)

    # -- Square (SQ) – centre + half-side -----------------------------------
    if outline.type == "SQ":
        xc = p.get("xc", 0.0)
        yc = p.get("yc", 0.0)
        hs = p.get("half_side", 0.001)
        if hs <= 0:
            return None
        corners = np.array([
            [xc - hs, yc - hs],
            [xc + hs, yc - hs],
            [xc + hs, yc + hs],
            [xc - hs, yc + hs],
        ])
        pts = _transform_pts(corners, comp)
        return Polygon(pts, closed=True,
                       facecolor=fc, edgecolor=color,
                       alpha=alpha, linewidth=0.4, linestyle=linestyle)

    # -- Complex contour (CONTOUR / OB) -------------------------------------
    if outline.type == "CONTOUR" and outline.contour is not None:
        verts = contour_to_vertices(outline.contour)
        if len(verts) < 2:
            return None
        pts = _transform_pts(verts, comp)
        return Polygon(pts, closed=True,
                       facecolor=fc, edgecolor=color,
                       alpha=alpha, linewidth=0.4, linestyle=linestyle)

    return None


def _transform_point(px: float, py: float,
                     comp: Component) -> tuple[float, float]:
    """Transform a single package-local point to board coordinates."""
    if comp.mirror:
        py = -py
    angle = math.radians(-comp.rotation)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return (px * cos_a - py * sin_a + comp.x,
            px * sin_a + py * cos_a + comp.y)


def _transform_pts(pts: np.ndarray, comp: Component) -> np.ndarray:
    """Transform an (N, 2) array of package-local points to board coordinates."""
    out = pts.copy().astype(float)
    if comp.mirror:
        out[:, 1] = -out[:, 1]
    angle = math.radians(-comp.rotation)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    x_rot = out[:, 0] * cos_a - out[:, 1] * sin_a
    y_rot = out[:, 0] * sin_a + out[:, 1] * cos_a
    return np.column_stack([x_rot + comp.x, y_rot + comp.y])


def draw_pin_markers(ax: Axes, components: list[Component],
                     color: str = "#FF4444", size: float = 0.002):
    """Draw small dot markers at toeprint (pin) locations."""
    for comp in components:
        for toep in comp.toeprints:
            ax.plot(toep.x, toep.y, ".", color=color, markersize=1, alpha=0.5)


def _get_component_bbox(comp: Component, pkg: Package | None) -> BBox | None:
    """Compute a board-coordinate bounding box for the fallback outline."""
    if pkg and pkg.bbox:
        bx = pkg.bbox
        hw = (bx.xmax - bx.xmin) / 2
        hh = (bx.ymax - bx.ymin) / 2
        corners = np.array([[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]])
        pts = _transform_pts(corners, comp)
        return BBox(float(pts[:, 0].min()), float(pts[:, 1].min()),
                    float(pts[:, 0].max()), float(pts[:, 1].max()))

    if comp.toeprints:
        xs = [t.x for t in comp.toeprints]
        ys = [t.y for t in comp.toeprints]
        m = 0.005
        return BBox(min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m)

    return None


def _draw_comp_outline(ax: Axes, bbox: BBox, color: str, alpha: float):
    """Draw a dashed bounding-box fallback rectangle."""
    w = bbox.xmax - bbox.xmin
    h = bbox.ymax - bbox.ymin
    ax.add_patch(Rectangle(
        (bbox.xmin, bbox.ymin), w, h,
        linewidth=0.5, edgecolor=color, facecolor="none",
        alpha=alpha, linestyle="--",
    ))
