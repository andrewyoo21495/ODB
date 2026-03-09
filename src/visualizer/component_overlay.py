"""Component overlay rendering - full geometry from EDA package data.

For each placed component the renderer looks up its Package via pkg_ref
(a 0-based index into EdaData.packages) and draws:

  * Pin pad shapes  – RC / CR / SQ / CT / CONTOUR outlines stored on each Pin
  * Package outlines – courtyard / silkscreen shapes stored on the Package itself
  * Fallback         – dashed bounding-box when no pin geometry is available

All coordinate data (components, EDA packages, profile, layer features) is
normalised to MM before rendering.  Outline coordinates are in package-local
space and are transformed to board coordinates by applying mirror → rotate →
translate.

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

from src.models import BBox, Component, LayerFeatures, Package, PinOutline, UserSymbol
from src.visualizer.symbol_renderer import contour_to_vertices, symbol_to_patch, user_symbol_to_patches


def draw_components(ax: Axes, components: list[Component],
                    packages: list[Package] = None,
                    color: str = "#00CCCC", alpha: float = 0.5,
                    show_labels: bool = False, font_size: float = 4,
                    show_pads: bool = True,
                    show_pkg_outlines: bool = True,
                    comp_layer_features: LayerFeatures = None,
                    user_symbols: dict[str, UserSymbol] = None):
    """Draw component geometries derived from EDA package definitions.

    All coordinates are expected to be pre-normalised to the same unit (MM).

    When *comp_layer_features* is supplied the renderer uses the actual pad
    shapes from that layer (comp_+_top or comp_+_bot) keyed by toeprint board
    position.  This gives accurate polygon pad geometry instead of the
    simplified RC/CR outlines stored in the EDA package data.
    """
    pkg_lookup: dict[int, Package] = (
        {i: pkg for i, pkg in enumerate(packages)} if packages else {}
    )

    # Build a spatial index: (rounded_x, rounded_y) → pad feature
    # from the component layer so we can look up by toeprint position.
    pad_by_pos: dict[tuple[int, int], object] = {}
    pad_sym_lookup: dict[int, object] = {}
    pad_units: str = "INCH"
    if comp_layer_features is not None:
        from src.models import PadRecord
        pad_units = comp_layer_features.units
        pad_sym_lookup = {s.index: s for s in comp_layer_features.symbols}
        for feat in comp_layer_features.features:
            if isinstance(feat, PadRecord):
                key = (round(feat.x, 4), round(feat.y, 4))
                pad_by_pos[key] = feat

    for comp in components:
        pkg = pkg_lookup.get(comp.pkg_ref)
        drew = _draw_component_geometry(ax, comp, pkg, color, alpha,
                                        draw_pads=show_pads,
                                        draw_pkg_outlines=show_pkg_outlines,
                                        pad_by_pos=pad_by_pos,
                                        pad_sym_lookup=pad_sym_lookup,
                                        pad_units=pad_units,
                                        user_symbols=user_symbols or {})

        if not drew:
            # Fallback: dashed bounding box
            bbox = _get_component_bbox(comp, pkg)
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
                              pad_by_pos: dict = None,
                              pad_sym_lookup: dict = None,
                              pad_units: str = "INCH",
                              user_symbols: dict = None) -> bool:
    """Render pin pads and/or package outlines for one component.

    Returns True when at least one patch was added to *ax*.

    Pin pad rendering priority:
      1. Component-layer pad feature at the toeprint position (most accurate —
         real polygon geometry from the design tool).
      2. EDA package pin outline (RC / CR / SQ / CONTOUR).
      3. Small circle at the pin centre (last-resort fallback).
    """
    if pkg is None:
        return False

    drew_any = False
    pad_by_pos = pad_by_pos or {}
    pad_sym_lookup = pad_sym_lookup or {}
    user_symbols = user_symbols or {}

    # -- Pin-level pad shapes ------------------------------------------------
    if draw_pads:
        # Build a quick lookup from pin index → toeprint board position
        toep_by_pin: dict[int, object] = {}
        for tp in comp.toeprints:
            toep_by_pin[tp.pin_num] = tp

        for pin_idx, pin in enumerate(pkg.pins):
            drew_pin = False

            # 1. Try component-layer pad at the toeprint position
            tp = toep_by_pin.get(pin_idx) or toep_by_pin.get(pin_idx + 1)
            if tp is not None and pad_by_pos:
                key = (round(tp.x, 4), round(tp.y, 4))
                pad_feat = pad_by_pos.get(key)
                if pad_feat is not None:
                    sym_ref = pad_sym_lookup.get(pad_feat.symbol_idx)
                    if sym_ref is not None:
                        if sym_ref.name in user_symbols:
                            patches = user_symbol_to_patches(
                                user_symbols[sym_ref.name],
                                tp.x, tp.y,
                                pad_feat.rotation, pad_feat.mirror,
                                color, alpha,
                            )
                            for p in patches:
                                ax.add_patch(p)
                            if patches:
                                drew_pin = True
                        else:
                            patch = symbol_to_patch(
                                sym_ref.name, tp.x, tp.y,
                                pad_feat.rotation, pad_feat.mirror,
                                pad_units, sym_ref.unit_override,
                                color, alpha, pad_feat.resize_factor,
                            )
                            if patch is not None:
                                ax.add_patch(patch)
                                drew_pin = True

            # 2. Fall back to EDA package pin outlines
            if not drew_pin and pin.outlines:
                for outline in pin.outlines:
                    patch = _outline_to_patch(outline, comp, color, alpha)
                    if patch is not None:
                        ax.add_patch(patch)
                        drew_pin = True

            # 3. Last-resort: small circle at the transformed pin centre
            if not drew_pin:
                bx, by = _transform_point(pin.center.x, pin.center.y, comp)
                fhs = pin.finished_hole_size
                r = fhs / 2 if fhs > 0 else 0.1
                ax.add_patch(Circle((bx, by), r,
                                    facecolor=color, edgecolor=color,
                                    alpha=alpha * 0.7, linewidth=0))
                drew_pin = True

            if drew_pin:
                drew_any = True

    # -- Package-level courtyard / silkscreen outlines -----------------------
    if draw_pkg_outlines:
        ol_alpha = alpha * 0.5 if draw_pads else alpha
        for outline in pkg.outlines:
            patch = _outline_to_patch(outline, comp, color, ol_alpha,
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
        xc, yc = _transform_point(
            p.get("xc", 0.0), p.get("yc", 0.0), comp)
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
    """Transform a single package-local point to board coordinates.

    ODB++ stores the rotation angle as it appears in the final assembly view
    (looking at the board from the top).  The correct transform order is:
      1. Rotate (CW-positive) in package space.
      2. Mirror X for bottom-layer components (comp.mirror=True).
      3. Translate to board position.

    Applying mirror before rotation (wrong order) reverses the effective
    rotation direction for non-zero angles, producing a horizontally-mirrored
    appearance on the bottom layer.
    """
    angle = math.radians(comp.rotation)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    # Step 1: clockwise rotation in package space
    x_rot = px * cos_a + py * sin_a
    y_rot = -px * sin_a + py * cos_a
    # Step 2: mirror X for bottom-layer components
    if comp.mirror:
        x_rot = -x_rot
    return (x_rot + comp.x, y_rot + comp.y)


def _transform_pts(pts: np.ndarray, comp: Component) -> np.ndarray:
    """Transform an (N, 2) array of package-local points to board coordinates.

    ODB++ stores the rotation angle as it appears in the final assembly view
    (looking at the board from the top).  The correct transform order is:
      1. Rotate (CW-positive) in package space.
      2. Mirror X for bottom-layer components (comp.mirror=True).
      3. Translate to board position.
    """
    out = pts.copy().astype(float)
    angle = math.radians(comp.rotation)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    # Step 1: clockwise rotation in package space
    x_rot = out[:, 0] * cos_a + out[:, 1] * sin_a
    y_rot = -out[:, 0] * sin_a + out[:, 1] * cos_a
    # Step 2: mirror X for bottom-layer components
    if comp.mirror:
        x_rot = -x_rot
    return np.column_stack([x_rot + comp.x, y_rot + comp.y])


# Public aliases so other modules can import the transform helpers.
transform_point = _transform_point
transform_pts = _transform_pts


def draw_pin_markers(ax: Axes, components: list[Component],
                     color: str = "#FF4444", size: float = 0.002):
    """Draw small dot markers at toeprint (pin) locations."""
    for comp in components:
        for toep in comp.toeprints:
            ax.plot(toep.x, toep.y, ".", color=color, markersize=1, alpha=0.5)


def _get_component_bbox(comp: Component,
                        pkg: Package | None) -> BBox | None:
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
        m = 0.13  # ~0.13 mm margin
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
