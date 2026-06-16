"""Job data service: cache building, cache ensuring, and job loading.

This module owns the *cache path* of the data layer — extracted from the CLI
(``main.py``) so that every interface (CLI, web API, MCP) shares one
implementation:

* :func:`build_cache` — parse an ODB++ archive and serialise it to JSON.
* :func:`ensure_cache` — build the cache only if it is missing.
* :func:`load_job` — reconstruct dataclass objects from the JSON cache.

Coordinate normalisation (INCH -> MM) and EDA/component scale calibration happen
inside :func:`build_cache` (at cache-build time), so :func:`load_job` returns
already-normalised data and does *not* re-calibrate.

The helpers :func:`_select_step` and :func:`_calibrate_eda_to_components` are
also used by the live-parse path in ``main.py`` (the viewers), so they live here
as shared utilities.
"""

from __future__ import annotations

import math
import statistics
import time
from pathlib import Path
from typing import Callable

from src import odb_loader
from src.cache_manager import (
    cache_job, load_cache,
    reconstruct_profile, reconstruct_eda_data, reconstruct_components,
    reconstruct_layer_features, reconstruct_matrix_layers,
    reconstruct_font, reconstruct_user_symbols,
)
from src.unit_converter import (
    INCH_TO_MM as _INCH_TO_MM,
    scale_components as _scale_components,
    scale_eda_data as _scale_eda_data,
    scale_profile as _scale_profile,
    scale_layer_features as _scale_layer_features,
    scale_user_symbols as _scale_user_symbols,
)

LogFn = Callable[[str], None]


def _select_step(job):
    """Return (step_name, step_paths) for the relevant step.

    For array-type data, selects the step named 'array'.
    For unit-type data, selects the first (and only) step.
    """
    if job.data_type == "array" and "array" in job.steps:
        name = "array"
    else:
        name = list(job.steps.keys())[0]
    return name, job.steps[name]


def _parse_attrlist_value(attrlist_path: Path, key: str) -> float | None:
    """Read a numeric value for *key* (e.g. '.copper_weight') from a layer attrlist file."""
    prefix = key if key.endswith("=") else key + "="
    try:
        with open(attrlist_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith(prefix):
                    return float(line.split("=", 1)[1].strip())
    except Exception:
        pass
    return None


def _calibrate_eda_to_components(components_top: list, components_bot: list,
                                 eda_data, log: LogFn | None = None) -> None:
    """Detect and correct any residual EDA package scale mismatch.

    After initial unit normalisation both EDA pin centers (package-local space)
    and toeprint positions (board space) should share the same unit.  This
    function verifies that assumption by comparing, per component, the maximum
    distance of a toeprint from the component centroid against the maximum
    distance of an EDA pin center from the package origin.  Rotation and mirror
    do not affect distance, so no transform is needed.

    If a consistent ×25.4 or ÷25.4 ratio is found, the EDA data is rescaled in
    place so that component geometry renders at the correct physical size.
    """
    _log = log if log is not None else print
    if not eda_data or not eda_data.packages:
        return

    pkg_lookup = {i: pkg for i, pkg in enumerate(eda_data.packages)}
    ratios: list[float] = []

    for comp in (components_top + components_bot):
        pkg = pkg_lookup.get(comp.pkg_ref)
        if not pkg or len(pkg.pins) < 2 or len(comp.toeprints) < 2:
            continue

        # Largest toeprint distance from component centroid (board coordinates)
        max_tp = max(
            math.sqrt((tp.x - comp.x) ** 2 + (tp.y - comp.y) ** 2)
            for tp in comp.toeprints
        )
        # Largest EDA pin distance from package origin (package-local coordinates)
        max_pin = max(
            math.sqrt(p.center.x ** 2 + p.center.y ** 2)
            for p in pkg.pins
        )

        if max_pin > 1e-9 and max_tp > 1e-9:
            ratios.append(max_tp / max_pin)

        if len(ratios) >= 30:
            break

    if not ratios:
        return

    ratio = statistics.median(ratios)

    if abs(ratio - 1.0) < 0.15:
        return  # Already in sync

    if 20.0 <= ratio <= 30.0:          # ≈ 25.4 → EDA is too small
        factor = 25.4
        direction = "×25.4"
    elif 0.030 <= ratio <= 0.060:      # ≈ 1/25.4 → EDA is too large
        factor = 1.0 / 25.4
        direction = "÷25.4"
    else:
        _log(f"  Warning: EDA/component scale ratio {ratio:.4f} is unexpected – skipping calibration")
        return

    _scale_eda_data(eda_data, factor)
    _log(f"  Units: EDA package geometry rescaled {direction} to match component coordinates (ratio={ratio:.3f})")


def _resolve_pin_geometries(data: dict, log: LogFn | None = None):
    """Resolve FID cross-references and store pad geometry in Toeprint.geom.

    Called during cache build after all unit normalisation is complete.
    This resolves each component pin's pad shape once so the viewer can
    render directly without re-resolving FID references at runtime.
    """
    _log = log if log is not None else print
    from src.models import PinGeometry
    from src.visualizer.fid_lookup import (
        build_fid_map, resolve_fid_features, _find_top_bottom_signal_layers,
    )

    eda = data["eda_data"]

    # Build temporary layers_data dict for FID resolution
    matrix_layers = data.get("matrix_layers", [])
    layer_lookup = {ml.name: ml for ml in matrix_layers}
    layers_data = {}
    for key in data:
        if key.startswith("layer_features:"):
            layer_name = key[len("layer_features:"):]
            ml = layer_lookup.get(layer_name)
            if ml:
                layers_data[layer_name] = (data[key], ml)

    if not layers_data:
        return

    fid_map = build_fid_map(eda)
    if not fid_map:
        return

    resolved = resolve_fid_features(fid_map, eda.layer_names, layers_data)
    if not resolved:
        return

    # Identify top/bottom signal layers so we can prefer the correct outer
    # layer pad when a toeprint has FID references to multiple layers
    # (e.g. through-hole pads appear on sigt, inner layers, and sigb).
    top_sig, bot_sig = _find_top_bottom_signal_layers(layers_data)

    # Collect user-defined symbol names for the is_user_symbol flag
    user_sym_names: set[str] = set()
    symbols = data.get("symbols")
    if symbols:
        if isinstance(symbols, dict):
            user_sym_names = set(symbols.keys())

    # Populate Toeprint.geom for each component
    populated = 0
    for side_key, side_char in (("components_top", "T"), ("components_bot", "B")):
        preferred_layer = top_sig if side_char == "T" else bot_sig
        comps = data.get(side_key, [])
        for comp in comps:
            for tp in comp.toeprints:
                # Try both pin_num directly and as 0-based index
                for pnum in (tp.pin_num, tp.pin_num - 1, tp.pin_num + 1):
                    key = (side_char, comp.comp_index, pnum)
                    pad_features = resolved.get(key)
                    if not pad_features:
                        continue
                    # Prefer the pad from the correct outer signal layer
                    # (sigt for top, sigb for bottom).  A toeprint can have
                    # FID references to multiple layers (outer + inner copper),
                    # so we must pick the outermost one, not just the first.
                    rpf = None
                    if preferred_layer:
                        rpf = next(
                            (f for f in pad_features
                             if f.layer_name == preferred_layer),
                            None,
                        )
                    if rpf is None:
                        rpf = pad_features[0]  # fallback: first available
                    tp.geom = PinGeometry(
                        symbol_name=rpf.symbol.name,
                        x=rpf.pad.x,
                        y=rpf.pad.y,
                        rotation=rpf.pad.rotation,
                        mirror=rpf.pad.mirror,
                        units=rpf.units,
                        resize_factor=rpf.pad.resize_factor,
                        unit_override=rpf.symbol.unit_override,
                        is_user_symbol=rpf.symbol.name in user_sym_names,
                    )
                    populated += 1
                    break  # stop trying alternative pin numbers

    _log(f"  FID: resolved pad geometry for {populated} toeprints")


def build_cache(odb_path: str | Path, cache_dir: str | Path, *,
                cache_name: str | None = None, log: LogFn | None = None) -> dict:
    """Parse an ODB++ archive and cache it to JSON files.

    Args:
        odb_path: path to the ODB++ ``.tgz`` archive.
        cache_dir: root cache directory (``cache/`` by default in the CLI).
        cache_name: cache folder name; defaults to the archive file stem.
        log: optional progress callback; defaults to ``print``.

    Returns:
        The in-memory ``data`` dict that was serialised (useful for callers
        that want to use the freshly-parsed data without reloading).
    """
    _log = log if log is not None else print

    odb_path = str(odb_path)
    _log(f"Loading ODB++ from: {odb_path}")
    t0 = time.time()

    job = odb_loader.load(odb_path)
    cache_dir = Path(cache_dir)

    # Use the input file name (without extension) as the cache folder name
    if cache_name is None:
        cache_name = Path(odb_path).stem

    _log(f"Job: {job.job_name}")
    _log(f"Cache directory: {cache_dir / cache_name}")

    data: dict = {}
    data["data_type"] = job.data_type
    _log(f"Data type: {job.data_type}")

    # Parse misc/info
    if job.misc_info_path:
        from src.parsers.misc_parser import parse_info
        info = parse_info(job.misc_info_path)
        data["job_info"] = info
        _log(f"  Parsed: misc/info")

    # Parse matrix
    layer_type_map: dict[str, str] = {}
    if job.matrix_path:
        from src.parsers.matrix_parser import parse_matrix
        steps, layers = parse_matrix(job.matrix_path)
        data["matrix_steps"] = steps
        data["matrix_layers"] = layers
        layer_type_map = {ml.name: ml.type for ml in layers}
        _log(f"  Parsed: matrix ({len(steps)} steps, {len(layers)} layers)")

    # Parse font
    if job.font_path:
        from src.parsers.font_parser import parse_font
        font = parse_font(job.font_path)
        data["font"] = font
        _log(f"  Parsed: fonts/standard ({len(font.characters)} characters)")

    # Parse the relevant step (unit: first step; array: step named "array")
    step_name, step_paths = _select_step(job)
    _log(f"\n  Step: {step_name}")

    # Step header
    if step_paths.stephdr:
        from src.parsers.stephdr_parser import parse_stephdr
        header = parse_stephdr(step_paths.stephdr)
        data["step_header"] = header
        _log(f"    Parsed: stephdr (units={header.units})")

    # Profile
    if step_paths.profile:
        from src.parsers.profile_parser import parse_profile
        profile = parse_profile(step_paths.profile)
        data["profile"] = profile
        _log(f"    Parsed: profile")

    # EDA data (unit only; array has no eda/ folder)
    if step_paths.eda_data:
        from src.parsers.eda_parser import parse_eda_data
        eda = parse_eda_data(step_paths.eda_data)
        data["eda_data"] = eda
        _log(f"    Parsed: eda/data ({len(eda.nets)} nets, {len(eda.packages)} packages)")

    # Netlist (unit only; array has no netlists/ folder)
    if step_paths.netlist_cadnet:
        from src.parsers.netlist_parser import parse_netlist
        netlist = parse_netlist(step_paths.netlist_cadnet)
        data["netlist"] = netlist
        _log(f"    Parsed: netlist ({len(netlist.net_names)} nets)")

    # Components and layer features
    from src.parsers.component_parser import parse_components
    from src.parsers.feature_parser import parse_features

    copper_data: dict[str, float] = {}

    for layer_name, layer_paths in step_paths.layers.items():
        # Components (unit only; array has no comp_+_* layers)
        if layer_paths.components:
            components, comp_units = parse_components(layer_paths.components)
            key = "components_top" if "top" in layer_name else "components_bot"
            data[key] = components
            # Store component units so they survive caching
            data[f"{key}_units"] = comp_units
            _log(f"    Parsed: {layer_name}/components ({len(components)} components, units={comp_units})")

        # Features
        if layer_paths.features:
            try:
                features = parse_features(layer_paths.features)
                data[f"layer_features:{layer_name}"] = features
                _log(f"    Parsed: {layer_name}/features ({len(features.features)} features)")
            except Exception as e:
                _log(f"    Warning: Failed to parse {layer_name}/features: {e}")

        # Thickness (Signal and Dielectric layers only)
        layer_type = layer_type_map.get(layer_name, "")
        if layer_paths.attrlist:
            if layer_type == "SIGNAL":
                cw = _parse_attrlist_value(layer_paths.attrlist, ".copper_weight")
                if cw is not None:
                    copper_data[layer_name] = cw / 1000.0
            elif layer_type == "DIELECTRIC":
                dt = _parse_attrlist_value(layer_paths.attrlist, ".layer_dielectric")
                if dt is not None:
                    copper_data[layer_name] = dt

    if copper_data:
        data["copper_data"] = copper_data
        _log(f"    Extracted copper weight for {len(copper_data)} layers")

    # Parse user-defined symbols
    if job.symbols:
        from src.parsers.symbol_parser import parse_all_symbols
        symbols = parse_all_symbols(job.symbols)
        data["symbols"] = symbols
        _log(f"\n  Parsed: {len(symbols)} user-defined symbols")

    # Parse stackup if available
    if job.stackup_path:
        from src.parsers.stackup_parser import parse_stackup
        try:
            stackup = parse_stackup(job.stackup_path)
            data["stackup"] = stackup
            _log(f"  Parsed: stackup.xml")
        except Exception as e:
            _log(f"  Warning: Failed to parse stackup.xml: {e}")

    # ------------------------------------------------------------------
    # Unit normalisation – convert all inch-based data to MM before
    # caching.  After this block every coordinate (components, EDA,
    # profile, layer features) is in millimetres.
    # ------------------------------------------------------------------

    # Normalise component placement coordinates (inches -> mm)
    for key in ("components_top", "components_bot"):
        comps = data.get(key)
        units_key = f"{key}_units"
        comp_units = data.get(units_key, "INCH")
        if comps and comp_units == "INCH":
            _scale_components(comps, _INCH_TO_MM)
            data[units_key] = "MM"
            _log(f"  Units: scaled {key} INCH -> MM (x25.4)")

    # Negate rotation angles for both layers so the cache stores negative
    # ODB++ CW-positive angles (e.g. 90° → -90°).
    for key in ("components_top", "components_bot"):
        comps = data.get(key)
        if comps:
            for comp in comps:
                comp.rotation = -comp.rotation
    _log(f"  Angles: negated component rotations for both layers")

    # Normalise EDA package geometry (inches -> mm)
    eda = data.get("eda_data")
    if eda and hasattr(eda, "units") and eda.units == "INCH":
        _scale_eda_data(eda, _INCH_TO_MM)
        _log(f"  Units: scaled EDA package data INCH -> MM (x25.4)")
        eda.units = "MM"

    # Cross-check: detect and correct any residual scale mismatch
    # between EDA pin centres and component toeprint positions.
    if eda:
        _calibrate_eda_to_components(
            data.get("components_top", []),
            data.get("components_bot", []),
            eda,
            log=_log,
        )

    # Normalise profile coordinates (inches -> mm)
    profile = data.get("profile")
    if profile and profile.units == "INCH":
        _scale_profile(profile, _INCH_TO_MM)
        profile.units = "MM"
        _log(f"  Units: scaled profile INCH -> MM (x25.4)")

    # Normalise layer feature coordinates (inches -> mm).
    # features.units is kept as the original file unit (INCH/MM) so that
    # the symbol renderer can correctly interpret symbol dimension encoding
    # (mils for INCH files, microns for MM files).
    for key in list(data.keys()):
        if key.startswith("layer_features:"):
            feats = data[key]
            if feats.units == "INCH":
                _scale_layer_features(feats, _INCH_TO_MM)
                _log(f"  Units: scaled {key} INCH -> MM (x25.4)")

    # Normalise user-defined symbol coordinates (inches -> mm).
    if data.get("symbols"):
        _scale_user_symbols(data["symbols"], _INCH_TO_MM)
        _log(f"  Units: scaled user-defined symbol coordinates INCH -> MM (x25.4)")

    # ------------------------------------------------------------------
    # Resolve FID cross-references and populate Toeprint.geom so that
    # the viewer can render pin pads without re-resolving at runtime.
    # ------------------------------------------------------------------
    eda = data.get("eda_data")
    if eda and eda.layer_names:
        _resolve_pin_geometries(data, log=_log)

    # Report identified top/bottom signal layers
    eda = data.get("eda_data")
    matrix_layers_list = data.get("matrix_layers", [])
    matrix_layers_map = {ml.name: ml for ml in matrix_layers_list} if matrix_layers_list else None
    if eda and eda.layer_names:
        from src.visualizer.fid_lookup import identify_signal_layers
        sig_map = identify_signal_layers(eda.layer_names, matrix_layers_map)
        sigt_name = sig_map.get("sigt", "N/A")
        sigb_name = sig_map.get("sigb", "N/A")
        _log(f"\n  Signal layers identified:")
        _log(f"    Top  (sigt): {sigt_name}")
        _log(f"    Bot  (sigb): {sigb_name}")

    # Write cache
    _log(f"\nWriting cache...")
    cache_job(cache_name, data, cache_dir)

    elapsed = time.time() - t0
    _log(f"\nDone! Cached in {elapsed:.1f}s")
    _log(f"Cache location: {cache_dir / cache_name}")

    job.cleanup()
    return data


def ensure_cache(odb_path: str | Path, cache_dir: str | Path,
                 *, log: LogFn | None = None) -> str:
    """Ensure a JSON cache exists for odb_path; build it automatically if missing.

    Returns the cache_name (stem of the ODB path).
    """
    _log = log if log is not None else print
    cache_name = Path(odb_path).stem
    cache_path = Path(cache_dir) / cache_name
    cache_files = list(cache_path.glob("*.json")) if cache_path.exists() else []
    if not cache_files:
        _log(f"No cache found at {cache_path}. Building cache first...")
        build_cache(odb_path, cache_dir, cache_name=cache_name, log=log)
    return cache_name


def load_job(cache_dir: str | Path, cache_name: str,
             *, log: LogFn | None = None) -> dict:
    """Load and reconstruct all job data from the JSON cache into dataclass objects."""
    _log = log if log is not None else print
    from src.models import JobInfo

    cache_dir = Path(cache_dir)
    _log(f"Loading from cache: {cache_dir / cache_name}")
    raw = load_cache(cache_dir, cache_name)
    if not raw:
        raise RuntimeError(f"Cache is empty or missing: {cache_dir / cache_name}")

    result: dict = {
        "job": None,
        "data_type": raw.get("data_type", "unit"),
        "components_top": [],
        "components_bot": [],
        "layers_data": {},
        "user_symbols": {},
    }

    if "profile" in raw:
        result["profile"] = reconstruct_profile(raw["profile"])
    if "eda_data" in raw:
        result["eda_data"] = reconstruct_eda_data(raw["eda_data"])
    if "components_top" in raw:
        result["components_top"] = reconstruct_components(raw["components_top"])
    if "components_bot" in raw:
        result["components_bot"] = reconstruct_components(raw["components_bot"])

    # Reconstruct layer features keyed by layer name
    matrix_layers = reconstruct_matrix_layers(raw.get("matrix_layers", []))
    layer_lookup = {ml.name: ml for ml in matrix_layers}
    for key, value in raw.items():
        if key.startswith("layer_features:"):
            layer_name = key[len("layer_features:"):]
            ml = layer_lookup.get(layer_name)
            if ml:
                result["layers_data"][layer_name] = (
                    reconstruct_layer_features(value), ml
                )

    if "font" in raw:
        result["font"] = reconstruct_font(raw["font"])
    if "symbols" in raw:
        result["user_symbols"] = reconstruct_user_symbols(raw["symbols"])

    if "job_info" in raw:
        ji = raw["job_info"]
        result["job_info"] = JobInfo(
            job_name=ji.get("job_name", ""),
            odb_version_major=ji.get("odb_version_major", 0),
            odb_version_minor=ji.get("odb_version_minor", 0),
            odb_source=ji.get("odb_source", ""),
            creation_date=ji.get("creation_date", ""),
            save_date=ji.get("save_date", ""),
            save_app=ji.get("save_app", ""),
            save_user=ji.get("save_user", ""),
            units=ji.get("units", "INCH"),
            max_uid=ji.get("max_uid", 0),
        )

    return result
