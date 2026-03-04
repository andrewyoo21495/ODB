"""Component overlay rendering - full geometry from EDA package data.

For each placed component the renderer looks up its Package via pkg_ref
(a 0-based index into EdaData.packages) and draws:

  * Pin pad shapes  – RC / CR / SQ / CT / CONTOUR outlines stored on each Pin
  * Package outlines – courtyard / silkscreen shapes stored on the Package itself
  * Fallback         – dashed bounding-box when no pin geometry is available

All outline coordinates are in package-local space and are transformed to
board coordinates by applying mirror → rotate → translate.

draw_components() accepts:
  show_pads=True          Draw pin-level pad shapes.
  show_pkg_outlines=True  Draw package-level courtyard / silkscreen outlines.
  show_labels=False       Annotate each component with its ref-des.

Set show_pads=False, show_pkg_outlines=True (with a yellow color) to render
only the component boundary outlines as a separate pass.
"""

from __future__ import annotations

import math

import numpy as np
from matplotlib.axes import Axes
from matplotlib.patches import Circle, Polygon, Rectangle

from src.models import BBox, Component, Package, PinOutline
from src.visualizer.symbol_renderer import contour_to_vertices


_INCH_TO_MM = 25.4


def _pkg_scale_factor(eda_units: str | None, board_units: str | None) -> float:
    """Return the multiplier to convert EDA package-local coordinates to board units."""
    if not eda_units or eda_units == board_units:
        return 1.0
    # When EDA package data is in inches, apply the inch→mm factor unless the
    # board is explicitly also in inches.  If board_units is unknown (None) we
    # assume the board is in MM, which is the ODB++ default.
    if eda_units == "INCH" and board_units != "INCH":
        return _INCH_TO_MM
    if eda_units == "MM" and board_units == "INCH":
        return 1.0 / _INCH_TO_MM
    return 1.0


def draw_components(ax: Axes, components: list[Component],
                    packages: list[Package] = None,
                    color: str = "#00CCCC", alpha: float = 0.5,
                    show_labels: bool = False, font_size: float = 4,
                    show_pads: bool = True,
                    show_pkg_outlines: bool = True,
                    eda_units: str | None = None,
                    board_units: str | None = None):
    """Draw component geometries derived from EDA package definitions.

    Args:
        ax:                matplotlib Axes to draw on.
        components:        Placed components (top or bottom layer).
        packages:          Package definitions from EdaData.packages.
                           comp.pkg_ref is the 0-based index into this list.
        color:             Fill / stroke colour for pads and outlines.
        alpha:             Opacity for pad fills.
        show_labels:       Whether to annotate each component with its ref-des.
        font_size:         Font size for ref-des labels.
        show_pads:         Draw pin-level pad shapes.
        show_pkg_outlines: Draw package-level courtyard / silkscreen outlines.
        eda_units:         Unit system of EDA package data ("INCH" or "MM").
        board_units:       Unit system of board coordinates ("INCH" or "MM").
                           When these differ a scale factor is applied to all
                           package-local coordinates so they match the board.
    """
    scale = _pkg_scale_factor(eda_units, board_units)

    pkg_lookup: dict[int, Package] = (
        {i: pkg for i, pkg in enumerate(packages)} if packages else {}
    )

    for comp in components:
        pkg = pkg_lookup.get(comp.pkg_ref)
        drew = _draw_component_geometry(ax, comp, pkg, color, alpha,
                                        draw_pads=show_pads,
                                        draw_pkg_outlines=show_pkg_outlines,
                                        pkg_scale=scale)

        if not drew:
            # Fallback: dashed bounding box
            bbox = _get_component_bbox(comp, pkg, pkg_scale=scale)
            if bbox:
                _draw_comp_outline(ax, bbox, color,
                                   alpha if show_pads else alpha * 0.7)

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
                              color: str, alpha: float,
                              draw_pads: bool = True,
                              draw_pkg_outlines: bool = True,
                              pkg_scale: float = 1.0) -> bool:
    """Render pin pads and/or package outlines for one component.

    *pkg_scale* converts EDA package-local dimensions to board units.
    Returns True when at least one patch was added to *ax*.
    """
    if pkg is None:
        return False

    drew_any = False

    # -- Pin-level pad shapes ------------------------------------------------
    if draw_pads:
        for pin in pkg.pins:
            if pin.outlines:
                for outline in pin.outlines:
                    patch = _outline_to_patch(outline, comp, color, alpha,
                                              pkg_scale=pkg_scale)
                    if patch is not None:
                        ax.add_patch(patch)
                        drew_any = True
            else:
                # No explicit outline – draw a small circle at the pin centre
                cx = pin.center.x * pkg_scale
                cy = pin.center.y * pkg_scale
                bx, by = _transform_point(cx, cy, comp)
                fhs = pin.finished_hole_size * pkg_scale
                r = fhs / 2 if fhs > 0 else 0.1  # 0.1 mm fallback
                ax.add_patch(Circle((bx, by), r,
                                    facecolor=color, edgecolor=color,
                                    alpha=alpha * 0.7, linewidth=0))
                drew_any = True

    # -- Package-level courtyard / silkscreen outlines -----------------------
    if draw_pkg_outlines:
        ol_alpha = alpha * 0.5 if draw_pads else alpha
        for outline in pkg.outlines:
            patch = _outline_to_patch(outline, comp, color, ol_alpha,
                                      filled=False, linestyle="--",
                                      pkg_scale=pkg_scale)
            if patch is not None:
                ax.add_patch(patch)
                drew_any = True

    return drew_any


def _outline_to_patch(outline: PinOutline, comp: Component,
                      color: str, alpha: float,
                      filled: bool = True,
                      linestyle: str = "-",
                      pkg_scale: float = 1.0):
    """Convert a PinOutline to a board-coordinate matplotlib patch.

    *pkg_scale* converts package-local dimensions to board coordinate units.
    Returns None for unknown or degenerate shapes.
    """
    p = outline.params
    fc = color if filled else "none"
    s = pkg_scale

    # -- Circle (CR) or rounded/chamfered circle (CT) -----------------------
    if outline.type in ("CR", "CT"):
        xc, yc = _transform_point(
            p.get("xc", 0.0) * s, p.get("yc", 0.0) * s, comp)
        r = p.get("radius", 0.001) * s
        if r <= 0:
            return None
        return Circle((xc, yc), r,
                      facecolor=fc, edgecolor=color,
                      alpha=alpha, linewidth=0.4, linestyle=linestyle)

    # -- Rectangle (RC) – lower-left corner + width + height ----------------
    if outline.type == "RC":
        llx = p.get("llx", 0.0) * s
        lly = p.get("lly", 0.0) * s
        w   = p.get("width", 0.0) * s
        h   = p.get("height", 0.0) * s
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
        xc = p.get("xc", 0.0) * s
        yc = p.get("yc", 0.0) * s
        hs = p.get("half_side", 0.001) * s
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
        if s != 1.0:
            verts = verts * s
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
    # Bottom-side (mirrored) components require a negated rotation because
    # the mirror flip reverses the rotation direction.  Top-side components
    # use the rotation value directly.
    angle = math.radians(-comp.rotation if comp.mirror else comp.rotation)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return (px * cos_a - py * sin_a + comp.x,
            px * sin_a + py * cos_a + comp.y)


def _transform_pts(pts: np.ndarray, comp: Component) -> np.ndarray:
    """Transform an (N, 2) array of package-local points to board coordinates."""
    out = pts.copy().astype(float)
    if comp.mirror:
        out[:, 1] = -out[:, 1]
    angle = math.radians(-comp.rotation if comp.mirror else comp.rotation)
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


def _get_component_bbox(comp: Component, pkg: Package | None,
                        pkg_scale: float = 1.0) -> BBox | None:
    """Compute a board-coordinate bounding box for the fallback outline.

    *pkg_scale* converts package-local dimensions to board coordinate units.
    """
    if pkg and pkg.bbox:
        bx = pkg.bbox
        hw = (bx.xmax - bx.xmin) / 2 * pkg_scale
        hh = (bx.ymax - bx.ymin) / 2 * pkg_scale
        corners = np.array([[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]])
        pts = _transform_pts(corners, comp)
        return BBox(float(pts[:, 0].min()), float(pts[:, 1].min()),
                    float(pts[:, 0].max()), float(pts[:, 1].max()))

    if comp.toeprints:
        xs = [t.x for t in comp.toeprints]
        ys = [t.y for t in comp.toeprints]
        m = 0.13  # ~0.13 mm margin (or ~5 mil)
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
