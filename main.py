"""ODB++ Processing System - CLI Entry Point.

Usage:
    python main.py cache     <odb_path>                         Parse and cache to JSON
    python main.py view      <odb_path> [--layers L1 L2 ...]    Launch visualizer
    python main.py view-top  <odb_path> [--layers L1 L2 ...]    View top components
    python main.py view-bot  <odb_path> [--layers L1 L2 ...]    View bottom components
    python main.py check     <odb_path> [--rules R1 R2 ...]     Run checklist
    python main.py info      <odb_path>                         Print job summary
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent))

from src import odb_loader
from src.cache_manager import cache_job, cache_layer, is_cache_valid, load_cache
from src.models import LayerFeatures


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

    print(f"Job: {job.job_name}")
    print(f"Cache directory: {cache_dir / job.job_name}")

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
                components = parse_components(layer_paths.components)
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
    cache_job(job.job_name, data, cache_dir)

    elapsed = time.time() - t0
    print(f"\nDone! Cached in {elapsed:.1f}s")
    print(f"Cache location: {cache_dir / job.job_name}")

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

    for layer_name, layer_paths in step.layers.items():
        # Always parse components regardless of layer filter
        if layer_paths.components:
            comps = parse_components(layer_paths.components)
            if "top" in layer_name:
                components_top = comps
            else:
                components_bot = comps

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
    data["job"].cleanup()


def cmd_view_top(args):
    """Launch viewer focused on top-side components."""
    data = _parse_for_view(args.odb_path, layer_names=args.layers)

    from src.visualizer.viewer import PcbViewer, COMP_TOP_KEY

    initial = [COMP_TOP_KEY]
    if args.layers:
        initial.extend(l.lower() for l in args.layers)

    n_comps = len(data["components_top"])
    n_layers = len(data["layers_data"])
    print(f"\nLaunching top-component viewer ({n_comps} components, {n_layers} layers)...")

    viewer = PcbViewer(
        profile=data["profile"],
        layers_data=data["layers_data"],
        components_top=data["components_top"],
        components_bot=[],
        eda_data=data["eda_data"],
        user_symbols=data["user_symbols"],
        font=data["font"],
    )
    viewer.show(initial_visible=initial)
    data["job"].cleanup()


def cmd_view_bot(args):
    """Launch viewer focused on bottom-side components."""
    data = _parse_for_view(args.odb_path, layer_names=args.layers)

    from src.visualizer.viewer import PcbViewer, COMP_BOT_KEY

    initial = [COMP_BOT_KEY]
    if args.layers:
        initial.extend(l.lower() for l in args.layers)

    n_comps = len(data["components_bot"])
    n_layers = len(data["layers_data"])
    print(f"\nLaunching bottom-component viewer ({n_comps} components, {n_layers} layers)...")

    viewer = PcbViewer(
        profile=data["profile"],
        layers_data=data["layers_data"],
        components_top=[],
        components_bot=data["components_bot"],
        eda_data=data["eda_data"],
        user_symbols=data["user_symbols"],
        font=data["font"],
    )
    viewer.show(initial_visible=initial)
    data["job"].cleanup()


def cmd_check(args):
    """Run the automated checklist."""
    print(f"Loading ODB++ from: {args.odb_path}")
    job = odb_loader.load(args.odb_path)

    # Import rules to trigger registration
    import src.checklist.rules.ckl_component_alignment  # noqa: F401
    import src.checklist.rules.ckl_spacing  # noqa: F401
    import src.checklist.rules.ckl_placement  # noqa: F401

    from src.checklist.engine import load_rules, run_checklist
    from src.checklist.reporter import generate_report

    # Parse required data
    from src.parsers.matrix_parser import parse_matrix
    from src.parsers.profile_parser import parse_profile
    from src.parsers.component_parser import parse_components
    from src.parsers.eda_parser import parse_eda_data
    from src.parsers.misc_parser import parse_info

    step_name = list(job.steps.keys())[0]
    step = job.steps[step_name]

    job_data = {}

    # Job info
    if job.misc_info_path:
        job_data["job_info"] = parse_info(job.misc_info_path)

    # Matrix
    steps, layers = parse_matrix(job.matrix_path)
    job_data["matrix_layers"] = layers

    # Profile
    if step.profile:
        job_data["profile"] = parse_profile(step.profile)

    # EDA
    if step.eda_data:
        job_data["eda_data"] = parse_eda_data(step.eda_data)

    # Components
    for layer_name, layer_paths in step.layers.items():
        if layer_paths.components:
            comps = parse_components(layer_paths.components)
            if "top" in layer_name:
                job_data["components_top"] = comps
                print(f"  Loaded {len(comps)} top components")
            else:
                job_data["components_bot"] = comps
                print(f"  Loaded {len(comps)} bottom components")

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
    job_name = job_data.get("job_info", {})
    if hasattr(job_name, "job_name"):
        job_name = job_name.job_name
    else:
        job_name = job.job_name

    generate_report(results, output_path, job_name=job_name)

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

    # view-top command
    p_vtop = subparsers.add_parser("view-top", help="View top-side components")
    p_vtop.add_argument("odb_path", help="Path to ODB++ archive or directory")
    p_vtop.add_argument("--layers", nargs="*", help="Additional layer names to load and display")

    # view-bot command
    p_vbot = subparsers.add_parser("view-bot", help="View bottom-side components")
    p_vbot.add_argument("odb_path", help="Path to ODB++ archive or directory")
    p_vbot.add_argument("--layers", nargs="*", help="Additional layer names to load and display")

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
    elif args.command == "view-top":
        cmd_view_top(args)
    elif args.command == "view-bot":
        cmd_view_bot(args)
    elif args.command == "check":
        cmd_check(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
