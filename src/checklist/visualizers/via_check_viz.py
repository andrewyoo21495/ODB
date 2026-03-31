"""Shared visualization for VIA presence check rules.

Produces one PNG per component showing pad outlines colour-coded by
via presence (green = has via, red = no via) with nearby vias drawn as
small circles.

Used by: CKL-01-002, CKL-03-004, CKL-03-005, CKL-03-013.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Circle, Polygon

from src.checklist.geometry_utils import (
    build_toeprint_lookup,
    count_vias_at_pad,
    lookup_resolved_pads_for_pin,
    _get_pad_polygon_board,
    _resolved_pad_polygon,
)
from src.visualizer.component_overlay import transform_point


def _build_pin_viz_data(comp, pkg, via_positions, is_bottom,
                        fid_resolved=None, signal_layer_name=None,
                        pin_indices=None):
    """Analyse each pin of *comp* and return per-pin visualisation data.

    Parameters
    ----------
    pin_indices : set[int] | None
        If provided, only include these pin indices. Used for rules that
        check only a subset of pads (e.g. outermost pads).

    Returns a list of dicts with keys: pin_name, bx, by, via_count, poly.
    """
    toep_by_pin = build_toeprint_lookup(comp, pkg)
    results = []

    for pin_idx, pin in enumerate(pkg.pins):
        if pin_indices is not None and pin_idx not in pin_indices:
            continue

        tp = toep_by_pin.get(pin_idx)

        if tp is not None:
            bx, by = tp.x, tp.y
        else:
            bx, by = transform_point(pin.center.x, pin.center.y, comp,
                                     is_bottom=is_bottom)

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

        # Pad polygon: prefer FID-resolved, fallback to EDA pin outline
        poly = None
        if rpads:
            for rpf in rpads:
                poly = _resolved_pad_polygon(rpf, is_bottom=is_bottom)
                if poly is not None:
                    break
        if poly is None:
            poly = _get_pad_polygon_board(pin, comp, is_bottom=is_bottom)

        results.append({
            "pin_name": pin.name or str(pin_idx),
            "bx": bx,
            "by": by,
            "via_count": via_count,
            "poly": poly,
        })

    return results


def render_via_check_image(
    comp, pkg, via_positions, is_bottom,
    output_path: Path, *,
    rule_id: str = "CKL-03-013",
    comp_type: str = "Component",
    fid_resolved=None,
    signal_layer_name=None,
    pin_indices=None,
) -> Path:
    """Render a single component's pads + vias to a PNG file.

    Parameters
    ----------
    comp : Component
    pkg : Package
    via_positions : set[tuple[float, float]]
    is_bottom : bool
    output_path : Path
    rule_id : str
    comp_type : str – e.g. "MIC", "PMIC", "Hall IC", "Axis Sensor"
    fid_resolved : dict, optional
    signal_layer_name : str, optional
    pin_indices : set[int] | None
        If provided, only visualise these pin indices.

    Returns
    -------
    Path
    """
    pin_data = _build_pin_viz_data(
        comp, pkg, via_positions, is_bottom,
        fid_resolved=fid_resolved,
        signal_layer_name=signal_layer_name,
        pin_indices=pin_indices,
    )

    if not pin_data:
        return output_path

    # --- figure setup --------------------------------------------------------
    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    layer_str = "Bottom" if is_bottom else "Top"
    ax.set_title(
        f"{comp.comp_name} ({comp.part_name}) — {layer_str} Layer\n"
        f"{rule_id}: VIA presence on {comp_type} pads",
        fontsize=12, fontweight="bold",
    )

    # Compute viewport from pad extents
    pad_xs, pad_ys = [], []
    for r in pin_data:
        pad_xs.append(r["bx"])
        pad_ys.append(r["by"])
        if r["poly"] is not None:
            pad_xs.extend(r["poly"][:, 0])
            pad_ys.extend(r["poly"][:, 1])

    if not pad_xs:
        plt.close(fig)
        return output_path

    cx = (max(pad_xs) + min(pad_xs)) / 2
    cy = (max(pad_ys) + min(pad_ys)) / 2
    span = max(max(pad_xs) - min(pad_xs), max(pad_ys) - min(pad_ys), 0.5)
    margin = span * 0.5
    ax.set_xlim(cx - span / 2 - margin, cx + span / 2 + margin)
    ax.set_ylim(cy - span / 2 - margin, cy + span / 2 + margin)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)

    # --- draw nearby vias ----------------------------------------------------
    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    for vx, vy in via_positions:
        if xlim[0] <= vx <= xlim[1] and ylim[0] <= vy <= ylim[1]:
            ax.add_patch(Circle((vx, vy), 0.02, facecolor="gray",
                                edgecolor="dimgray", alpha=0.7, linewidth=0.3))

    # --- draw pads -----------------------------------------------------------
    for r in pin_data:
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

        ax.annotate(
            f"Pin {r['pin_name']}\nvias={r['via_count']}",
            (r["bx"], r["by"]),
            textcoords="offset points", xytext=(12, 12),
            fontsize=7, color=label_color,
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                      edgecolor=label_color, alpha=0.8),
            arrowprops=dict(arrowstyle="->", color=label_color, lw=0.8),
        )

    # Component origin marker
    ax.plot(comp.x, comp.y, "x", color="blue", markersize=10, markeredgewidth=2)

    # --- legend --------------------------------------------------------------
    legend_elements = [
        mpatches.Patch(facecolor="#90EE90", edgecolor="darkgreen", alpha=0.5,
                       label="Pad WITH via(s)"),
        mpatches.Patch(facecolor="#FFB0B0", edgecolor="darkred", alpha=0.5,
                       label="Pad WITHOUT via"),
        mpatches.Patch(facecolor="gray", edgecolor="dimgray", alpha=0.7,
                       label=f"Via ({layer_str} layer only)"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", fontsize=8)

    # --- save ----------------------------------------------------------------
    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path
