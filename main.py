"""ODB++ Processing System - CLI Entry Point.

Usage:
    python main.py cache      <odb_path>                         Parse and cache to JSON
    python main.py view       <odb_path> [--layers L1 L2 ...]    Launch visualizer
    python main.py view-comp  <odb_path>                         Launch component viewer
    python main.py check      <odb_path> [--rules R1 R2 ...]     Run checklist
    python main.py info       <odb_path>                         Print job summary
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
    reconstruct_profile, reconstruct_component, reconstruct_eda_data,
    reconstruct_matrix_layer, reconstruct_layer_features,
    reconstruct_user_symbol, reconstruct_font, reconstruct_job_info,
)
from src.models import ArcSegment, LayerFeatures, LineSegment


# ---------------------------------------------------------------------------
# Unit normalisation helpers
# ---------------------------------------------------------------------------

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


def _load_view_data_from_cache(cache_dir: Path, cache_name: str,
                               layer_names: list[str] | None) -> dict:
    """Load and reconstruct viewer data from JSON cache."""
    raw = load_cache(cache_dir, cache_name)

    profile = reconstruct_profile(raw["profile"]) if raw.get("profile") else None
    matrix_layers = [reconstruct_matrix_layer(d) for d in raw.get("matrix_layers", [])]
    layer_lookup = {ml.name: ml for ml in matrix_layers}

    components_top = [reconstruct_component(d) for d in raw.get("components_top", [])]
    components_bot = [reconstruct_component(d) for d in raw.get("components_bot", [])]
    eda_data = reconstruct_eda_data(raw["eda_data"]) if raw.get("eda_data") else None

    user_symbols = {
        name: reconstruct_user_symbol(sym_data)
        for name, sym_data in (raw.get("symbols") or {}).items()
    }
    font = reconstruct_font(raw["font"]) if raw.get("font") else None

    target_set = set(l.lower() for l in layer_names) if layer_names else None
    layers_data = {}
    for key, feat_data in raw.items():
        if not key.startswith("layer_features:"):
            continue
        layer_name = key.split(":", 1)[1]
        if target_set is not None and layer_name not in target_set:
            continue
        lf = reconstruct_layer_features(feat_data)
        ml = layer_lookup.get(layer_name)
        if ml:
            layers_data[layer_name] = (lf, ml)
            print(f"  Loaded (cache): {layer_name} ({len(lf.features)} features)")

    if eda_data:
        _calibrate_eda_to_components(components_top, components_bot, eda_data)

    return {
        "job": None,
        "profile": profile,
        "layers_data": layers_data,
        "components_top": components_top,
        "components_bot": components_bot,
        "eda_data": eda_data,
        "user_symbols": user_symbols,
        "font": font,
    }


def _load_comp_view_data_from_cache(cache_dir: Path, cache_name: str) -> dict:
    """Load and reconstruct component-viewer data from JSON cache."""
    raw = load_cache(cache_dir, cache_name)

    profile = reconstruct_profile(raw["profile"]) if raw.get("profile") else None
    components_top = [reconstruct_component(d) for d in raw.get("components_top", [])]
    components_bot = [reconstruct_component(d) for d in raw.get("components_bot", [])]
    eda_data = reconstruct_eda_data(raw["eda_data"]) if raw.get("eda_data") else None

    if eda_data:
        _calibrate_eda_to_components(components_top, components_bot, eda_data)

    return {
        "job": None,
        "profile": profile,
        "components_top": components_top,
        "components_bot": components_bot,
        "eda_data": eda_data,
    }


def _load_check_data_from_cache(cache_dir: Path, cache_name: str) -> dict:
    """Load and reconstruct checklist data from JSON cache."""
    raw = load_cache(cache_dir, cache_name)

    job_data = {}
    if raw.get("job_info"):
        job_data["job_info"] = reconstruct_job_info(raw["job_info"])
    if raw.get("matrix_layers"):
        job_data["matrix_layers"] = [reconstruct_matrix_layer(d) for d in raw["matrix_layers"]]
    if raw.get("profile"):
        job_data["profile"] = reconstruct_profile(raw["profile"])
    if raw.get("eda_data"):
        job_data["eda_data"] = reconstruct_eda_data(raw["eda_data"])
    if raw.get("components_top"):
        job_data["components_top"] = [reconstruct_component(d) for d in raw["components_top"]]
        print(f"  Loaded (cache): {len(job_data['components_top'])} top components")
    if raw.get("components_bot"):
        job_data["components_bot"] = [reconstruct_component(d) for d in raw["components_bot"]]
        print(f"  Loaded (cache): {len(job_data['components_bot'])} bottom components")

    return job_data


def cmd_info(args):
    """Print job summary information."""
    job = odb_loader.load(args.odb_path)

    print(f"{'='*60}")
    print(f"ODB++ Job: {job.job_name}")
    print(f"Root: {job.root_dir}")
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

    # Parse misc/info
    if job.misc_info_path:
        from src.parsers.misc_parser import parse_info
        info = parse_info(job.misc_info_path)
        data["job_info"] = info
        print(f"  Parsed: misc/info")

    # Parse matrix
    if job.matrix_path:
        from src.parsers.matrix_parser import parse_matrix
        steps, layers = parse_matrix(job.matrix_path)
        data["matrix_steps"] = steps
        data["matrix_layers"] = layers
        print(f"  Parsed: matrix ({len(steps)} steps, {len(layers)} layers)")

    # Parse font
    if job.font_path:
        from src.parsers.font_parser import parse_font
        font = parse_font(job.font_path)
        data["font"] = font
        print(f"  Parsed: fonts/standard ({len(font.characters)} characters)")

    # Parse each step
    for step_name, step_paths in job.steps.items():
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

        # EDA data
        if step_paths.eda_data:
            from src.parsers.eda_parser import parse_eda_data
            eda = parse_eda_data(step_paths.eda_data)
            data["eda_data"] = eda
            print(f"    Parsed: eda/data ({len(eda.nets)} nets, {len(eda.packages)} packages)")

        # Netlist
        if step_paths.netlist_cadnet:
            from src.parsers.netlist_parser import parse_netlist
            netlist = parse_netlist(step_paths.netlist_cadnet)
            data["netlist"] = netlist
            print(f"    Parsed: netlist ({len(netlist.net_names)} nets)")

        # Components and layer features
        from src.parsers.component_parser import parse_components
        from src.parsers.feature_parser import parse_features

        for layer_name, layer_paths in step_paths.layers.items():
            # Components
            if layer_paths.components:
                components, _cu = parse_components(layer_paths.components)
                key = "components_top" if "top" in layer_name else "components_bot"
                data[key] = components
                print(f"    Parsed: {layer_name}/components ({len(components)} components)")

            # Features
            if layer_paths.features:
                try:
                    features = parse_features(layer_paths.features)
                    data[f"layer_features:{layer_name}"] = features
                    print(f"    Parsed: {layer_name}/features ({len(features.features)} features)")
                except Exception as e:
                    print(f"    Warning: Failed to parse {layer_name}/features: {e}")

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
    cache_name = Path(odb_path).stem
    cache_dir = Path("cache")
    if is_cache_valid(cache_dir, cache_name, odb_path):
        print(f"Loading from cache: {cache_dir / cache_name}")
        return _load_view_data_from_cache(cache_dir, cache_name, layer_names)

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

    step_name = list(job.steps.keys())[0]
    step = job.steps[step_name]

    profile = parse_profile(step.profile) if step.profile else None
    font = parse_font(job.font_path) if job.font_path else None
    user_symbols = parse_all_symbols(job.symbols) if job.symbols else {}
    eda_data = parse_eda_data(step.eda_data) if step.eda_data else None

    # Determine which layers to load features for
    if layer_names:
        target_set = set(l.lower() for l in layer_names)
    else:
        target_set = None  # load all

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
            if target_set is not None and layer_name not in target_set:
                continue
            try:
                features = parse_features(layer_paths.features)
                ml = layer_lookup.get(layer_name)
                if ml:
                    layers_data[layer_name] = (features, ml)
                    print(f"  Loaded: {layer_name} ({len(features.features)} features)")
            except Exception as e:
                print(f"  Warning: Failed to load {layer_name}: {e}")

    # Normalise units – scale component and EDA coordinates to match the
    # profile's coordinate space when files declare different units.
    profile_units = profile.units if profile else "INCH"
    for comps, cu in [(components_top, comp_top_units),
                      (components_bot, comp_bot_units)]:
        if comps and cu != profile_units:
            f = _unit_scale(cu, profile_units)
            _scale_components(comps, f)
            print(f"  Units: scaled component positions {cu} → {profile_units}")

    if eda_data and eda_data.units != profile_units:
        f = _unit_scale(eda_data.units, profile_units)
        _scale_eda_data(eda_data, f)
        eda_data.units = profile_units
        print(f"  Units: scaled EDA package data to {profile_units}")

    # Cross-check: verify EDA package geometry matches component toeprint
    # positions and apply a correction if a residual inch/mm discrepancy remains.
    if eda_data:
        _calibrate_eda_to_components(components_top, components_bot, eda_data)

    # Auto-save to cache so subsequent runs skip TGZ parsing.
    try:
        cache_data: dict = {
            "profile": profile,
            "matrix_layers": matrix_layers,
            "components_top": components_top,
            "components_bot": components_bot,
            "eda_data": eda_data,
            "symbols": user_symbols,
            "font": font,
        }
        for layer_name, (lf, _ml) in layers_data.items():
            cache_data[f"layer_features:{layer_name}"] = lf
        cache_job(cache_name, cache_data, cache_dir)
        print(f"  Cache saved: {cache_dir / cache_name}")
    except Exception as e:
        print(f"  Warning: Cache save failed: {e}")

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


def cmd_view(args):
    """Launch the interactive PCB visualizer.

    Without --layers: loads ALL layers, starts with PCB outline only.
    With --layers:    loads and checks only the specified layers.
    """
    data = _parse_for_view(args.odb_path, layer_names=args.layers)

    from src.visualizer.viewer import PcbViewer

    if args.layers:
        initial = [l.lower() for l in args.layers]
    else:
        initial = []  # outline only

    print(f"\nLaunching viewer with {len(data['layers_data'])} layers...")

    viewer = PcbViewer(
        profile=data["profile"],
        layers_data=data["layers_data"],
        components_top=data["components_top"],
        components_bot=data["components_bot"],
        eda_data=data["eda_data"],
        user_symbols=data["user_symbols"],
        font=data["font"],
    )
    viewer.show(initial_visible=initial)
    if data.get("job"):
        data["job"].cleanup()


def _parse_for_comp_view(odb_path: str) -> dict:
    """Parse only the data needed for the component viewer (no layer features)."""
    cache_name = Path(odb_path).stem
    cache_dir = Path("cache")
    if is_cache_valid(cache_dir, cache_name, odb_path):
        print(f"Loading from cache: {cache_dir / cache_name}")
        return _load_comp_view_data_from_cache(cache_dir, cache_name)

    import matplotlib
    matplotlib.use("TkAgg")

    print(f"Loading ODB++ from: {odb_path}")
    job = odb_loader.load(odb_path)

    from src.parsers.profile_parser import parse_profile
    from src.parsers.component_parser import parse_components
    from src.parsers.eda_parser import parse_eda_data

    step_name = list(job.steps.keys())[0]
    step = job.steps[step_name]

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

    profile_units = profile.units if profile else "INCH"
    for comps, cu in [(components_top, comp_top_units),
                      (components_bot, comp_bot_units)]:
        if comps and cu != profile_units:
            f = _unit_scale(cu, profile_units)
            _scale_components(comps, f)
            print(f"  Units: scaled component positions {cu} → {profile_units}")

    if eda_data and eda_data.units != profile_units:
        f = _unit_scale(eda_data.units, profile_units)
        _scale_eda_data(eda_data, f)
        eda_data.units = profile_units
        print(f"  Units: scaled EDA package data to {profile_units}")

    if eda_data:
        _calibrate_eda_to_components(components_top, components_bot, eda_data)

    # Auto-save to cache so subsequent runs skip TGZ parsing.
    try:
        cache_data = {
            "profile": profile,
            "components_top": components_top,
            "components_bot": components_bot,
            "eda_data": eda_data,
        }
        cache_job(cache_name, cache_data, cache_dir)
        print(f"  Cache saved: {cache_dir / cache_name}")
    except Exception as e:
        print(f"  Warning: Cache save failed: {e}")

    return {
        "job": job,
        "profile": profile,
        "components_top": components_top,
        "components_bot": components_bot,
        "eda_data": eda_data,
    }


def cmd_view_comp(args):
    """Launch the component-focused interactive viewer."""
    data = _parse_for_comp_view(args.odb_path)

    from src.visualizer.viewer import ComponentViewer

    top_n = len(data["components_top"])
    bot_n = len(data["components_bot"])
    print(f"\nLaunching component viewer ({top_n} top, {bot_n} bot components)...")

    viewer = ComponentViewer(
        profile=data["profile"],
        components_top=data["components_top"],
        components_bot=data["components_bot"],
        eda_data=data["eda_data"],
    )
    viewer.show()
    if data.get("job"):
        data["job"].cleanup()


def cmd_check(args):
    """Run the automated checklist."""
    # Import rules to trigger registration
    import src.checklist.rules.ckl_component_alignment  # noqa: F401
    import src.checklist.rules.ckl_spacing  # noqa: F401
    import src.checklist.rules.ckl_placement  # noqa: F401

    from src.checklist.engine import load_rules, run_checklist
    from src.checklist.reporter import generate_report

    cache_name = Path(args.odb_path).stem
    cache_dir = Path("cache")
    job = None

    if is_cache_valid(cache_dir, cache_name, args.odb_path):
        print(f"Loading from cache: {cache_dir / cache_name}")
        job_data = _load_check_data_from_cache(cache_dir, cache_name)
    else:
        print(f"Loading ODB++ from: {args.odb_path}")
        job = odb_loader.load(args.odb_path)

        from src.parsers.matrix_parser import parse_matrix
        from src.parsers.profile_parser import parse_profile
        from src.parsers.component_parser import parse_components
        from src.parsers.eda_parser import parse_eda_data
        from src.parsers.misc_parser import parse_info

        step_name = list(job.steps.keys())[0]
        step = job.steps[step_name]

        job_data = {}

        if job.misc_info_path:
            job_data["job_info"] = parse_info(job.misc_info_path)

        _steps, layers = parse_matrix(job.matrix_path)
        job_data["matrix_layers"] = layers

        if step.profile:
            job_data["profile"] = parse_profile(step.profile)

        if step.eda_data:
            job_data["eda_data"] = parse_eda_data(step.eda_data)

        for layer_name, layer_paths in step.layers.items():
            if layer_paths.components:
                comps, _cu = parse_components(layer_paths.components)
                if "top" in layer_name:
                    job_data["components_top"] = comps
                    print(f"  Loaded {len(comps)} top components")
                else:
                    job_data["components_bot"] = comps
                    print(f"  Loaded {len(comps)} bottom components")

        # Auto-save to cache
        try:
            cache_job(cache_name, job_data, cache_dir)
            print(f"  Cache saved: {cache_dir / cache_name}")
        except Exception as e:
            print(f"  Warning: Cache save failed: {e}")

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
    output_path = Path(args.output) if args.output else Path("output/checklist_report.xlsx")
    job_info = job_data.get("job_info")
    job_name = job_info.job_name if job_info else cache_name

    generate_report(results, output_path, job_name=job_name)

    if job:
        job.cleanup()


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

    # view-comp command
    p_view_comp = subparsers.add_parser("view-comp", help="Launch component viewer")
    p_view_comp.add_argument("odb_path", help="Path to ODB++ archive or directory")

    # check command
    p_check = subparsers.add_parser("check", help="Run design checklist")
    p_check.add_argument("odb_path", help="Path to ODB++ archive or directory")
    p_check.add_argument("--rules", nargs="*", help="Rule IDs to run (default: all)")
    p_check.add_argument("--output", help="Output Excel path")

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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
