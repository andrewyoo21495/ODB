"""Debug script for via-on-pad detection algorithm (geometry-based, layer-aware).

Validates via detection using actual pad shape containment with layer-specific
via positions:
- Component Z1 (known truth: pins 1,2,5 have 1 via each; pins 3,4 have none)
- Randomly selected components from top and bottom layers
- Previously affected components

Generates visualization images showing pad outlines and via positions.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Circle, Polygon
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from main import _load_from_cache
from src.models import Component, Package, PadRecord, Pin, Toeprint
from src.checklist.geometry_utils import (
    build_toeprint_lookup,
    build_via_position_set,
    count_vias_at_pad,
    lookup_resolved_pads_for_pin,
    _get_pad_polygon_board,
    _resolved_pad_polygon,
)
from src.visualizer.component_overlay import transform_point
from src.visualizer.fid_lookup import (
    build_fid_map,
    resolve_fid_features,
    _find_top_bottom_signal_layers,
)


def load_data():
    cache_dir = Path("cache")
    data = _load_from_cache(cache_dir, "designodb_rigidflex")
    return data


def analyze_component(comp, packages, via_positions, is_bottom, label="",
                      fid_resolved=None, signal_layer_name=None):
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        print(f"  [SKIP] Invalid pkg_ref={comp.pkg_ref}")
        return []

    pkg = packages[comp.pkg_ref]
    toep_by_pin = build_toeprint_lookup(comp, pkg)
    layer_str = "Bottom" if is_bottom else "Top"

    print(f"\n--- {label}{comp.comp_name} (part={comp.part_name}, layer={layer_str}) ---")
    print(f"  Position: ({comp.x:.4f}, {comp.y:.4f}), Rotation: {comp.rotation}, Mirror: {comp.mirror}")
    print(f"  Package: {len(pkg.pins)} pins, toeprints: {len(comp.toeprints)}")

    results = []
    for pin_idx, pin in enumerate(pkg.pins):
        tp = toep_by_pin.get(pin_idx)

        if tp is not None:
            bx, by = tp.x, tp.y
            coord_src = "toeprint"
        else:
            bx, by = transform_point(pin.center.x, pin.center.y, comp,
                                      is_bottom=is_bottom)
            coord_src = "transform"

        # Look up FID-resolved pad features for this pin
        rpads = None
        if fid_resolved:
            rpads = lookup_resolved_pads_for_pin(
                fid_resolved, comp, is_bottom,
                pin_idx, signal_layer_name=signal_layer_name,
            )

        via_count = count_vias_at_pad(
            comp, pin.center.x, pin.center.y,
            via_positions, is_bottom=is_bottom,
            toeprint=tp, pin=pin,
            resolved_pads=rpads,
        )

        # Get polygon for visualization — prefer FID-resolved, fallback to EDA pin outline
        poly = None
        pad_src = "none"
        if rpads:
            for rpf in rpads:
                poly = _resolved_pad_polygon(rpf, is_bottom=is_bottom)
                if poly is not None:
                    pad_src = f"FID({rpf.symbol.name})"
                    break
        if poly is None:
            poly = _get_pad_polygon_board(pin, comp, is_bottom=is_bottom)
            if poly is not None:
                pad_src = "EDA-pin-outline"

        pad_info = ""
        if poly is not None:
            xmin, ymin = poly.min(axis=0)
            xmax, ymax = poly.max(axis=0)
            pad_info = f" pad_size=({xmax-xmin:.3f}x{ymax-ymin:.3f}) [{pad_src}]"

        pin_name = pin.name or str(pin_idx)
        print(f"  Pin {pin_name}: board=({bx:.4f}, {by:.4f}) [{coord_src}]{pad_info}"
              f" -> vias={via_count}")

        results.append({
            "pin_idx": pin_idx,
            "pin_name": pin_name,
            "pin": pin,
            "bx": bx, "by": by,
            "coord_src": coord_src,
            "via_count": via_count,
            "poly": poly,
            "toeprint": tp,
        })

    return results


def visualize_component(comp, packages, via_positions, is_bottom, results,
                        output_path, title_extra=""):
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return

    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    layer_str = "Bottom" if is_bottom else "Top"
    ax.set_title(f"{comp.comp_name} ({comp.part_name}) - {layer_str} Layer{title_extra}",
                 fontsize=12, fontweight="bold")

    pad_xs, pad_ys = [], []
    for r in results:
        pad_xs.append(r["bx"])
        pad_ys.append(r["by"])
        if r["poly"] is not None:
            pad_xs.extend(r["poly"][:, 0])
            pad_ys.extend(r["poly"][:, 1])

    if not pad_xs:
        plt.close(fig)
        return

    cx = (max(pad_xs) + min(pad_xs)) / 2
    cy = (max(pad_ys) + min(pad_ys)) / 2
    span = max(max(pad_xs) - min(pad_xs), max(pad_ys) - min(pad_ys), 0.5)
    margin = span * 0.5
    ax.set_xlim(cx - span/2 - margin, cx + span/2 + margin)
    ax.set_ylim(cy - span/2 - margin, cy + span/2 + margin)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)

    # Draw nearby vias (only those belonging to this layer)
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    nearby_vias = [(vx, vy) for vx, vy in via_positions
                   if xlim[0] <= vx <= xlim[1] and ylim[0] <= vy <= ylim[1]]

    for vx, vy in nearby_vias:
        ax.add_patch(Circle((vx, vy), 0.02, facecolor="gray",
                            edgecolor="dimgray", alpha=0.7, linewidth=0.3))

    # Draw pad outlines and labels
    for r in results:
        has_via = r["via_count"] > 0
        fill_color = "#90EE90" if has_via else "#FFB0B0"
        edge_color = "darkgreen" if has_via else "darkred"
        label_color = "darkgreen" if has_via else "darkred"

        if r["poly"] is not None:
            ax.add_patch(Polygon(r["poly"], closed=True,
                                 facecolor=fill_color, edgecolor=edge_color,
                                 alpha=0.5, linewidth=1.5))
        else:
            ax.add_patch(Circle((r["bx"], r["by"]), 0.08,
                                facecolor=fill_color, edgecolor=edge_color,
                                alpha=0.5, linewidth=1.5))

        ax.plot(r["bx"], r["by"], ".", color=edge_color, markersize=3)

        ax.annotate(f"Pin {r['pin_name']}\nvias={r['via_count']}",
                    (r["bx"], r["by"]),
                    textcoords="offset points", xytext=(12, 12),
                    fontsize=7, color=label_color,
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                              edgecolor=label_color, alpha=0.8),
                    arrowprops=dict(arrowstyle="->", color=label_color, lw=0.8))

    ax.plot(comp.x, comp.y, "x", color="blue", markersize=10, markeredgewidth=2)

    legend_elements = [
        mpatches.Patch(facecolor="#90EE90", edgecolor="darkgreen", alpha=0.5,
                       label="Pad WITH via(s)"),
        mpatches.Patch(facecolor="#FFB0B0", edgecolor="darkred", alpha=0.5,
                       label="Pad WITHOUT via"),
        mpatches.Patch(facecolor="gray", edgecolor="dimgray", alpha=0.7,
                       label=f"Via ({layer_str} layer only)"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", fontsize=8)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> Saved: {output_path}")


def main():
    print("=" * 70)
    print("VIA-ON-PAD DEBUG (Geometry-Based, Layer-Aware)")
    print("=" * 70)

    data = load_data()
    components_top = data.get("components_top", [])
    components_bot = data.get("components_bot", [])
    eda = data.get("eda_data")
    layers_data = data.get("layers_data", {})
    packages = eda.packages if eda else []

    print(f"\nLoaded: {len(components_top)} top, {len(components_bot)} bottom, "
          f"{len(packages)} packages, {len(layers_data)} layers")

    # Build layer-specific via position sets
    via_top = build_via_position_set(eda, layers_data, is_bottom=False)
    via_bot = build_via_position_set(eda, layers_data, is_bottom=True)
    print(f"Via positions - Top layer: {len(via_top)}, Bottom layer: {len(via_bot)}")

    # Build FID-resolved pad lookup for actual copper pad geometry
    fid_resolved = {}
    top_sig_name, bot_sig_name = None, None
    if eda and layers_data:
        fid_map = build_fid_map(eda)
        fid_resolved = resolve_fid_features(
            fid_map, eda.layer_names, layers_data)
        top_sig_name, bot_sig_name = _find_top_bottom_signal_layers(layers_data)
        print(f"FID resolved: {len(fid_resolved)} pin entries")
        print(f"Signal layers: top={top_sig_name}, bottom={bot_sig_name}")

    out_dir = Path("debug_via_images")
    out_dir.mkdir(exist_ok=True)

    # === TEST 1: Component Z1 (known truth) ===
    print("\n" + "=" * 70)
    print("TEST 1: Component Z1 (expected: pins 1,2,5=via; pins 3,4=no via)")
    print("=" * 70)

    z1 = next((c for c in components_top if c.comp_name == "Z1"), None)
    z1_is_bottom = False
    if z1 is None:
        z1 = next((c for c in components_bot if c.comp_name == "Z1"), None)
        z1_is_bottom = True

    if z1:
        z1_vias = via_bot if z1_is_bottom else via_top
        z1_sig = bot_sig_name if z1_is_bottom else top_sig_name
        results_z1 = analyze_component(z1, packages, z1_vias,
                                        z1_is_bottom, label="[Z1] ",
                                        fid_resolved=fid_resolved,
                                        signal_layer_name=z1_sig)
        visualize_component(z1, packages, z1_vias, z1_is_bottom,
                            results_z1, out_dir / "Z1_via_check.png",
                            title_extra="\n(Expected: pins 1,2,5=1 via; pins 3,4=0 vias)")

        expected = {"1": 1, "2": 1, "3": 0, "4": 0, "5": 1}
        print(f"\n  === Z1 VALIDATION ===")
        all_match = True
        for r in results_z1:
            exp = expected.get(r["pin_name"], "?")
            actual_has = r["via_count"] > 0
            exp_has = exp > 0 if isinstance(exp, int) else None
            match = "OK" if actual_has == exp_has else "MISMATCH"
            if match == "MISMATCH":
                all_match = False
            print(f"    Pin {r['pin_name']}: expected={'>=1' if exp else '0'}, "
                  f"got={r['via_count']} -> {match}")
        print(f"  {'[PASS]' if all_match else '[FAIL]'} Z1 validation")

    # === TEST 2: Random TOP layer components ===
    print("\n" + "=" * 70)
    print("TEST 2: Random TOP layer components")
    print("=" * 70)

    random.seed(42)
    top_candidates = [c for c in components_top
                      if 0 <= c.pkg_ref < len(packages)
                      and 2 <= len(packages[c.pkg_ref].pins) <= 20]
    sample_top = random.sample(top_candidates, min(3, len(top_candidates)))

    for comp in sample_top:
        results = analyze_component(comp, packages, via_top, False,
                                     label="[TOP] ",
                                     fid_resolved=fid_resolved,
                                     signal_layer_name=top_sig_name)
        safe_name = comp.comp_name.replace("/", "_")
        visualize_component(comp, packages, via_top, False, results,
                            out_dir / f"TOP_{safe_name}_via_check.png")

    # === TEST 3: Random BOTTOM layer components ===
    print("\n" + "=" * 70)
    print("TEST 3: Random BOTTOM layer components")
    print("=" * 70)

    bot_candidates = [c for c in components_bot
                      if 0 <= c.pkg_ref < len(packages)
                      and 2 <= len(packages[c.pkg_ref].pins) <= 20]
    sample_bot = random.sample(bot_candidates, min(3, len(bot_candidates)))

    for comp in sample_bot:
        results = analyze_component(comp, packages, via_bot, True,
                                     label="[BOT] ",
                                     fid_resolved=fid_resolved,
                                     signal_layer_name=bot_sig_name)
        safe_name = comp.comp_name.replace("/", "_")
        visualize_component(comp, packages, via_bot, True, results,
                            out_dir / f"BOT_{safe_name}_via_check.png")

    # === TEST 4: Previously affected components ===
    print("\n" + "=" * 70)
    print("TEST 4: Previously affected components")
    print("=" * 70)

    target_names = ["R129", "R85", "C112", "D1"]
    for name in target_names:
        comp = next((c for c in components_top if c.comp_name == name), None)
        is_bot = False
        if comp is None:
            comp = next((c for c in components_bot if c.comp_name == name), None)
            is_bot = True
        if comp:
            vias = via_bot if is_bot else via_top
            sig = bot_sig_name if is_bot else top_sig_name
            results = analyze_component(comp, packages, vias, is_bot,
                                         label="[FIX-CHECK] ",
                                         fid_resolved=fid_resolved,
                                         signal_layer_name=sig)
            safe_name = comp.comp_name.replace("/", "_")
            visualize_component(comp, packages, vias, is_bot, results,
                                out_dir / f"FIXED_{safe_name}_via_check.png")

    print("\n" + "=" * 70)
    print(f"All images saved to: {out_dir.resolve()}")
    print("=" * 70)


if __name__ == "__main__":
    main()
