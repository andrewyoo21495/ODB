"""Viewer service: serialize layer geometry to JSON for the interactive viewer.

The web viewer is client-rendered (HTML5 Canvas): the backend computes a
layer's copper geometry once (reusing :mod:`copper_vector`), serializes it to
coordinate rings, and the frontend handles pan/zoom locally.

Layer/net geometry comes from shapely polygons; component pad geometry is
flattened from matplotlib pad patches (Agg backend forced for headless server
threads).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")  # headless — component pad patches built in server threads

from src.services import data_service

LogFn = Callable[[str], None]

_UNSAFE = '/\\:[]*?'


def safe_name(layer_name: str) -> str:
    out = layer_name
    for ch in _UNSAFE:
        out = out.replace(ch, "_")
    return out


# Geometry simplification tolerance (mm).  ~2µm — negligible at board scale but
# trims vertex counts to shrink the JSON payload.  Set 0 to disable.
SIMPLIFY_TOL = 0.002


def _simplify(geom):
    if geom is None or geom.is_empty or SIMPLIFY_TOL <= 0:
        return geom
    try:
        return geom.simplify(SIMPLIFY_TOL, preserve_topology=True)
    except Exception:
        return geom


def list_layers(cache_dir: str | Path, cache_name: str) -> list[dict]:
    """Return ``[{name, type}]`` for layers that have features (dropdown source).

    Reads the raw cache directly (no full feature reconstruction) for speed.
    """
    from src.cache_manager import load_cache, reconstruct_matrix_layers

    raw = load_cache(Path(cache_dir), cache_name)
    mls = {ml.name: ml for ml in reconstruct_matrix_layers(raw.get("matrix_layers", []))}
    names = [k[len("layer_features:"):] for k in raw if k.startswith("layer_features:")]
    names.sort(key=lambda n: mls[n].row if n in mls else 999)
    return [{"name": n, "type": (mls[n].type if n in mls else "")} for n in names]


def _ring(coords) -> list[list[float]]:
    return [[round(float(x), 4), round(float(y), 4)] for x, y in coords]


def _poly_to_obj(poly) -> dict:
    return {
        "exterior": _ring(poly.exterior.coords),
        "holes": [_ring(r.coords) for r in poly.interiors],
    }


def _geom_to_polys(geom) -> list[dict]:
    if geom is None or geom.is_empty:
        return []
    gt = geom.geom_type
    if gt == "Polygon":
        return [_poly_to_obj(geom)]
    if gt == "MultiPolygon":
        return [_poly_to_obj(p) for p in geom.geoms]
    if gt == "GeometryCollection":
        # May mix polygons with stray lines/points (from difference ops);
        # keep only the polygonal parts.
        out: list[dict] = []
        for g in geom.geoms:
            out.extend(_geom_to_polys(g))
        return out
    return []  # LineString / Point / etc. — not renderable as fill


_CATEGORY_COLOR = {
    "IC": "#1677ff",
    "Capacitor": "#52c41a",
    "Inductor": "#fa8c16",
    "Connector": "#722ed1",
    "SIM_Socket": "#13c2c2",
    "INP": "#eb2f96",
    "Unknown": "#8c8c8c",
}


def _profile_rings_and_bounds(profile):
    """Return (profile_rings, profile_bounds | None)."""
    from src.visualizer import copper_vector
    ppoly = copper_vector._profile_to_poly(profile) if profile else None
    rings = _geom_to_polys(ppoly)
    bounds = list(ppoly.bounds) if (ppoly is not None and not ppoly.is_empty) else None
    return rings, bounds


def list_nets(cache_dir: str | Path, cache_name: str, layer_name: str) -> list[str]:
    """Net names that have features on the given (signal) layer."""
    from src.visualizer import net_filter
    data = data_service.load_job(cache_dir, cache_name, log=lambda m: None)
    layers_data = data.get("layers_data", {})
    eda = data.get("eda_data")
    if not eda or layer_name not in layers_data:
        return []
    index = net_filter.build_net_feature_index(eda, layers_data)
    return net_filter.get_nets_for_layer(layer_name, index)


def build_net_geometry(cache_dir: str | Path, cache_name: str, layer_name: str,
                       net_name: str, out_path: Path, *,
                       log: LogFn | None = None) -> dict:
    """Geometry of a single net's features on one layer (filtered copper)."""
    _log = log if log is not None else (lambda m: None)
    from src.visualizer import copper_vector, net_filter

    data = data_service.load_job(cache_dir, cache_name, log=lambda m: None)
    layers_data = data.get("layers_data", {})
    if layer_name not in layers_data:
        raise KeyError(f"layer not found: {layer_name}")
    features, ml = layers_data[layer_name]
    user_symbols = data.get("user_symbols", {})

    index = net_filter.build_net_feature_index(data.get("eda_data"), layers_data)
    allowed = index.get(net_name, {}).get(layer_name, set())
    _log(f"net {net_name} on {layer_name}: {len(allowed)} features")
    filtered = net_filter.filter_layer_features(features, allowed)
    geom = _simplify(copper_vector._build_copper_geometry(filtered, user_symbols))
    polygons = _geom_to_polys(geom)

    profile_rings, pbounds = _profile_rings_and_bounds(data.get("profile"))
    bounds = (list(geom.bounds) if geom is not None and not geom.is_empty
              else (pbounds or [0.0, 0.0, 1.0, 1.0]))

    out = {"layer": layer_name, "type": ml.type, "net": net_name, "bounds": bounds,
           "profile": profile_rings, "polygons": polygons}
    Path(out_path).write_text(json.dumps(out), encoding="utf-8")
    return {"layer": layer_name, "net": net_name, "bounds": bounds,
            "n_polys": len(polygons), "geometry": Path(out_path).name}


def _outline_ring(outline, comp, is_bottom: bool):
    """Vertices of a package outline in board coordinates, or None."""
    import numpy as np
    from src.visualizer.component_overlay import transform_pts

    p = outline.params or {}
    t = outline.type
    if t in ("CR", "CT"):
        xc, yc, r = p.get("xc", 0.0), p.get("yc", 0.0), p.get("radius", 0.0)
        if r <= 0:
            return None
        ang = np.linspace(0, 2 * np.pi, 48, endpoint=False)
        pts = np.column_stack([xc + r * np.cos(ang), yc + r * np.sin(ang)])
    elif t == "RC":
        llx, lly = p.get("llx", 0.0), p.get("lly", 0.0)
        w, h = p.get("width", 0.0), p.get("height", 0.0)
        if w <= 0 or h <= 0:
            return None
        pts = np.array([[llx, lly], [llx + w, lly], [llx + w, lly + h], [llx, lly + h]])
    elif t == "SQ":
        xc, yc, hs = p.get("xc", 0.0), p.get("yc", 0.0), p.get("half_side", 0.0)
        if hs <= 0:
            return None
        pts = np.array([[xc - hs, yc - hs], [xc + hs, yc - hs],
                        [xc + hs, yc + hs], [xc - hs, yc + hs]])
    elif t == "CONTOUR" and outline.contour is not None:
        from src.visualizer.symbol_renderer import contour_to_vertices
        verts = contour_to_vertices(outline.contour)
        if len(verts) < 3:
            return None
        pts = np.asarray(verts)
    else:
        return None

    board = transform_pts(pts, comp, is_bottom=is_bottom)
    return [[round(float(x), 4), round(float(y), 4)] for x, y in board]


# Component-view colors mirror the legacy ``view-comp`` viewer (on a dark
# canvas): pads cyan (top) / pink (bottom), package outlines yellow, vias grey.
_PAD_COLOR_TOP = "#2BFFF4"
_PAD_COLOR_BOT = "#FC5BA1"
_OUTLINE_COLOR = "#FFFF00"
_VIA_COLOR = "#9e9e9e"


def _patch_to_ring(patch) -> dict | None:
    """Flatten a matplotlib pad patch (Circle/Polygon/Path/etc.) into a
    ``{exterior, holes}`` ring by sampling its path. Curves are tessellated by
    ``Path.to_polygons``; the largest sub-polygon is the exterior, the rest are
    treated as holes (e.g. donut pads)."""
    if patch is None:
        return None
    try:
        path = patch.get_path()
        polys = path.to_polygons(patch.get_patch_transform())
    except Exception:
        return None

    def _round(poly):
        return [[round(float(x), 4), round(float(y), 4)] for x, y in poly]

    def _area(poly):
        a = 0.0
        for i in range(len(poly)):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % len(poly)]
            a += x1 * y2 - x2 * y1
        return abs(a) / 2.0

    rings = [p for p in polys if len(p) >= 3]
    if not rings:
        return None
    rings.sort(key=_area, reverse=True)
    return {"exterior": _round(rings[0]), "holes": [_round(r) for r in rings[1:]]}


def _symbol_rings(symbol_name: str, x: float, y: float, rotation: float,
                  mirror: bool, units: str, unit_override, resize,
                  is_user: bool, user_symbols: dict) -> list[dict]:
    """Build polygon rings for one symbol instance via the matplotlib patch
    path (shared by pad and via rendering)."""
    from src.visualizer.symbol_renderer import symbol_to_patch, user_symbol_to_patches

    if is_user and symbol_name in user_symbols:
        patches = user_symbol_to_patches(
            user_symbols[symbol_name], x, y, rotation, mirror, "#000", 1.0,
        )
    else:
        patch = symbol_to_patch(
            symbol_name, x, y, rotation, mirror, units, unit_override,
            "#000", 1.0, resize,
        )
        patches = [patch] if patch is not None else []
    rings: list[dict] = []
    for p in patches:
        ring = _patch_to_ring(p)
        if ring:
            rings.append(ring)
    return rings


def _pad_rings(comp, is_bottom: bool, user_symbols: dict) -> list[dict]:
    """Pin-pad rings for one component, resolved from ``Toeprint.geom`` exactly
    as the legacy ``draw_components`` does (same rotation handling)."""
    out: list[dict] = []
    for tp in comp.toeprints:
        geom = tp.geom
        if geom is None:
            continue
        pad_rot = -geom.rotation if is_bottom else geom.rotation
        out.extend(_symbol_rings(
            geom.symbol_name, geom.x, geom.y, pad_rot, geom.mirror,
            geom.units, geom.unit_override, geom.resize_factor,
            geom.is_user_symbol, user_symbols,
        ))
    return out


def _via_rings(layers_data: dict, side: str, user_symbols: dict) -> list[dict]:
    """VIA pad rings on the side's outer signal layer (matches view-comp's
    'Show Via'). Returns [] if no vias / no signal layers."""
    from src.visualizer.fid_lookup import (
        _find_top_bottom_signal_layers, collect_via_pads_by_attribute,
    )

    vias = collect_via_pads_by_attribute(layers_data)
    if not vias:
        return []
    top_name, bot_name = _find_top_bottom_signal_layers(layers_data)
    want = top_name if side == "top" else bot_name
    if want is None:
        return []

    out: list[dict] = []
    for rpf in vias:
        if rpf.layer_name != want:
            continue
        pad = rpf.pad
        is_user = rpf.symbol.name in user_symbols
        out.extend(_symbol_rings(
            rpf.symbol.name, pad.x, pad.y, pad.rotation, pad.mirror,
            rpf.units, rpf.symbol.unit_override, None, is_user, user_symbols,
        ))
    return out


def build_component_geometry(cache_dir: str | Path, cache_name: str, side: str,
                             out_path: Path, *, log: LogFn | None = None) -> dict:
    """Component pads + package outlines for one side, matching the legacy
    ``view-comp`` look: pads cyan(top)/pink(bottom) filled, outlines yellow
    (stroke-only). Each polygon carries ``meta`` (refdes/part/category) for
    click-identify."""
    _log = log if log is not None else (lambda m: None)
    from src.checklist.component_classifier import classify_component

    data = data_service.load_job(cache_dir, cache_name, log=lambda m: None)
    comps = data.get("components_top" if side == "top" else "components_bot", [])
    eda = data.get("eda_data")
    user_symbols = data.get("user_symbols", {})
    packages = eda.packages if eda else []
    pkg_lookup = {i: pkg for i, pkg in enumerate(packages)}
    is_bottom = side == "bottom"
    pad_color = _PAD_COLOR_BOT if is_bottom else _PAD_COLOR_TOP

    polygons: list[dict] = []
    n_pads = n_outlines = 0
    for comp in comps:
        category = classify_component(comp).value
        meta = {"refdes": comp.comp_name or "", "part": comp.part_name or "",
                "category": category}
        # Package outlines (yellow, stroke-only).
        pkg = pkg_lookup.get(comp.pkg_ref)
        if pkg and getattr(pkg, "outlines", None):
            for outline in pkg.outlines:
                ring = _outline_ring(outline, comp, is_bottom)
                if ring:
                    polygons.append({"exterior": ring, "holes": [],
                                     "color": _OUTLINE_COLOR, "fill": False,
                                     "role": "outline", "meta": meta})
                    n_outlines += 1
        # Pin pads (cyan/pink, filled).
        for ring in _pad_rings(comp, is_bottom, user_symbols):
            ring["color"] = pad_color
            ring["role"] = "pad"
            ring["meta"] = meta
            polygons.append(ring)
            n_pads += 1

    # VIA pads on the side's outer signal layer (grey, filled).
    via_rings = _via_rings(data.get("layers_data", {}), side, user_symbols)
    for ring in via_rings:
        ring["color"] = _VIA_COLOR
        ring["role"] = "via"
        polygons.append(ring)

    points: list[list[float]] = []
    _log(f"{side}: {len(comps)} components, {n_outlines} outlines, "
         f"{n_pads} pads, {len(via_rings)} vias")

    profile_rings, pbounds = _profile_rings_and_bounds(data.get("profile"))
    if pbounds:
        bounds = pbounds
    elif polygons:
        xs = [pt[0] for poly in polygons for pt in poly["exterior"]]
        ys = [pt[1] for poly in polygons for pt in poly["exterior"]]
        bounds = [min(xs), min(ys), max(xs), max(ys)]
    else:
        bounds = [0.0, 0.0, 1.0, 1.0]

    out = {"side": side, "bounds": bounds, "profile": profile_rings,
           "polygons": polygons, "points": points}
    Path(out_path).write_text(json.dumps(out), encoding="utf-8")
    return {"side": side, "count": len(comps), "n_polys": len(polygons),
            "bounds": bounds, "geometry": Path(out_path).name}


def build_layer_geometry(cache_dir: str | Path, cache_name: str, layer_name: str,
                         out_path: Path, *, log: LogFn | None = None) -> dict:
    """Compute one layer's copper geometry, write it as JSON, return a summary.

    JSON shape: ``{layer, type, bounds:[minx,miny,maxx,maxy], profile:[ring..],
    polygons:[{exterior, holes}..]}``.
    """
    _log = log if log is not None else (lambda m: None)
    from src.visualizer import copper_vector

    data = data_service.load_job(cache_dir, cache_name, log=lambda m: None)
    layers_data = data.get("layers_data", {})
    if layer_name not in layers_data:
        raise KeyError(f"layer not found: {layer_name}")

    features, ml = layers_data[layer_name]
    user_symbols = data.get("user_symbols", {})

    _log(f"building geometry for {layer_name} ({len(features.features)} features)")
    geom = _simplify(copper_vector._build_copper_geometry(features, user_symbols))
    polygons = _geom_to_polys(geom)

    profile = data.get("profile")
    ppoly = copper_vector._profile_to_poly(profile) if profile else None
    profile_rings = _geom_to_polys(ppoly)

    if geom is not None and not geom.is_empty:
        bounds = list(geom.bounds)
    elif ppoly is not None and not ppoly.is_empty:
        bounds = list(ppoly.bounds)
    else:
        bounds = [0.0, 0.0, 1.0, 1.0]

    out = {
        "layer": layer_name,
        "type": ml.type,
        "bounds": bounds,
        "profile": profile_rings,
        "polygons": polygons,
    }
    Path(out_path).write_text(json.dumps(out), encoding="utf-8")

    return {
        "layer": layer_name,
        "type": ml.type,
        "bounds": bounds,
        "n_polys": len(polygons),
        "geometry": Path(out_path).name,
    }
