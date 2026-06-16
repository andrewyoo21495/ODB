"""ODB++ Processing System - CLI Entry Point.

Usage:
    python main.py cache              <odb_path>                         Parse and cache to JSON
    python main.py view               <odb_path> [--layers L1 L2 ...]    Launch visualizer
    python main.py view-comp          <odb_path>                         Launch component viewer
    python main.py check              <odb_path> [--rules R1 R2 ...]     Run checklist
    python main.py compare            <odb_old> <odb_new>                Compare two revisions
    python main.py info               <odb_path>                         Print job summary
    python main.py copper             <odb_path>                         Display layer thickness
    python main.py copper-ratio       <odb_path>                         Launch copper ratio viewer
    python main.py copper-calculate                                       Launch copper ratio batch calculator
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent))

from src import odb_loader
# load_cache and reconstruct_matrix_layers are still used by cmd_copper_calculate;
# the rest of the cache reconstruction now lives in src.services.data_service.
from src.cache_manager import load_cache, reconstruct_matrix_layers
from src.unit_converter import (
    INCH_TO_MM as _INCH_TO_MM,
    scale_components as _scale_components,
    scale_eda_data as _scale_eda_data,
    scale_profile as _scale_profile,
    scale_layer_features as _scale_layer_features,
    scale_user_symbols as _scale_user_symbols,
)
# Cache-path data logic now lives in the interface-independent data service.
# _select_step and _calibrate_eda_to_components are imported here because the
# live-parse path below (_parse_for_view / _parse_for_comp_view) still uses them.
from src.services import data_service
from src.services.data_service import _select_step, _calibrate_eda_to_components


# _select_step and _calibrate_eda_to_components moved to
# src.services.data_service (imported above); they are shared with the
# cache-build path and the live-parse path below.


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


# _parse_attrlist_value and _resolve_pin_geometries moved to
# src.services.data_service (used only by the cache-build path).


def cmd_cache(args):
    """Parse ODB++ data and cache to JSON files (delegates to data_service)."""
    cache_dir = Path(args.cache_dir) if args.cache_dir else Path("cache")
    data_service.build_cache(args.odb_path, cache_dir)


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


# _ensure_cache / _load_from_cache now delegate to the data service.  They are
# kept as thin wrappers so the existing call sites in this module stay unchanged.

def _ensure_cache(odb_path: str, cache_dir: Path) -> str:
    """Ensure a JSON cache exists for odb_path; build it if missing. Returns cache_name."""
    return data_service.ensure_cache(odb_path, cache_dir)


def _load_from_cache(cache_dir: Path, cache_name: str) -> dict:
    """Load and reconstruct all job data from the JSON cache into dataclass objects."""
    return data_service.load_job(cache_dir, cache_name)


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



def cmd_view_net(args):
    """Launch the signal-layer net visualizer."""
    import matplotlib
    matplotlib.use("TkAgg")

    cache_dir = Path(getattr(args, "cache_dir", None) or "cache")
    cache_name = _ensure_cache(args.odb_path, cache_dir)
    data = _load_from_cache(cache_dir, cache_name)

    from src.visualizer.viewer import NetViewer
    from src.visualizer.net_filter import get_signal_layers

    signal_layers = get_signal_layers(data.get("layers_data", {}))
    if not signal_layers:
        print("No SIGNAL layers found in cache.")
        return

    print(f"\nLaunching net viewer ({len(signal_layers)} signal layers)...")

    viewer = NetViewer(
        profile=data.get("profile"),
        layers_data=data.get("layers_data", {}),
        eda_data=data.get("eda_data"),
        user_symbols=data.get("user_symbols", {}),
        font=data.get("font"),
    )
    viewer.show()


def cmd_check(args):
    """Run the automated checklist (delegates to checklist_service)."""
    from src.services import checklist_service

    cache_dir = Path(getattr(args, "cache_dir", None) or "cache")
    cache_name = _ensure_cache(args.odb_path, cache_dir)
    job_data = _load_from_cache(cache_dir, cache_name)

    # Discover + run rules (rules are auto-discovered; no manual import list).
    rule_ids = args.rules if args.rules else None
    results = checklist_service.evaluate(job_data, rule_ids)
    print(f"\nRunning {len(results)} checklist rule(s)...")

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

    # Generate HTML report (Excel reporting retired)
    odb_filename = Path(args.odb_path).name
    job_info = job_data.get("job_info")
    job_name = job_info.job_name if job_info else cache_name
    references_dir = Path(__file__).parent / "references"

    if args.output:
        html_path = Path(args.output).with_suffix(".html")
    else:
        html_path = Path(f"output/[CKL_report]{odb_filename}.html")

    checklist_service.write_report(
        results,
        html_path=html_path,
        odb_filename=odb_filename,
        job_name=job_name,
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


def cmd_compare(args):
    """Compare two ODB++ revisions and generate a diff report (delegates to compare_service)."""
    from src.services import compare_service

    cache_dir = Path(getattr(args, "cache_dir", None) or "cache")

    # Ensure caches for both revisions
    old_cache_name = _ensure_cache(args.odb_path_old, cache_dir)
    new_cache_name = _ensure_cache(args.odb_path_new, cache_dir)

    # Load both from cache
    print(f"\nLoading old revision: {old_cache_name}")
    old_data = _load_from_cache(cache_dir, old_cache_name)

    print(f"Loading new revision: {new_cache_name}")
    new_data = _load_from_cache(cache_dir, new_cache_name)

    # Run all comparators (auto-discovered; no manual import list).
    print(f"\nRunning revision comparison...")
    results = compare_service.compare(old_data, new_data)

    # Print console summary
    print(f"\n{'='*60}")
    print(f"COMPARISON RESULTS")
    print(f"{'='*60}")
    for r in results:
        print(f"  [{r.comparator_id}] {r.title}: {r.summary}")

    # Generate HTML report (Excel reporting retired)
    old_name = Path(args.odb_path_old).stem
    new_name = Path(args.odb_path_new).stem
    if args.output:
        html_path = Path(args.output).with_suffix(".html")
    else:
        html_path = Path(f"output/[CMP_report]{old_name}_vs_{new_name}.html")
    compare_service.write_html_report(
        results, html_path,
        old_job_name=Path(args.odb_path_old).name,
        new_job_name=Path(args.odb_path_new).name,
    )
    print(f"\nHTML report saved to: {html_path}")


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

    # view-net command
    p_view_net = subparsers.add_parser("view-net", help="Launch signal-layer net viewer")
    p_view_net.add_argument("odb_path", help="Path to ODB++ archive or directory")
    p_view_net.add_argument("--cache-dir", default="cache", help="Cache directory")

    # check command
    p_check = subparsers.add_parser("check", help="Run design checklist")
    p_check.add_argument("odb_path", help="Path to ODB++ archive or directory")
    p_check.add_argument("--rules", nargs="*", help="Rule IDs to run (default: all)")
    p_check.add_argument("--output", help="Output HTML report path")
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

    # compare command
    p_compare = subparsers.add_parser("compare", help="Compare two ODB++ revisions")
    p_compare.add_argument("odb_path_old", help="Path to old revision ODB++ archive")
    p_compare.add_argument("odb_path_new", help="Path to new revision ODB++ archive")
    p_compare.add_argument("--output", help="Output report path (reserved; HTML report pending)")
    p_compare.add_argument("--cache-dir", default="cache", help="Cache directory")

    args = parser.parse_args()

    if args.command == "info":
        cmd_info(args)
    elif args.command == "cache":
        cmd_cache(args)
    elif args.command == "view":
        cmd_view(args)
    elif args.command == "view-comp":
        cmd_view_comp(args)
    elif args.command == "view-net":
        cmd_view_net(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "copper":
        cmd_copper(args)
    elif args.command == "copper-ratio":
        cmd_copper_ratio(args)
    elif args.command == "copper-calculate":
        cmd_copper_calculate(args)
    elif args.command == "compare":
        cmd_compare(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
