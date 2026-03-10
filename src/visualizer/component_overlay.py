"""Component overlay rendering - full geometry from EDA package data.

For each placed component the renderer looks up its Package via pkg_ref
(a 0-based index into EdaData.packages) and draws:

  * Pin pad shapes  – RC / CR / SQ / CT / CONTOUR outlines stored on each Pin
  * Package outlines – courtyard / silkscreen shapes stored on the Package itself
  * Fallback         – dashed bounding-box when no pin geometry is available

All coordinate data (components, EDA packages, profile, layer features) is
normalised to MM before rendering.  Outline coordinates are in package-local
space and are transformed to board coordinates following the ODB++ orient_def
convention: mirror → rotate → translate.

**Bottom-layer mirroring:**
Components in comp_+_bot are viewed from the top.  Their CMP x/y and toeprint
coordinates are already in board space (top-view), but package-local geometry
(pin outlines, package outlines, bounding boxes) must be X-mirrored before
rotation and translation because the component sits on the underside.  The
CMP record's mirror flag indicates *additional* mirroring beyond the implicit
bottom-layer flip:

  bottom + mirror=N  → effective mirror = True  (normal bottom placement)
  bottom + mirror=M  → effective mirror = False (extra flip cancels)
  top    + mirror=N  → effective mirror = False
  top    + mirror=M  → effective mirror = True

Pad features from layer feature files carry an orient_def value (0–9) that
encodes both rotation and mirror:
  0-3  → 0/90/180/270° rotation, no mirror
  4-7  → 0/90/180/270° rotation, mirrored in X
  8    → arbitrary angle, no mirror
  9    → arbitrary angle, mirrored in X
The mirror is always applied before the rotation.

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
from matplotlib.patches import Circle, PathPatch, Polygon, Rectangle
from matplotlib.path import Path as MplPath

from src.models import BBox, Component, LayerFeatures, Package, PinOutline, UserSymbol
from src.visualizer.symbol_renderer import (
    contour_to_vertices, get_line_width_for_symbol, symbol_to_patch,
    user_symbol_to_patches,
)


def draw_components(ax: Axes, components: list[Component],
                    packages: list[Package] = None,
                    color: str = "#00CCCC", alpha: float = 0.5,
                    show_labels: bool = False, font_size: float = 4,
                    show_pads: bool = True,
                    show_pkg_outlines: bool = True,
                    comp_layer_features: LayerFeatures = None,
                    user_symbols: dict[str, UserSymbol] = None,
                    fid_resolved: dict = None,
                    comp_side: str = "T"):
    """Draw component geometries derived from EDA package definitions.

    All coordinates are expected to be pre-normalised to the same unit (MM).

    Pin pad rendering priority (highest to lowest):
      0. *fid_resolved* — FID-based lookup from EDA/data SNT→FID records.
         Deterministic mapping via (side, comp_num, pin_num) → feature.
         Only ONE pad shape is drawn per pin (first successful layer match)
         to avoid overlapping shapes from multiple copper/mask layers.
      1. *comp_layer_features* — spatial matching by toeprint (x, y) in the
         comp_+_top or comp_+_bot layer (legacy fallback).
      2. EDA package pin outlines (RC/CR/SQ/CONTOUR).
      3. Small circle at the pin centre (last-resort fallback).

    Args:
        fid_resolved: Pre-resolved FID features — a dict mapping
            ``(side, comp_num, pin_num)`` to a list of
            :class:`~src.visualizer.fid_lookup.ResolvedPadFeature`.
            Built by :func:`~src.visualizer.fid_lookup.resolve_fid_features`.
        comp_side: "T" for top components, "B" for bottom.
    """
    pkg_lookup: dict[int, Package] = (
        {i: pkg for i, pkg in enumerate(packages)} if packages else {}
    )
    fid_resolved = fid_resolved or {}
    is_bottom = (comp_side == "B")

    # Pre-parse the component layer once: build a global position → pad map
    # and collect line features.  Per-component filtering (to only the pads
    # that belong to each component's own toeprints) is done inside the loop
    # so that pads from other components are never accidentally matched.
    _all_pad_by_pos: dict[tuple[float, float], object] = {}
    pad_sym_lookup: dict[int, object] = {}
    pad_units: str = "INCH"
    line_features: list = []
    if comp_layer_features is not None:
        from src.models import LineRecord, PadRecord
        pad_units = comp_layer_features.units
        pad_sym_lookup = {s.index: s for s in comp_layer_features.symbols}
        for feat in comp_layer_features.features:
            if isinstance(feat, PadRecord):
                key = (round(feat.x, 4), round(feat.y, 4))
                _all_pad_by_pos[key] = feat
            elif isinstance(feat, LineRecord):
                line_features.append(feat)

    for comp_idx, comp in enumerate(components):
        pkg = pkg_lookup.get(comp.pkg_ref)

        # Build a component-specific pad lookup restricted to this component's
        # own toeprint positions so that pads belonging to other components are
        # never drawn here, even if their board positions happen to round to the
        # same grid key.
        if _all_pad_by_pos:
            toep_keys = {(round(tp.x, 4), round(tp.y, 4)) for tp in comp.toeprints}
            pad_by_pos = {k: v for k, v in _all_pad_by_pos.items() if k in toep_keys}
        else:
            pad_by_pos = {}

        drew = _draw_component_geometry(ax, comp, pkg, color, alpha,
                                        draw_pads=show_pads,
                                        draw_pkg_outlines=show_pkg_outlines,
                                        pad_by_pos=pad_by_pos,
                                        pad_sym_lookup=pad_sym_lookup,
                                        pad_units=pad_units,
                                        user_symbols=user_symbols or {},
                                        fid_resolved=fid_resolved,
                                        comp_side=comp_side,
                                        comp_idx=comp_idx,
                                        line_features=line_features,
                                        is_bottom=is_bottom)

        if not drew:
            # Fallback: dashed bounding box
            bbox = _get_component_bbox(comp, pkg, is_bottom=is_bottom)
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
                              user_symbols: dict = None,
                              fid_resolved: dict = None,
                              comp_side: str = "T",
                              comp_idx: int = 0,
                              line_features: list = None,
                              is_bottom: bool = False) -> bool:
    """Render pin pads and/or package outlines for one component.

    Returns True when at least one patch was added to *ax*.

    Pin pad rendering priority:
      0. FID-based lookup — deterministic mapping via EDA/data SNT→FID records.
         Only one pad drawn per pin to avoid overlapping shapes.
      1. Component-layer pad feature at the toeprint position (spatial fallback).
      2. EDA package pin outline (RC / CR / SQ / CONTOUR).
      3. Small circle at the pin centre (last-resort fallback).
    """
    if pkg is None:
        return False

    drew_any = False
    pad_by_pos = pad_by_pos or {}
    pad_sym_lookup = pad_sym_lookup or {}
    user_symbols = user_symbols or {}
    fid_resolved = fid_resolved or {}

    # -- Pin-level pad shapes ------------------------------------------------
    if draw_pads:
        # Shield-can shortcut: sweep a circle along the polyline outline
        sc_drawn = False
        if _is_shield_can(comp) and line_features:
            sc_drawn = _draw_shield_can(ax, comp, line_features,
                                        pad_sym_lookup, pad_units,
                                        color, alpha)
            if sc_drawn:
                drew_any = True

        # Shield-can fallback: if sweep failed (e.g. comp layer features are
        # empty), draw a simple bounding-box outline and skip individual pins.
        if _is_shield_can(comp) and not sc_drawn:
            bbox = _get_component_bbox(comp, pkg, is_bottom=is_bottom)
            if bbox:
                _draw_comp_outline(ax, bbox, color, alpha)
                sc_drawn = True
                drew_any = True

        # Build a quick lookup from pin index → toeprint board position
        toep_by_pin: dict[int, object] = {}
        for tp in comp.toeprints:
            toep_by_pin[tp.pin_num] = tp

        for pin_idx, pin in enumerate(pkg.pins if not sc_drawn else []):
            drew_pin = False
            tp = toep_by_pin.get(pin_idx) or toep_by_pin.get(pin_idx + 1)

            # 0. FID-based lookup (highest priority — deterministic)
            if not drew_pin and fid_resolved:
                drew_pin = _draw_pin_from_fid(
                    ax, comp, comp_side, comp_idx, pin_idx, tp,
                    fid_resolved, user_symbols, color, alpha,
                )

            # 1. Try component-layer pad at the toeprint position (spatial)
            if not drew_pin and tp is not None and pad_by_pos:
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
                    patch = _outline_to_patch(outline, comp, color, alpha,
                                              is_bottom=is_bottom)
                    if patch is not None:
                        ax.add_patch(patch)
                        drew_pin = True
                        break  # one outline per pin is enough

            # 3. Last-resort: small circle at the transformed pin centre
            if not drew_pin:
                bx, by = _transform_point(pin.center.x, pin.center.y,
                                          comp, is_bottom=is_bottom)
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
                                      filled=False, linestyle="--",
                                      is_bottom=is_bottom)
            if patch is not None:
                ax.add_patch(patch)
                drew_any = True

    return drew_any


def _draw_pin_from_fid(ax: Axes, comp: Component,
                        comp_side: str, comp_idx: int,
                        pin_idx: int, tp,
                        fid_resolved: dict,
                        user_symbols: dict,
                        color: str, alpha: float) -> bool:
    """Try to draw a pin pad using FID-resolved features.

    Looks up (side, comp_idx, pin_num) in *fid_resolved* and renders the
    geometry from the resolved symbol at the toeprint's board position.
    The toeprint position (from components_top/bot) is authoritative for
    WHERE to draw; the FID feature supplies only the geometry (symbol name,
    rotation, mirror).  If no toeprint is available the function returns
    False immediately.

    Only ONE pad shape is drawn per pin (the first successfully resolved
    feature) to avoid overlapping shapes from multiple copper/mask layers.

    Returns True if a patch was drawn.
    """
    # Position must come from the toeprint (components file), not the layer.
    if tp is None:
        return False

    px, py = tp.x, tp.y

    # Try both pin_idx (0-based) and pin_idx+1 (1-based) as the spec
    # can use either convention depending on the design tool.
    for pnum in (pin_idx, pin_idx + 1):
        key = (comp_side, comp_idx, pnum)
        pad_features = fid_resolved.get(key)
        if not pad_features:
            continue

        # Draw only the FIRST successfully resolved feature to avoid
        # overlapping pads from multiple layers (e.g. signal + solder mask).
        for rpf in pad_features:
            pad = rpf.pad
            sym = rpf.symbol

            if sym.name in user_symbols:
                patches = user_symbol_to_patches(
                    user_symbols[sym.name],
                    px, py,
                    pad.rotation, pad.mirror,
                    color, alpha,
                )
                for p in patches:
                    ax.add_patch(p)
                if patches:
                    return True
            else:
                patch = symbol_to_patch(
                    sym.name, px, py,
                    pad.rotation, pad.mirror,
                    rpf.units, sym.unit_override,
                    color, alpha, pad.resize_factor,
                )
                if patch is not None:
                    ax.add_patch(patch)
                    return True

    return False


# ---------------------------------------------------------------------------
# Shield-can helpers (sweep a circle along a polyline)
# ---------------------------------------------------------------------------

def _is_shield_can(comp: Component) -> bool:
    """Return True when *comp* looks like a shield-can (ref-des starts with SC)."""
    return comp.comp_name.upper().startswith("SC")


def _sweep_outline(
    points: list[tuple[float, float]],
    radius: float,
    n_cap: int = 16,
) -> tuple[np.ndarray, np.ndarray | None] | None:
    """Create a swept outline by moving a circle along a polyline.

    Offsets each segment by *radius* on both sides, joins interior corners
    with a miter, and caps open endpoints with semicircles.

    Returns ``(outer, inner)`` for closed polylines (ring shape) or
    ``(outline_verts, None)`` for open polylines.  Returns ``None`` when
    the input is degenerate.
    """
    pts = np.array(points, dtype=float)
    n = len(pts)
    if n < 2:
        return None

    # Detect closed polyline (last point ≈ first point)
    closed = n > 2 and np.linalg.norm(pts[0] - pts[-1]) < max(radius * 0.1, 0.01)
    if closed:
        pts = pts[:-1]
        n = len(pts)

    # Per-segment unit normals (perpendicular, pointing "left")
    num_segs = n if closed else n - 1
    seg_normals: list[np.ndarray] = []
    for i in range(num_segs):
        j = (i + 1) % n
        d = pts[j] - pts[i]
        length = np.linalg.norm(d)
        if length < 1e-12:
            seg_normals.append(np.array([0.0, 1.0]))
        else:
            seg_normals.append(np.array([-d[1], d[0]]) / length)

    # Compute miter offset at each vertex
    left_pts: list[np.ndarray] = []
    right_pts: list[np.ndarray] = []
    for i in range(n):
        if closed:
            n1 = seg_normals[(i - 1) % num_segs]
            n2 = seg_normals[i % num_segs]
        else:
            if i == 0:
                n1 = n2 = seg_normals[0]
            elif i == n - 1:
                n1 = n2 = seg_normals[-1]
            else:
                n1 = seg_normals[i - 1]
                n2 = seg_normals[i]

        bisector = n1 + n2
        bis_len = np.linalg.norm(bisector)
        if bis_len < 1e-12:
            # Antiparallel segments (180° turn) — use simple offset
            offset = n1 * radius
        else:
            bisector /= bis_len
            cos_half = np.dot(bisector, n1)
            miter_scale = 1.0 / max(cos_half, 0.25)   # clamp to avoid spikes
            offset = bisector * radius * miter_scale

        left_pts.append(pts[i] + offset)
        right_pts.append(pts[i] - offset)

    if closed:
        return np.array(left_pts), np.array(right_pts)

    # Open polyline — build a single polygon with semicircle end-caps
    outline: list[np.ndarray] = []

    # Left side forward
    outline.extend(left_pts)

    # End cap: semicircle from left[-1] to right[-1]
    d_end = pts[-1] - pts[-2]
    angle_end = math.atan2(d_end[1], d_end[0])
    for k in range(1, n_cap):
        theta = (angle_end + math.pi / 2) - k * math.pi / n_cap
        outline.append(
            pts[-1] + radius * np.array([math.cos(theta), math.sin(theta)])
        )

    # Right side backward
    outline.extend(reversed(right_pts))

    # Start cap: semicircle from right[0] to left[0]
    d_start = pts[1] - pts[0]
    angle_start = math.atan2(d_start[1], d_start[0])
    for k in range(1, n_cap):
        theta = (angle_start - math.pi / 2) - k * math.pi / n_cap
        outline.append(
            pts[0] + radius * np.array([math.cos(theta), math.sin(theta)])
        )

    return np.array(outline), None


def _chain_line_segments(lines) -> list[list[tuple[float, float]]]:
    """Chain line segments into ordered polylines.

    Returns a list of polylines; each polyline is an ordered list of
    ``(x, y)`` coordinate tuples.
    """
    if not lines:
        return []

    eps = 4  # decimal places for rounding

    # Build adjacency: rounded_endpoint → [(segment_idx, exact_other_end)]
    adj: dict[tuple[float, float], list[tuple[int, tuple[float, float]]]] = {}
    for i, line in enumerate(lines):
        s = (round(line.xs, eps), round(line.ys, eps))
        e = (round(line.xe, eps), round(line.ye, eps))
        adj.setdefault(s, []).append((i, (line.xe, line.ye)))
        adj.setdefault(e, []).append((i, (line.xs, line.ys)))

    used: set[int] = set()
    polylines: list[list[tuple[float, float]]] = []

    for start_idx in range(len(lines)):
        if start_idx in used:
            continue
        used.add(start_idx)
        line = lines[start_idx]
        chain: list[tuple[float, float]] = [(line.xs, line.ys), (line.xe, line.ye)]

        # Extend forward from tail
        while True:
            tail = (round(chain[-1][0], eps), round(chain[-1][1], eps))
            found = False
            for idx, other_end in adj.get(tail, []):
                if idx not in used:
                    used.add(idx)
                    chain.append(other_end)
                    found = True
                    break
            if not found:
                break

        # Extend backward from head
        while True:
            head = (round(chain[0][0], eps), round(chain[0][1], eps))
            found = False
            for idx, other_end in adj.get(head, []):
                if idx not in used:
                    used.add(idx)
                    chain.insert(0, other_end)
                    found = True
                    break
            if not found:
                break

        polylines.append(chain)

    return polylines


def _draw_shield_can(ax: Axes, comp: Component,
                     line_features: list, sym_lookup: dict,
                     units: str, color: str, alpha: float) -> bool:
    """Render a shield-can component as a swept polyline outline.

    Collects ``LineRecord`` features whose endpoints match the component's
    toeprint positions, chains them into polylines, and draws each as a
    swept circular outline.

    Returns True if at least one outline was drawn.
    """
    from src.models import LineRecord

    # Build set of toeprint positions for this component
    toep_set: set[tuple[float, float]] = set()
    for tp in comp.toeprints:
        toep_set.add((round(tp.x, 4), round(tp.y, 4)))

    if not toep_set:
        return False

    # Filter lines whose both endpoints match toeprint positions
    matching: list[LineRecord] = []
    for feat in line_features:
        if not isinstance(feat, LineRecord):
            continue
        s = (round(feat.xs, 4), round(feat.ys, 4))
        e = (round(feat.xe, 4), round(feat.ye, 4))
        if s in toep_set and e in toep_set:
            matching.append(feat)

    if not matching:
        return False

    # Get sweep radius from the line symbol
    sym_ref = sym_lookup.get(matching[0].symbol_idx)
    if sym_ref is None:
        return False
    width = get_line_width_for_symbol(sym_ref.name, units, sym_ref.unit_override)
    radius = width / 2
    if radius <= 0:
        return False

    # Chain segments and sweep
    polylines = _chain_line_segments(matching)
    drew = False

    for chain in polylines:
        result = _sweep_outline(chain, radius)
        if result is None:
            continue

        outer, inner = result
        if inner is not None:
            # Closed polyline → ring with hole
            n_out = len(outer)
            n_in = len(inner)

            verts: list[list[float]] = []
            codes: list[int] = []

            # Outer boundary
            verts.extend(outer.tolist())
            verts.append(outer[0].tolist())
            codes.append(MplPath.MOVETO)
            codes.extend([MplPath.LINETO] * (n_out - 1))
            codes.append(MplPath.CLOSEPOLY)

            # Inner boundary (reversed winding for hole)
            inner_rev = inner[::-1]
            verts.extend(inner_rev.tolist())
            verts.append(inner_rev[0].tolist())
            codes.append(MplPath.MOVETO)
            codes.extend([MplPath.LINETO] * (n_in - 1))
            codes.append(MplPath.CLOSEPOLY)

            path = MplPath(verts, codes)
            patch = PathPatch(path, facecolor=color, edgecolor="none",
                              alpha=alpha)
            ax.add_patch(patch)
            drew = True
        else:
            # Open polyline → single polygon with caps
            patch = Polygon(outer, closed=True, facecolor=color,
                            edgecolor="none", alpha=alpha)
            ax.add_patch(patch)
            drew = True

    return drew


# ---------------------------------------------------------------------------
# Outline / transform helpers
# ---------------------------------------------------------------------------

def _outline_to_patch(outline: PinOutline, comp: Component,
                      color: str, alpha: float,
                      filled: bool = True,
                      linestyle: str = "-",
                      is_bottom: bool = False):
    """Convert a PinOutline to a board-coordinate matplotlib patch.

    Args:
        is_bottom: True for bottom-layer components; inverts the effective
            mirror so that package-local geometry is correctly X-flipped.

    Returns None for unknown or degenerate shapes.
    """
    p = outline.params
    fc = color if filled else "none"

    # -- Circle (CR) or rounded/chamfered circle (CT) -----------------------
    if outline.type in ("CR", "CT"):
        xc, yc = _transform_point(
            p.get("xc", 0.0), p.get("yc", 0.0), comp,
            is_bottom=is_bottom)
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
        pts = _transform_pts(corners, comp, is_bottom=is_bottom)
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
        pts = _transform_pts(corners, comp, is_bottom=is_bottom)
        return Polygon(pts, closed=True,
                       facecolor=fc, edgecolor=color,
                       alpha=alpha, linewidth=0.4, linestyle=linestyle)

    # -- Complex contour (CONTOUR / OB) -------------------------------------
    if outline.type == "CONTOUR" and outline.contour is not None:
        verts = contour_to_vertices(outline.contour)
        if len(verts) < 2:
            return None
        pts = _transform_pts(verts, comp, is_bottom=is_bottom)
        return Polygon(pts, closed=True,
                       facecolor=fc, edgecolor=color,
                       alpha=alpha, linewidth=0.4, linestyle=linestyle)

    return None


def _transform_point(px: float, py: float,
                     comp: Component,
                     is_bottom: bool = False) -> tuple[float, float]:
    """Transform a single package-local point to board coordinates.

    ODB++ orient_def convention (mirror → rotate → translate):
      1. Mirror X in package space.
      2. Rotate CCW by comp.rotation.
      3. Translate to board position (comp.x, comp.y).

    For bottom-layer components (*is_bottom=True*) the effective mirror is
    inverted: mirror=False (normal bottom placement) means X-mirror is
    needed; mirror=True (extra flip) cancels the implicit bottom mirror.
    """
    # Step 1: compute effective mirror and apply X-flip in package space
    effective_mirror = (not comp.mirror) if is_bottom else comp.mirror
    lx = -px if effective_mirror else px
    ly = py
    # Step 2: CCW rotation
    angle = math.radians(comp.rotation)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    x_rot = lx * cos_a - ly * sin_a
    y_rot = lx * sin_a + ly * cos_a
    # Step 3: translate to board position
    return (x_rot + comp.x, y_rot + comp.y)


def _transform_pts(pts: np.ndarray, comp: Component,
                   is_bottom: bool = False) -> np.ndarray:
    """Transform an (N, 2) array of package-local points to board coordinates.

    ODB++ orient_def convention (mirror → rotate → translate):
      1. Mirror X in package space.
      2. Rotate CCW by comp.rotation.
      3. Translate to board position (comp.x, comp.y).

    For bottom-layer components (*is_bottom=True*) the effective mirror is
    inverted (see :func:`_transform_point` docstring).
    """
    out = pts.copy().astype(float)
    # Step 1: compute effective mirror and apply X-flip in package space
    effective_mirror = (not comp.mirror) if is_bottom else comp.mirror
    if effective_mirror:
        out[:, 0] = -out[:, 0]
    # Step 2: CCW rotation
    angle = math.radians(comp.rotation)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    x_rot = out[:, 0] * cos_a - out[:, 1] * sin_a
    y_rot = out[:, 0] * sin_a + out[:, 1] * cos_a
    # Step 3: translate to board position
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
                        pkg: Package | None,
                        is_bottom: bool = False) -> BBox | None:
    """Compute a board-coordinate bounding box for the fallback outline."""
    if pkg and pkg.bbox:
        bx = pkg.bbox
        hw = (bx.xmax - bx.xmin) / 2
        hh = (bx.ymax - bx.ymin) / 2
        corners = np.array([[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]])
        pts = _transform_pts(corners, comp, is_bottom=is_bottom)
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
