"""ODB++ Processing System - CLI Entry Point.

Usage:
    python main.py cache              <odb_path>                         Parse and cache to JSON
    python main.py view               <odb_path> [--layers L1 L2 ...]    Launch visualizer
    python main.py view-comp          <odb_path>                         Launch component viewer
    python main.py check              <odb_path> [--rules R1 R2 ...]     Run checklist
    python main.py info               <odb_path>                         Print job summary
    python main.py copper             <odb_path>                         Display layer thickness
    python main.py copper-ratio       <odb_path>                         Launch copper ratio viewer
    python main.py copper-calculate                                       Launch copper ratio batch calculator
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
import time
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent))

from src import odb_loader
from src.cache_manager import (
    cache_job, cache_layer, is_cache_valid, load_cache,
    reconstruct_profile, reconstruct_eda_data, reconstruct_components,
    reconstruct_layer_features, reconstruct_matrix_layers,
    reconstruct_font, reconstruct_user_symbols,
)
from src.models import (
    ArcRecord, ArcSegment, BarcodeRecord, LineRecord,
    LineSegment, PadRecord, SurfaceRecord, TextRecord,
)


# ---------------------------------------------------------------------------
# Unit normalisation helpers
# ---------------------------------------------------------------------------

_INCH_TO_MM = 25.4


def _unit_scale(from_units: str, to_units: str) -> float:
    """Return the multiplier to convert *from_units* coordinates to *to_units*."""
    if from_units == to_units:
        return 1.0
    if from_units == "INCH" and to_units == "MM":
        return 25.4
    if from_units == "MM" and to_units == "INCH":
        return 1.0 / 25.4
    return 1.0


def _scale_components(comps: list, factor: float) -> None:
    """Scale component board coordinates (x, y and toeprint positions) in place."""
    for comp in comps:
        comp.x *= factor
        comp.y *= factor
        for tp in comp.toeprints:
            tp.x *= factor
            tp.y *= factor



def _scale_outline_params(outline, factor: float) -> None:
    """Scale a PinOutline's coordinate parameters in place."""
    p = outline.params
    if outline.type == "RC":
        for k in ("llx", "lly", "width", "height"):
            if k in p:
                p[k] *= factor
    elif outline.type in ("CR", "CT"):
        for k in ("xc", "yc", "radius"):
            if k in p:
                p[k] *= factor
    elif outline.type == "SQ":
        for k in ("xc", "yc", "half_side"):
            if k in p:
                p[k] *= factor
    elif outline.type == "CONTOUR" and outline.contour:
        c = outline.contour
        c.start.x *= factor
        c.start.y *= factor
        for seg in c.segments:
            if isinstance(seg, LineSegment):
                seg.end.x *= factor
                seg.end.y *= factor
            elif isinstance(seg, ArcSegment):
                seg.end.x *= factor
                seg.end.y *= factor
                seg.center.x *= factor
                seg.center.y *= factor


def _scale_eda_data(eda, factor: float) -> None:
    """Scale EDA package coordinate data (bounding boxes, pin centres, outlines) in place."""
    for pkg in eda.packages:
        if pkg.bbox:
            pkg.bbox.xmin *= factor
            pkg.bbox.xmax *= factor
            pkg.bbox.ymin *= factor
            pkg.bbox.ymax *= factor
        pkg.pitch *= factor
        for pin in pkg.pins:
            pin.center.x *= factor
            pin.center.y *= factor
            pin.finished_hole_size *= factor
            for ol in pin.outlines:
                _scale_outline_params(ol, factor)
        for ol in pkg.outlines:
            _scale_outline_params(ol, factor)


def _scale_profile(profile, factor: float) -> None:
    """Scale profile surface coordinates in place."""
    if not profile or not profile.surface:
        return
    for contour in profile.surface.contours:
        contour.start.x *= factor
        contour.start.y *= factor
        for seg in contour.segments:
            seg.end.x *= factor
            seg.end.y *= factor
            if isinstance(seg, ArcSegment):
                seg.center.x *= factor
                seg.center.y *= factor


def _scale_layer_features(features, factor: float) -> None:
    """Scale all feature coordinates in place."""
    for feat in features.features:
        if isinstance(feat, LineRecord):
            feat.xs *= factor
            feat.ys *= factor
            feat.xe *= factor
            feat.ye *= factor
        elif isinstance(feat, PadRecord):
            feat.x *= factor
            feat.y *= factor
        elif isinstance(feat, ArcRecord):
            feat.xs *= factor
            feat.ys *= factor
            feat.xe *= factor
            feat.ye *= factor
            feat.xc *= factor
            feat.yc *= factor
        elif isinstance(feat, TextRecord):
            feat.x *= factor
            feat.y *= factor
            feat.xsize *= factor
            feat.ysize *= factor
        elif isinstance(feat, BarcodeRecord):
            feat.x *= factor
            feat.y *= factor
            feat.width *= factor
            feat.height *= factor
        elif isinstance(feat, SurfaceRecord):
            for contour in feat.contours:
                contour.start.x *= factor
                contour.start.y *= factor
                for seg in contour.segments:
                    seg.end.x *= factor
                    seg.end.y *= factor
                    if isinstance(seg, ArcSegment):
                        seg.center.x *= factor
                        seg.center.y *= factor


def _scale_user_symbols(user_symbols: dict, factor: float) -> None:
    """Scale contour coordinates of all user-defined symbols in place."""
    from src.models import SurfaceRecord, ArcSegment
    for symbol in user_symbols.values():
        if symbol.units == "INCH":
            for feat in symbol.features:
                if isinstance(feat, SurfaceRecord):
                    for contour in feat.contours:
                        contour.start.x *= factor
                        contour.start.y *= factor
                        for seg in contour.segments:
                            seg.end.x *= factor
                            seg.end.y *= factor
                            if isinstance(seg, ArcSegment):
                                seg.center.x *= factor
                                seg.center.y *= factor
            symbol.units = "MM"


def _calibrate_eda_to_components(components_top: list, components_bot: list,
                                   eda_data) -> None:
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
        print(f"  Warning: EDA/component scale ratio {ratio:.4f} is unexpected – skipping calibration")
        return

    _scale_eda_data(eda_data, factor)
    print(f"  Units: EDA package geometry rescaled {direction} to match component coordinates (ratio={ratio:.3f})")


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


def cmd_info(args):
    """Print job summary information."""
    job = odb_loader.load(args.odb_path)

    print(f"{'='*60}")
    print(f"ODB++ Job: {job.job_name}")
    print(f"Root: {job.root_dir}")
    print(f"Data Type: {job.data_type.upper()}")
    print(f"{'='*60}")

    # Parse misc/info
    if job.misc_info_path:
        from src.parsers.misc_parser import parse_info
        info = parse_info(job.misc_info_path)
        print(f"ODB++ Version: {info.odb_version_major}.{info.odb_version_minor}")
        print(f"Source: {info.odb_source}")
        print(f"Created: {info.creation_date}")
        print(f"Saved: {info.save_date} by {info.save_app} ({info.save_user})")
        print(f"Units: {info.units}")
        print(f"Max UID: {info.max_uid}")

    # Parse matrix
    if job.matrix_path:
        from src.parsers.matrix_parser import parse_matrix
        steps, layers = parse_matrix(job.matrix_path)

        print(f"\nSteps ({len(steps)}):")
        for step in steps:
            print(f"  [{step.col}] {step.name}")

        print(f"\nLayers ({len(layers)}):")
        for layer in layers:
            type_str = f"{layer.type}"
            if layer.add_type:
                type_str += f" ({layer.add_type})"
            form_str = f" [{layer.form}]" if layer.form else ""
            print(f"  [{layer.row:3d}] {layer.name:<30s} {type_str}{form_str}")

    # Steps summary
    print(f"\nDiscovered Steps: {list(job.steps.keys())}")
    for step_name, step_paths in job.steps.items():
        layer_count = len(step_paths.layers)
        print(f"  {step_name}: {layer_count} layers")
        if step_paths.eda_data:
            print(f"    EDA data: Yes")
        if step_paths.netlist_cadnet:
            print(f"    Netlist: Yes")

    print(f"\nUser-defined Symbols: {len(job.symbols)}")
    print(f"Wheels: {len(job.wheels)}")

    job.cleanup()


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


def cmd_cache(args):
    """Parse ODB++ data and cache to JSON files."""
    print(f"Loading ODB++ from: {args.odb_path}")
    t0 = time.time()

    job = odb_loader.load(args.odb_path)
    cache_dir = Path(args.cache_dir) if args.cache_dir else Path("cache")

    # Use the input file name (without extension) as the cache folder name
    cache_name = Path(args.odb_path).stem

    print(f"Job: {job.job_name}")
    print(f"Cache directory: {cache_dir / cache_name}")

    data = {}
    data["data_type"] = job.data_type
    print(f"Data type: {job.data_type}")

    # Parse misc/info
    if job.misc_info_path:
        from src.parsers.misc_parser import parse_info
        info = parse_info(job.misc_info_path)
        data["job_info"] = info
        print(f"  Parsed: misc/info")

    # Parse matrix
    layer_type_map: dict[str, str] = {}
    if job.matrix_path:
        from src.parsers.matrix_parser import parse_matrix
        steps, layers = parse_matrix(job.matrix_path)
        data["matrix_steps"] = steps
        data["matrix_layers"] = layers
        layer_type_map = {ml.name: ml.type for ml in layers}
        print(f"  Parsed: matrix ({len(steps)} steps, {len(layers)} layers)")

    # Parse font
    if job.font_path:
        from src.parsers.font_parser import parse_font
        font = parse_font(job.font_path)
        data["font"] = font
        print(f"  Parsed: fonts/standard ({len(font.characters)} characters)")

    # Parse the relevant step (unit: first step; array: step named "array")
    step_name, step_paths = _select_step(job)
    print(f"\n  Step: {step_name}")

    # Step header
    if step_paths.stephdr:
        from src.parsers.stephdr_parser import parse_stephdr
        header = parse_stephdr(step_paths.stephdr)
        data["step_header"] = header
        print(f"    Parsed: stephdr (units={header.units})")

    # Profile
    if step_paths.profile:
        from src.parsers.profile_parser import parse_profile
        profile = parse_profile(step_paths.profile)
        data["profile"] = profile
        print(f"    Parsed: profile")

    # EDA data (unit only; array has no eda/ folder)
    if step_paths.eda_data:
        from src.parsers.eda_parser import parse_eda_data
        eda = parse_eda_data(step_paths.eda_data)
        data["eda_data"] = eda
        print(f"    Parsed: eda/data ({len(eda.nets)} nets, {len(eda.packages)} packages)")

    # Netlist (unit only; array has no netlists/ folder)
    if step_paths.netlist_cadnet:
        from src.parsers.netlist_parser import parse_netlist
        netlist = parse_netlist(step_paths.netlist_cadnet)
        data["netlist"] = netlist
        print(f"    Parsed: netlist ({len(netlist.net_names)} nets)")

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
            print(f"    Parsed: {layer_name}/components ({len(components)} components, units={comp_units})")

        # Features
        if layer_paths.features:
            try:
                features = parse_features(layer_paths.features)
                data[f"layer_features:{layer_name}"] = features
                print(f"    Parsed: {layer_name}/features ({len(features.features)} features)")
            except Exception as e:
                print(f"    Warning: Failed to parse {layer_name}/features: {e}")

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
        print(f"    Extracted copper weight for {len(copper_data)} layers")

    # Parse user-defined symbols
    if job.symbols:
        from src.parsers.symbol_parser import parse_all_symbols
        symbols = parse_all_symbols(job.symbols)
        data["symbols"] = symbols
        print(f"\n  Parsed: {len(symbols)} user-defined symbols")

    # Parse stackup if available
    if job.stackup_path:
        from src.parsers.stackup_parser import parse_stackup
        try:
            stackup = parse_stackup(job.stackup_path)
            data["stackup"] = stackup
            print(f"  Parsed: stackup.xml")
        except Exception as e:
            print(f"  Warning: Failed to parse stackup.xml: {e}")

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
            print(f"  Units: scaled {key} INCH -> MM (x25.4)")

    # Negate rotation angles for both layers so the cache stores negative
    # ODB++ CW-positive angles (e.g. 90° → -90°).
    for key in ("components_top", "components_bot"):
        comps = data.get(key)
        if comps:
            for comp in comps:
                comp.rotation = -comp.rotation
    print(f"  Angles: negated component rotations for both layers")

    # Normalise EDA package geometry (inches -> mm)
    eda = data.get("eda_data")
    if eda and hasattr(eda, "units") and eda.units == "INCH":
        _scale_eda_data(eda, _INCH_TO_MM)
        print(f"  Units: scaled EDA package data INCH -> MM (x25.4)")
        eda.units = "MM"

    # Cross-check: detect and correct any residual scale mismatch
    # between EDA pin centres and component toeprint positions.
    if eda:
        _calibrate_eda_to_components(
            data.get("components_top", []),
            data.get("components_bot", []),
            eda,
        )

    # Normalise profile coordinates (inches -> mm)
    profile = data.get("profile")
    if profile and profile.units == "INCH":
        _scale_profile(profile, _INCH_TO_MM)
        profile.units = "MM"
        print(f"  Units: scaled profile INCH -> MM (x25.4)")

    # Normalise layer feature coordinates (inches -> mm).
    # features.units is kept as the original file unit (INCH/MM) so that
    # the symbol renderer can correctly interpret symbol dimension encoding
    # (mils for INCH files, microns for MM files).
    for key in list(data.keys()):
        if key.startswith("layer_features:"):
            feats = data[key]
            if feats.units == "INCH":
                _scale_layer_features(feats, _INCH_TO_MM)
                print(f"  Units: scaled {key} INCH -> MM (x25.4)")

    # Normalise user-defined symbol coordinates (inches -> mm).
    if data.get("symbols"):
        _scale_user_symbols(data["symbols"], _INCH_TO_MM)
        print(f"  Units: scaled user-defined symbol coordinates INCH -> MM (x25.4)")

    # Write cache
    print(f"\nWriting cache...")
    cache_job(cache_name, data, cache_dir)

    elapsed = time.time() - t0
    print(f"\nDone! Cached in {elapsed:.1f}s")
    print(f"Cache location: {cache_dir / cache_name}")

    job.cleanup()


def _parse_for_view(odb_path: str, layer_names: list[str] = None) -> dict:
    """Parse ODB++ data needed for the viewer.

    Args:
        odb_path: Path to ODB++ archive or directory.
        layer_names: Layer names to load features for.
                     None = load ALL layers.

    Returns:
        dict with keys: job, profile, layers_data, components_top,
        components_bot, eda_data, user_symbols, font.
    """
    import matplotlib
    matplotlib.use("TkAgg")

    print(f"Loading ODB++ from: {odb_path}")
    job = odb_loader.load(odb_path)

    from src.parsers.matrix_parser import parse_matrix
    from src.parsers.profile_parser import parse_profile
    from src.parsers.feature_parser import parse_features
    from src.parsers.component_parser import parse_components
    from src.parsers.eda_parser import parse_eda_data
    from src.parsers.font_parser import parse_font
    from src.parsers.symbol_parser import parse_all_symbols

    steps, matrix_layers = parse_matrix(job.matrix_path)
    layer_lookup = {l.name: l for l in matrix_layers}

    step_name, step = _select_step(job)

    profile = parse_profile(step.profile) if step.profile else None
    font = parse_font(job.font_path) if job.font_path else None
    user_symbols = parse_all_symbols(job.symbols) if job.symbols else {}
    eda_data = parse_eda_data(step.eda_data) if step.eda_data else None

    # Determine which layers to load features for
    if layer_names:
        target_set = set(l.lower() for l in layer_names)
    else:
        target_set = None  # load all

    # Collect FID-referenced layers and their required feature indices
    # so we can selectively load only the features needed for pin rendering.
    fid_layer_names: set[str] = set()
    fid_feature_indices: dict[str, set[int]] = {}
    if eda_data and eda_data.layer_names:
        from src.visualizer.fid_lookup import (
            collect_fid_layer_names, collect_fid_feature_indices,
        )
        fid_layer_names = collect_fid_layer_names(eda_data)
        fid_feature_indices = collect_fid_feature_indices(eda_data)
        if fid_layer_names:
            print(f"  FID: {len(fid_layer_names)} layers referenced for pin geometry")

    components_top = []
    components_bot = []
    layers_data = {}
    comp_top_units = "INCH"
    comp_bot_units = "INCH"

    for layer_name, layer_paths in step.layers.items():
        # Always parse components regardless of layer filter
        if layer_paths.components:
            comps, comp_units = parse_components(layer_paths.components)
            if "top" in layer_name:
                components_top = comps
                comp_top_units = comp_units
            else:
                components_bot = comps
                comp_bot_units = comp_units

        # Parse features (all layers if target_set is None, otherwise only targets)
        if layer_paths.features:
            is_target = (target_set is None or layer_name in target_set)
            is_fid_layer = layer_name in fid_layer_names

            if not is_target and not is_fid_layer:
                continue

            try:
                # For FID-referenced layers not explicitly requested,
                # use selective loading to only parse needed features.
                only_indices = None
                if is_fid_layer and not is_target:
                    only_indices = fid_feature_indices.get(layer_name)

                features = parse_features(layer_paths.features,
                                          only_indices=only_indices)
                ml = layer_lookup.get(layer_name)
                if ml:
                    layers_data[layer_name] = (features, ml)
                    if only_indices is not None:
                        print(f"  Loaded: {layer_name} ({len(only_indices)} of "
                              f"{len(features.features)} features, FID-selective)")
                    else:
                        print(f"  Loaded: {layer_name} ({len(features.features)} features)")
            except Exception as e:
                print(f"  Warning: Failed to load {layer_name}: {e}")

    # ------------------------------------------------------------------
    # Unit normalisation – convert all inch-based data to MM.
    # ------------------------------------------------------------------
    for comps, cu in [(components_top, comp_top_units),
                      (components_bot, comp_bot_units)]:
        if comps and cu == "INCH":
            _scale_components(comps, _INCH_TO_MM)
            print(f"  Units: scaled component positions INCH -> MM (x25.4)")

    if eda_data and eda_data.units == "INCH":
        _scale_eda_data(eda_data, _INCH_TO_MM)
        eda_data.units = "MM"
        print(f"  Units: scaled EDA package data INCH -> MM (x25.4)")

    if eda_data:
        _calibrate_eda_to_components(components_top, components_bot, eda_data)

    if profile and profile.units == "INCH":
        _scale_profile(profile, _INCH_TO_MM)
        profile.units = "MM"
        print(f"  Units: scaled profile INCH -> MM (x25.4)")

    for layer_name, (features, ml) in layers_data.items():
        if features.units == "INCH":
            _scale_layer_features(features, _INCH_TO_MM)
            print(f"  Units: scaled {layer_name} features INCH -> MM (x25.4)")

    if user_symbols:
        _scale_user_symbols(user_symbols, _INCH_TO_MM)
        print(f"  Units: scaled user-defined symbol coordinates INCH -> MM (x25.4)")

    return {
        "job": job,
        "profile": profile,
        "layers_data": layers_data,
        "components_top": components_top,
        "components_bot": components_bot,
        "eda_data": eda_data,
        "user_symbols": user_symbols,
        "font": font,
    }


def _ensure_cache(odb_path: str, cache_dir: Path) -> str:
    """Ensure a JSON cache exists for odb_path; build it automatically if missing.

    Returns the cache_name (stem of the ODB path).
    """
    import argparse
    cache_name = Path(odb_path).stem
    cache_path = cache_dir / cache_name
    cache_files = list(cache_path.glob("*.json")) if cache_path.exists() else []
    if not cache_files:
        print(f"No cache found at {cache_path}. Building cache first...")
        cmd_cache(argparse.Namespace(odb_path=odb_path, cache_dir=str(cache_dir)))
    return cache_name


def _load_from_cache(cache_dir: Path, cache_name: str) -> dict:
    """Load and reconstruct all job data from the JSON cache into dataclass objects."""
    from src.cache_manager import load_cache
    from src.models import JobInfo

    print(f"Loading from cache: {cache_dir / cache_name}")
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


def cmd_view(args):
    """Launch the interactive PCB visualizer.

    Without --layers: loads ALL layers, starts with PCB outline only.
    With --layers:    loads and displays only the specified layers.
    """
    import matplotlib
    matplotlib.use("TkAgg")

    cache_dir = Path(getattr(args, "cache_dir", None) or "cache")
    cache_name = _ensure_cache(args.odb_path, cache_dir)
    data = _load_from_cache(cache_dir, cache_name)

    from src.visualizer.viewer import PcbViewer

    if args.layers:
        initial = [l.lower() for l in args.layers]
    else:
        initial = []

    top_n = len(data["components_top"])
    bot_n = len(data["components_bot"])
    print(f"\nLaunching viewer ({len(data['layers_data'])} layers, "
          f"{top_n} top, {bot_n} bot components)...")

    viewer = PcbViewer(
        profile=data.get("profile"),
        layers_data=data["layers_data"],
        components_top=data["components_top"],
        components_bot=data["components_bot"],
        eda_data=data.get("eda_data"),
        user_symbols=data.get("user_symbols", {}),
        font=data.get("font"),
    )
    viewer.show(initial_visible=initial)


def _parse_for_comp_view(odb_path: str) -> dict:
    """Parse only the data needed for the component viewer (no layer features)."""
    import matplotlib
    matplotlib.use("TkAgg")

    print(f"Loading ODB++ from: {odb_path}")
    job = odb_loader.load(odb_path)

    from src.parsers.profile_parser import parse_profile
    from src.parsers.component_parser import parse_components
    from src.parsers.eda_parser import parse_eda_data

    _, step = _select_step(job)

    profile  = parse_profile(step.profile)  if step.profile  else None
    eda_data = parse_eda_data(step.eda_data) if step.eda_data else None

    components_top = []
    components_bot = []
    comp_top_units = "INCH"
    comp_bot_units = "INCH"

    for layer_name, layer_paths in step.layers.items():
        if layer_paths.components:
            comps, comp_units = parse_components(layer_paths.components)
            if "top" in layer_name:
                components_top = comps
                comp_top_units = comp_units
            else:
                components_bot = comps
                comp_bot_units = comp_units

    # ------------------------------------------------------------------
    # Unit normalisation – convert all inch-based data to MM.
    # ------------------------------------------------------------------
    for comps, cu in [(components_top, comp_top_units),
                      (components_bot, comp_bot_units)]:
        if comps and cu == "INCH":
            _scale_components(comps, _INCH_TO_MM)
            print(f"  Units: scaled component positions INCH -> MM (x25.4)")

    if eda_data and eda_data.units == "INCH":
        _scale_eda_data(eda_data, _INCH_TO_MM)
        eda_data.units = "MM"
        print(f"  Units: scaled EDA package data INCH -> MM (x25.4)")

    if eda_data:
        _calibrate_eda_to_components(components_top, components_bot, eda_data)

    if profile and profile.units == "INCH":
        _scale_profile(profile, _INCH_TO_MM)
        profile.units = "MM"
        print(f"  Units: scaled profile INCH -> MM (x25.4)")

    return {
        "job": job,
        "profile": profile,
        "components_top": components_top,
        "components_bot": components_bot,
        "eda_data": eda_data,
    }


def cmd_view_comp(args):
    """Launch the component-focused interactive viewer."""
    import matplotlib
    matplotlib.use("TkAgg")

    cache_dir = Path(getattr(args, "cache_dir", None) or "cache")
    cache_name = _ensure_cache(args.odb_path, cache_dir)
    data = _load_from_cache(cache_dir, cache_name)

    if data.get("data_type") == "array":
        print("The 'view-comp' command is not available for Array-type ODB data "
              "(Array structures do not contain component layers).")
        return

    from src.visualizer.viewer import ComponentViewer

    top_n = len(data["components_top"])
    bot_n = len(data["components_bot"])
    print(f"\nLaunching component viewer ({top_n} top, {bot_n} bot components)...")

    viewer = ComponentViewer(
        profile=data.get("profile"),
        components_top=data["components_top"],
        components_bot=data["components_bot"],
        eda_data=data.get("eda_data"),
        layers_data=data.get("layers_data", {}),
        user_symbols=data.get("user_symbols", {}),
    )
    viewer.show()



def cmd_check(args):
    """Run the automated checklist."""
    # Import rules to trigger registration
    import src.checklist.rules.ckl_01_001  # noqa: F401
    import src.checklist.rules.ckl_01_002  # noqa: F401
    import src.checklist.rules.ckl_01_003  # noqa: F401
    import src.checklist.rules.ckl_01_004  # noqa: F401
    import src.checklist.rules.ckl_01_005  # noqa: F401
    import src.checklist.rules.ckl_01_006  # noqa: F401
    import src.checklist.rules.ckl_01_007  # noqa: F401
    import src.checklist.rules.ckl_02_001  # noqa: F401
    import src.checklist.rules.ckl_02_002  # noqa: F401
    import src.checklist.rules.ckl_02_003  # noqa: F401
    import src.checklist.rules.ckl_02_004  # noqa: F401
    import src.checklist.rules.ckl_02_006  # noqa: F401
    import src.checklist.rules.ckl_02_007  # noqa: F401
    import src.checklist.rules.ckl_02_008  # noqa: F401
    import src.checklist.rules.ckl_02_009  # noqa: F401
    import src.checklist.rules.ckl_02_010  # noqa: F401
    import src.checklist.rules.ckl_02_011  # noqa: F401
    import src.checklist.rules.ckl_02_012  # noqa: F401
    import src.checklist.rules.ckl_03_001  # noqa: F401
    import src.checklist.rules.ckl_03_002  # noqa: F401
    import src.checklist.rules.ckl_03_004  # noqa: F401
    import src.checklist.rules.ckl_03_011  # noqa: F401
    import src.checklist.rules.ckl_03_005  # noqa: F401
    import src.checklist.rules.ckl_03_012  # noqa: F401
    import src.checklist.rules.ckl_03_013  # noqa: F401
    import src.checklist.rules.ckl_03_015  # noqa: F401
    import src.checklist.rules.ckl_03_016  # noqa: F401
    import src.checklist.rules.ckl_03_008  # noqa: F401
    import src.checklist.rules.ckl_03_009  # noqa: F401

    from src.checklist.engine import load_rules, run_checklist
    from src.checklist.reporter import generate_report

    cache_dir = Path(getattr(args, "cache_dir", None) or "cache")
    cache_name = _ensure_cache(args.odb_path, cache_dir)
    job_data = _load_from_cache(cache_dir, cache_name)

    # Load rules
    rule_ids = args.rules if args.rules else None
    rules = load_rules(rule_ids)
    print(f"\nRunning {len(rules)} checklist rule(s)...")

    # Run checklist
    results = run_checklist(job_data, rules)

    # Print results
    print(f"\n{'='*60}")
    print(f"CHECKLIST RESULTS")
    print(f"{'='*60}")

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        marker = "[+]" if result.passed else "[X]"
        print(f"  {marker} {result.rule_id}: {result.description}")
        print(f"      Status: {status} - {result.message}")
        if result.affected_components:
            comps_str = ", ".join(result.affected_components[:10])
            if len(result.affected_components) > 10:
                comps_str += f" ... (+{len(result.affected_components) - 10} more)"
            print(f"      Components: {comps_str}")

    print(f"\nSummary: {passed} passed, {failed} failed out of {len(results)} rules")

    # Generate Excel report
    odb_filename = Path(args.odb_path).name
    default_output = Path(f"output/[CKL_report]{odb_filename}.xlsx")
    output_path = Path(args.output) if args.output else default_output
    job_info = job_data.get("job_info")
    job_name = job_info.job_name if job_info else cache_name
    references_dir = Path(__file__).parent / "references"
    generate_report(
        results, output_path, job_name=job_name,
        components_top=job_data.get("components_top", []),
        components_bot=job_data.get("components_bot", []),
        references_dir=references_dir,
    )


def cmd_copper_ratio(args):
    """Launch the interactive copper ratio viewer."""
    import json
    import matplotlib
    matplotlib.use("TkAgg")

    cache_dir = Path(getattr(args, "cache_dir", None) or "cache")
    cache_name = _ensure_cache(args.odb_path, cache_dir)
    data = _load_from_cache(cache_dir, cache_name)

    copper_data: dict[str, float] = {}
    copper_file = cache_dir / cache_name / "copper_data.json"
    if copper_file.exists():
        with open(copper_file, "r", encoding="utf-8") as f:
            copper_data = json.load(f)

    from src.visualizer.viewer import CopperRatioViewer

    viewer = CopperRatioViewer(
        profile=data.get("profile"),
        layers_data=data.get("layers_data", {}),
        copper_data=copper_data,
        user_symbols=data.get("user_symbols", {}),
        font=data.get("font"),
    )
    viewer.show()


def cmd_copper(args):
    """Display layer thickness (copper weight) for each Signal and Dielectric layer."""
    import json

    cache_dir = Path(getattr(args, "cache_dir", None) or "cache")
    cache_name = _ensure_cache(args.odb_path, cache_dir)

    copper_file = cache_dir / cache_name / "copper_data.json"
    if not copper_file.exists():
        print(
            "No copper data found in cache. "
            "Please re-run 'cache' to rebuild: python main.py cache <odb_path>"
        )
        return

    with open(copper_file, "r", encoding="utf-8") as f:
        copper_data: dict[str, float] = json.load(f)

    total = sum(copper_data.values())

    print(f"\n{'='*55}")
    print(f"Copper Check: Layer Thickness")
    print(f"{'='*55}")
    print(f"{'Layer':<30s}  {'Layer Thickness':>15s}")
    print(f"{'-'*30}  {'-'*15}")
    for layer_name, thickness in copper_data.items():
        print(f"{layer_name:<30s}  {thickness:>15.6f}")
    print(f"{'-'*30}  {'-'*15}")
    print(f"{'Total Thickness':<30s}  {total:>15.6f}")
    print(f"\n{len(copper_data)} layer(s) found.")


def cmd_copper_calculate(args):
    """Launch the copper ratio batch calculator GUI."""
    import json
    import matplotlib
    matplotlib.use("TkAgg")

    cache_dir = Path(getattr(args, "cache_dir", None) or "cache")

    def _load_data(odb_path: str) -> dict:
        """Load ODB++ data with copper and matrix layer info."""
        cn = _ensure_cache(odb_path, cache_dir)
        data = _load_from_cache(cache_dir, cn)

        # Merge copper_data (signal + dielectric thicknesses)
        copper_file = cache_dir / cn / "copper_data.json"
        if copper_file.exists():
            with open(copper_file, "r", encoding="utf-8") as f:
                data["copper_data"] = json.load(f)
        else:
            data["copper_data"] = {}

        # Provide ordered matrix layers for stackup-ordered output
        raw = load_cache(cache_dir, cn)
        ml_list = reconstruct_matrix_layers(raw.get("matrix_layers", []))
        data["matrix_layers_ordered"] = sorted(ml_list, key=lambda x: x.row)

        return data

    from src.visualizer.viewer import CopperCalculateViewer
    viewer = CopperCalculateViewer(load_data_fn=_load_data, cache_dir=cache_dir)
    viewer.show()


def main():
    parser = argparse.ArgumentParser(
        description="ODB++ Processing System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # info command
    p_info = subparsers.add_parser("info", help="Print job summary")
    p_info.add_argument("odb_path", help="Path to ODB++ archive or directory")

    # cache command
    p_cache = subparsers.add_parser("cache", help="Parse and cache to JSON")
    p_cache.add_argument("odb_path", help="Path to ODB++ archive or directory")
    p_cache.add_argument("--cache-dir", default="cache", help="Cache output directory")

    # view command
    p_view = subparsers.add_parser("view", help="Launch PCB visualizer")
    p_view.add_argument("odb_path", help="Path to ODB++ archive or directory")
    p_view.add_argument("--layers", nargs="*", help="Layer names to load and display")
    p_view.add_argument("--cache-dir", default="cache", help="Cache directory")

    # view-comp command
    p_view_comp = subparsers.add_parser("view-comp", help="Launch component viewer")
    p_view_comp.add_argument("odb_path", help="Path to ODB++ archive or directory")
    p_view_comp.add_argument("--cache-dir", default="cache", help="Cache directory")

    # check command
    p_check = subparsers.add_parser("check", help="Run design checklist")
    p_check.add_argument("odb_path", help="Path to ODB++ archive or directory")
    p_check.add_argument("--rules", nargs="*", help="Rule IDs to run (default: all)")
    p_check.add_argument("--output", help="Output Excel path")
    p_check.add_argument("--cache-dir", default="cache", help="Cache directory")

    # copper command
    p_copper = subparsers.add_parser("copper", help="Display layer thickness per layer")
    p_copper.add_argument("odb_path", help="Path to ODB++ archive or directory")
    p_copper.add_argument("--cache-dir", default="cache", help="Cache directory")

    # copper-ratio command
    p_copper_ratio = subparsers.add_parser("copper-ratio", help="Launch copper ratio viewer")
    p_copper_ratio.add_argument("odb_path", help="Path to ODB++ archive or directory")
    p_copper_ratio.add_argument("--cache-dir", default="cache", help="Cache directory")

    # copper-calculate command
    p_copper_calc = subparsers.add_parser("copper-calculate", help="Launch copper ratio batch calculator")
    p_copper_calc.add_argument("--cache-dir", default="cache", help="Cache directory")

    args = parser.parse_args()

    if args.command == "info":
        cmd_info(args)
    elif args.command == "cache":
        cmd_cache(args)
    elif args.command == "view":
        cmd_view(args)
    elif args.command == "view-comp":
        cmd_view_comp(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "copper":
        cmd_copper(args)
    elif args.command == "copper-ratio":
        cmd_copper_ratio(args)
    elif args.command == "copper-calculate":
        cmd_copper_calculate(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
