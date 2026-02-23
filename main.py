"""
ODB++ Processing System — CLI Entry Point

Usage:
    python main.py <path_to_odb>                  # Parse and summarize
    python main.py <path_to_odb> --visualize      # Render all layers
    python main.py <path_to_odb> --layer <name>   # Render a single layer
    python main.py <path_to_odb> --checklist      # Run checklist rules
    python main.py <path_to_odb> --all            # Visualize + checklist
    python main.py <path_to_odb> --output <dir>   # Write outputs to directory
"""

import argparse
import os
import sys


def parse_args():
    parser = argparse.ArgumentParser(
        description='ODB++ PCB Data Processing System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('odb_path', help='Path to ODB++ .tgz, .zip, or directory')
    parser.add_argument('--layer', metavar='NAME',
                        help='Render a single named layer')
    parser.add_argument('--visualize', action='store_true',
                        help='Render all layers to PNG')
    parser.add_argument('--checklist', action='store_true',
                        help='Run checklist rules and export Excel report')
    parser.add_argument('--all', dest='run_all', action='store_true',
                        help='Run both visualization and checklist')
    parser.add_argument('--output', metavar='DIR', default='.',
                        help='Output directory for generated files (default: .)')
    parser.add_argument('--min-spacing', type=float, default=0.2,
                        help='Minimum component spacing threshold (default: 0.2)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose parsing output')
    return parser.parse_args()


def load_model(odb_path: str, verbose: bool):
    from odb_reader import ODBReader
    reader = ODBReader(verbose=verbose)
    print(f"Loading: {odb_path}")
    model = reader.load(odb_path)
    return model


def print_summary(model):
    from models import ODBModel
    print("\n" + "=" * 60)
    print(f"  Product : {model.product_name}")
    print(f"  Units   : {model.units}")
    print(f"  Step    : {model.step_name}")
    print(f"  Layers  : {len(model.layers)}")
    print(f"  Nets    : {len(model.nets)}")

    total_pads  = sum(len(ld.pads)       for ld in model.layer_data.values())
    total_lines = sum(len(ld.lines)      for ld in model.layer_data.values())
    total_arcs  = sum(len(ld.arcs)       for ld in model.layer_data.values())
    total_surfs = sum(len(ld.surfaces)   for ld in model.layer_data.values())
    total_comps = sum(len(ld.components) for ld in model.layer_data.values())

    print(f"  Pads    : {total_pads}")
    print(f"  Lines   : {total_lines}")
    print(f"  Arcs    : {total_arcs}")
    print(f"  Surfaces: {total_surfs}")
    print(f"  Comps   : {total_comps}")
    print("=" * 60)

    print("\nLayer Stack:")
    for layer in model.layers:
        ld = model.layer_data.get(layer.name)
        if ld:
            feat_count = (len(ld.pads) + len(ld.lines) +
                          len(ld.arcs) + len(ld.surfaces))
            comp_count = len(ld.components)
        else:
            feat_count, comp_count = 0, 0
        print(f"  [{layer.index:3d}] {layer.name:<30s} "
              f"{layer.layer_type:<15s} {layer.side:<8s} "
              f"feats={feat_count} comps={comp_count}")


def run_visualization(model, output_dir: str, single_layer: str = None):
    try:
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend for file output
    except ImportError:
        print("ERROR: matplotlib not installed. Run: pip install matplotlib")
        return

    from visualizer import PCBVisualizer
    viz = PCBVisualizer(model)

    os.makedirs(output_dir, exist_ok=True)

    if single_layer:
        if single_layer not in model.layer_data:
            print(f"ERROR: Layer '{single_layer}' not found. "
                  f"Available: {list(model.layer_data.keys())}")
            return
        out_path = os.path.join(output_dir, f'layer_{single_layer}.png')
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(16, 12))
        fig.patch.set_facecolor('#0d0d0d')
        viz.render_layer(single_layer, ax=ax)
        fig.tight_layout()
        fig.savefig(out_path, dpi=150, bbox_inches='tight',
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        print(f"Layer rendered: {out_path}")
    else:
        out_path = os.path.join(output_dir, 'pcb_layers.png')
        viz.render_all_layers(output_path=out_path)


def run_checklist(model, output_dir: str, min_spacing: float):
    from checklist.registry import RuleRegistry
    from checklist.reporter import ExcelReporter
    from checklist.rules import (
        CapacitorConnectorOppositeRule,
        MinSpacingRule,
        ComponentCountRule,
        PolarizedComponentOrientationRule,
    )

    registry = RuleRegistry()
    registry.register(ComponentCountRule())
    registry.register(CapacitorConnectorOppositeRule())
    registry.register(MinSpacingRule(min_distance=min_spacing))
    registry.register(PolarizedComponentOrientationRule())

    print(f"\nRunning {registry.rule_count} checklist rule(s)...")
    results = registry.run_all(model, verbose=True)

    summary = RuleRegistry.summary(results)
    print(f"\nSummary: PASS={summary['PASS']} FAIL={summary['FAIL']} "
          f"WARNING={summary['WARNING']} SKIP={summary['SKIP']}")

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, 'checklist_result.xlsx')
    try:
        reporter = ExcelReporter()
        reporter.export(results, out_path, model.product_name)
    except ImportError as e:
        print(f"WARNING: {e}")
        # Fallback: print to stdout
        print("\nChecklist Results (text fallback):")
        for r in results:
            print(f"  {r}")

    return results


def main():
    args = parse_args()

    # Validate input path
    if not os.path.exists(args.odb_path):
        print(f"ERROR: Path not found: {args.odb_path}")
        sys.exit(1)

    # Load model
    model = load_model(args.odb_path, args.verbose)
    print_summary(model)

    # Determine what to do
    do_vis = args.visualize or args.run_all or bool(args.layer)
    do_chk = args.checklist or args.run_all

    if not do_vis and not do_chk:
        # Default: just show the summary (already done above)
        print("\nTip: Use --visualize, --checklist, or --all to generate outputs.")
        return

    out_dir = args.output
    if do_vis:
        run_visualization(model, out_dir, single_layer=args.layer)

    if do_chk:
        run_checklist(model, out_dir, min_spacing=args.min_spacing)


if __name__ == '__main__':
    main()
