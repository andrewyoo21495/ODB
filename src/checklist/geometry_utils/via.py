"""VIA-on-Pad detection utilities.

Provides:
- build_via_position_set      — set of VIA board positions
- build_toeprint_lookup       — pin index → Toeprint mapping
- lookup_resolved_pads_for_pin
- count_vias_at_pad           — count VIAs within a pad's geometric boundary
"""

from __future__ import annotations

import math

import numpy as np

from src.models import Component, EdaData, Package, PadRecord, Pin, Toeprint
from src.visualizer.component_overlay import transform_point, transform_pts
from src.visualizer.symbol_renderer import contour_to_vertices
from src.parsers.symbol_resolver import resolve_symbol


def _build_via_positions_by_attribute(
    layers_data: dict,
    signal_layer_name: str,
) -> set[tuple[float, float]]:
    """Return VIA (x, y) positions on signal_layer_name using .pad_usage."""
    ld = layers_data.get(signal_layer_name)
    if ld is None:
        return set()

    lf = ld[0]
    via_text = lf.attr_texts.get(1)
    positions: set[tuple[float, float]] = set()

    for feat in lf.features:
        if not isinstance(feat, PadRecord):
            continue
        pu = feat.attributes.get(".pad_usage")
        if pu is None:
            continue
        if pu != via_text and pu != "1":
            continue
        positions.add((round(feat.x, 4), round(feat.y, 4)))

    return positions


def _build_via_positions_by_subnet(
    eda_data: EdaData,
    layers_data: dict,
    signal_layer_name: str,
) -> set[tuple[float, float]]:
    """Return VIA (x, y) positions on signal_layer_name via EDA subnet FIDs."""
    layer_name_map: dict[int, str] = {}
    for idx, name in enumerate(eda_data.layer_names):
        layer_name_map[idx] = name

    positions: set[tuple[float, float]] = set()

    for net in eda_data.nets:
        for subnet in net.subnets:
            if subnet.type != "VIA":
                continue
            for fid in subnet.feature_ids:
                if fid.type != "C":
                    continue
                layer_name = layer_name_map.get(fid.layer_idx)
                if layer_name != signal_layer_name:
                    continue
                ld = layers_data.get(layer_name)
                if ld is None:
                    continue
                features = ld[0].features
                if fid.feature_idx < 0 or fid.feature_idx >= len(features):
                    continue
                feat = features[fid.feature_idx]
                if not isinstance(feat, PadRecord):
                    continue
                positions.add((round(feat.x, 4), round(feat.y, 4)))

    return positions


def build_via_position_set(
    eda_data: EdaData,
    layers_data: dict,
    is_bottom: bool = False,
) -> set[tuple[float, float]]:
    """Return deduplicated (x, y) board positions of VIAs on one surface.

    Unions results from the .pad_usage attribute method and the EDA VIA
    subnet FID method.
    """
    from src.visualizer.fid_lookup import _find_top_bottom_signal_layers

    top_name, bot_name = _find_top_bottom_signal_layers(layers_data)
    target_name = bot_name if is_bottom else top_name
    if target_name is None:
        return set()

    positions: set[tuple[float, float]] = set()
    positions.update(_build_via_positions_by_attribute(layers_data, target_name))
    positions.update(_build_via_positions_by_subnet(eda_data, layers_data, target_name))

    return positions


def build_toeprint_lookup(
    comp: Component,
    pkg: Package,
) -> dict[int, Toeprint]:
    """Build a reliable mapping from package pin index to toeprint.

    Strategy 1: match toeprint.name to pin.name.
    Strategy 2: use toeprint.pin_num as the pin index.
    """
    result: dict[int, Toeprint] = {}

    tp_by_name: dict[str, Toeprint] = {}
    for tp in comp.toeprints:
        if tp.name:
            tp_by_name[tp.name] = tp

    if tp_by_name:
        for pin_idx, pin in enumerate(pkg.pins):
            tp = tp_by_name.get(pin.name)
            if tp is not None:
                result[pin_idx] = tp

    if len(result) < len(pkg.pins):
        tp_by_num: dict[int, Toeprint] = {}
        for tp in comp.toeprints:
            tp_by_num[tp.pin_num] = tp
        for pin_idx in range(len(pkg.pins)):
            if pin_idx not in result:
                tp = tp_by_num.get(pin_idx)
                if tp is not None:
                    result[pin_idx] = tp

    return result


def lookup_resolved_pads_for_pin(
    fid_resolved: dict,
    comp: Component,
    is_bottom: bool,
    pin_idx: int,
    signal_layer_name: str | None = None,
) -> list | None:
    """Look up FID-resolved pad features for a specific pin.

    Searches fid_resolved using both 0-based and 1-based pin numbering.
    Optionally filters to features on signal_layer_name.
    Returns a list of ResolvedPadFeature or None.
    """
    side = "B" if is_bottom else "T"
    comp_idx = comp.comp_index

    for pnum in (pin_idx, pin_idx + 1):
        key = (side, comp_idx, pnum)
        pad_features = fid_resolved.get(key)
        if not pad_features:
            continue
        if signal_layer_name is not None:
            filtered = [rpf for rpf in pad_features
                        if rpf.layer_name == signal_layer_name]
            if filtered:
                return filtered
        else:
            return pad_features

    return None


def _symbol_to_polygon(
    symbol_name: str,
    x: float, y: float,
    rotation: float = 0.0,
    mirror: bool = False,
    units: str = "INCH",
    unit_override: str = None,
    resize_factor: float = None,
    num_circle_pts: int = 32,
) -> np.ndarray | None:
    """Convert a standard symbol to board-coordinate polygon vertices.

    Returns an (N, 2) array of polygon vertices or None for unsupported types.
    """
    from src.visualizer.symbol_renderer import (
        _get_scale_factor, _mirror_points, _rotate_points,
    )

    sym = resolve_symbol(symbol_name)
    scale = _get_scale_factor(units, unit_override)
    if resize_factor is not None and resize_factor != 0.0:
        scale *= resize_factor

    if sym.type == "round":
        d = sym.params["diameter"] * scale
        r = d / 2
        angles = np.linspace(0, 2 * np.pi, num_circle_pts, endpoint=False)
        return np.column_stack([x + r * np.cos(angles),
                                y + r * np.sin(angles)])

    if sym.type == "square":
        s = sym.params["side"] * scale
        corners = np.array([
            [x - s/2, y - s/2], [x + s/2, y - s/2],
            [x + s/2, y + s/2], [x - s/2, y + s/2],
        ])
        if mirror:
            corners = _mirror_points(corners, x)
        if rotation:
            corners = _rotate_points(corners, x, y, rotation)
        return corners

    if sym.type in ("rect", "rect_round", "rect_chamfer"):
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        corners = np.array([
            [x - w/2, y - h/2], [x + w/2, y - h/2],
            [x + w/2, y + h/2], [x - w/2, y + h/2],
        ])
        if mirror:
            corners = _mirror_points(corners, x)
        if rotation:
            corners = _rotate_points(corners, x, y, rotation)
        return corners

    if sym.type == "oval":
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        hw, hh = w/2, h/2
        angles = np.linspace(0, 2 * np.pi, num_circle_pts, endpoint=False)
        pts = np.column_stack([x + hw * np.cos(angles),
                               y + hh * np.sin(angles)])
        if mirror:
            pts = _mirror_points(pts, x)
        if rotation:
            pts = _rotate_points(pts, x, y, rotation)
        return pts

    if sym.type == "diamond":
        w = sym.params["width"] * scale / 2
        h = sym.params["height"] * scale / 2
        verts = np.array([
            [x, y + h], [x + w, y], [x, y - h], [x - w, y],
        ])
        if mirror:
            verts = _mirror_points(verts, x)
        if rotation:
            verts = _rotate_points(verts, x, y, rotation)
        return verts

    if sym.type == "octagon":
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        cs = sym.params["corner_size"] * scale
        from src.visualizer.symbol_renderer import _octagon_vertices
        verts = _octagon_vertices(x, y, w, h, cs)
        if mirror:
            verts = _mirror_points(verts, x)
        if rotation:
            verts = _rotate_points(verts, x, y, rotation)
        return verts

    if sym.type == "user_defined":
        return None

    if sym.type in ("donut_r",):
        od = sym.params["outer_diameter"] * scale
        r = od / 2
        angles = np.linspace(0, 2 * np.pi, num_circle_pts, endpoint=False)
        return np.column_stack([x + r * np.cos(angles),
                                y + r * np.sin(angles)])

    if sym.type in ("donut_s", "donut_s_round", "donut_sr"):
        od = sym.params["outer_size"] * scale
        s = od / 2
        corners = np.array([
            [x - s, y - s], [x + s, y - s],
            [x + s, y + s], [x - s, y + s],
        ])
        if mirror:
            corners = _mirror_points(corners, x)
        if rotation:
            corners = _rotate_points(corners, x, y, rotation)
        return corners

    if sym.type in ("donut_rc", "donut_rc_round", "donut_o"):
        ow = sym.params["outer_width"] * scale
        oh = sym.params["outer_height"] * scale
        corners = np.array([
            [x - ow/2, y - oh/2], [x + ow/2, y - oh/2],
            [x + ow/2, y + oh/2], [x - ow/2, y + oh/2],
        ])
        if mirror:
            corners = _mirror_points(corners, x)
        if rotation:
            corners = _rotate_points(corners, x, y, rotation)
        return corners

    if sym.type == "ellipse":
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        angles = np.linspace(0, 2 * np.pi, num_circle_pts, endpoint=False)
        pts = np.column_stack([x + w/2 * np.cos(angles),
                               y + h/2 * np.sin(angles)])
        if mirror:
            pts = _mirror_points(pts, x)
        if rotation:
            pts = _rotate_points(pts, x, y, rotation)
        return pts

    return None


def _get_pad_polygon_board(
    pin: Pin,
    comp: Component,
    is_bottom: bool = False,
    num_circle_pts: int = 32,
) -> np.ndarray | None:
    """Return the EDA pin outline as board-coordinate vertices (fallback).

    Returns None if the pin has no outlines or the outline is degenerate.
    """
    if not pin.outlines:
        return None

    ol = pin.outlines[0]
    p = ol.params

    if ol.type in ("CR", "CT"):
        xc = p.get("xc", 0.0)
        yc = p.get("yc", 0.0)
        r = p.get("radius", 0.0)
        if r <= 0:
            return None
        angles = np.linspace(0, 2 * np.pi, num_circle_pts, endpoint=False)
        local_pts = np.column_stack([
            xc + r * np.cos(angles),
            yc + r * np.sin(angles),
        ])
    elif ol.type == "RC":
        llx = p.get("llx", 0.0)
        lly = p.get("lly", 0.0)
        w = p.get("width", 0.0)
        h = p.get("height", 0.0)
        if w <= 0 or h <= 0:
            return None
        local_pts = np.array([
            [llx,     lly],
            [llx + w, lly],
            [llx + w, lly + h],
            [llx,     lly + h],
        ])
    elif ol.type == "SQ":
        xc = p.get("xc", 0.0)
        yc = p.get("yc", 0.0)
        hs = p.get("half_side", 0.0)
        if hs <= 0:
            return None
        local_pts = np.array([
            [xc - hs, yc - hs],
            [xc + hs, yc - hs],
            [xc + hs, yc + hs],
            [xc - hs, yc + hs],
        ])
    elif ol.type == "CONTOUR" and ol.contour is not None:
        local_pts = contour_to_vertices(ol.contour)
        if len(local_pts) < 3:
            return None
    else:
        return None

    return transform_pts(local_pts, comp, is_bottom=is_bottom)


def _point_in_polygon(px: float, py: float, verts: np.ndarray) -> bool:
    """Ray-casting point-in-polygon test.

    verts is an (N, 2) array of polygon vertices (closed automatically).
    """
    n = len(verts)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = verts[i]
        xj, yj = verts[j]
        if ((yi > py) != (yj > py)) and \
           (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _resolved_pad_polygon(
    rpf,
    is_bottom: bool = False,
) -> np.ndarray | None:
    """Convert a FID-resolved pad feature to board-coordinate polygon vertices."""
    pad = rpf.pad
    sym = rpf.symbol
    pad_rot = -pad.rotation if is_bottom else pad.rotation
    return _symbol_to_polygon(
        sym.name, pad.x, pad.y,
        rotation=pad_rot,
        mirror=pad.mirror,
        units=rpf.units,
        unit_override=sym.unit_override,
        resize_factor=pad.resize_factor,
    )


def count_vias_at_pad(
    comp: Component,
    pin_center_x: float,
    pin_center_y: float,
    via_positions: set[tuple[float, float]],
    is_bottom: bool = False,
    tolerance: float = 0.05,
    toeprint: Toeprint | None = None,
    pin: Pin | None = None,
    resolved_pads: list | None = None,
) -> int:
    """Count VIAs that fall within a pad's geometric boundary.

    Resolution priority:
      1. FID-resolved pad geometry (resolved_pads)
      2. EDA pin outline geometry (pin)
      3. Centre-distance fallback (tolerance)
    """
    if resolved_pads:
        count = 0
        for rpf in resolved_pads:
            poly = _resolved_pad_polygon(rpf, is_bottom=is_bottom)
            if poly is None:
                continue
            xmin, ymin = poly.min(axis=0)
            xmax, ymax = poly.max(axis=0)
            for vx, vy in via_positions:
                if vx < xmin or vx > xmax or vy < ymin or vy > ymax:
                    continue
                if _point_in_polygon(vx, vy, poly):
                    count += 1
            if count > 0:
                return count

    poly = None
    if pin is not None:
        poly = _get_pad_polygon_board(pin, comp, is_bottom=is_bottom)

    if poly is not None:
        xmin, ymin = poly.min(axis=0)
        xmax, ymax = poly.max(axis=0)
        count = 0
        for vx, vy in via_positions:
            if vx < xmin or vx > xmax or vy < ymin or vy > ymax:
                continue
            if _point_in_polygon(vx, vy, poly):
                count += 1
        return count

    if toeprint is not None:
        bx, by = toeprint.x, toeprint.y
    else:
        bx, by = transform_point(pin_center_x, pin_center_y, comp,
                                  is_bottom=is_bottom)
    count = 0
    tol_sq = tolerance * tolerance
    for vx, vy in via_positions:
        dx = bx - vx
        dy = by - vy
        if dx * dx + dy * dy <= tol_sq:
            count += 1
    return count
