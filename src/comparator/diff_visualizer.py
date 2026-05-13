"""Diff overlay visualizer for component changes between revisions.

Renders a single board-level image per layer showing all components with
color coding by change type:
  - ADDED:     cyan fill
  - REMOVED:   red dashed outline with X marker
  - RELOCATED: yellow fill with arrow from old to new position
  - MODIFIED:  green fill (part name changed)
  - UNCHANGED: light gray, dimmed
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch

from src.comparator.base import ChangeType, ComponentChange
from src.models import Component, Package, Profile, UserSymbol
from src.visualizer.component_overlay import draw_components
from src.visualizer.symbol_renderer import contour_to_vertices


# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

_UNCHANGED_COLOR = "#D3D3D3"
_UNCHANGED_ALPHA = 0.20

_ADDED_COLOR = "#00B0D0"
_ADDED_ALPHA = 0.70

_REMOVED_COLOR = "#CC0000"
_REMOVED_ALPHA = 0.55

_RELOCATED_COLOR_NEW = "#E6B800"
_RELOCATED_ALPHA_NEW = 0.65
_RELOCATED_COLOR_OLD = "#C0A000"
_RELOCATED_ALPHA_OLD = 0.25

_MODIFIED_COLOR = "#2E8B57"
_MODIFIED_ALPHA = 0.65

_BOARD_OUTLINE_COLOR = "royalblue"


def render_diff_overlay(
    old_components: list[Component],
    new_components: list[Component],
    changes: list[ComponentChange],
    profile: Profile | None,
    packages: list[Package] | None,
    user_symbols: dict[str, UserSymbol] | None,
    layer: str,
    comp_side: str,
    output_dir: Path | None = None,
) -> Path | None:
    """Render a diff overlay image for one layer.

    Args:
        old_components: components from old revision for this layer.
        new_components: components from new revision for this layer.
        changes: list of ComponentChange for this layer.
        profile: board outline (from either revision; assumed identical).
        packages: EDA packages list (from the new revision).
        user_symbols: user-defined symbols dict.
        layer: "Top" or "Bottom".
        comp_side: "T" or "B".
        output_dir: directory for temp image file. If None, uses tempdir.

    Returns:
        Path to the generated PNG file, or None on failure.
    """
    if not changes and not new_components:
        return None

    # Classify components by change type
    changed_names = {ch.comp_name: ch for ch in changes}
    unchanged_comps = [c for c in new_components
                       if c.comp_name not in changed_names]

    added_comps = [c for c in new_components
                   if changed_names.get(c.comp_name, None)
                   and changed_names[c.comp_name].change_type == ChangeType.ADDED]

    removed_comps = [c for c in old_components
                     if changed_names.get(c.comp_name, None)
                     and changed_names[c.comp_name].change_type == ChangeType.REMOVED]

    relocated_changes = [ch for ch in changes
                         if ch.change_type == ChangeType.RELOCATED]
    relocated_new_comps = [c for c in new_components
                           if changed_names.get(c.comp_name, None)
                           and changed_names[c.comp_name].change_type == ChangeType.RELOCATED]

    modified_comps = [c for c in new_components
                      if changed_names.get(c.comp_name, None)
                      and changed_names[c.comp_name].change_type == ChangeType.MODIFIED]

    # Figure setup
    fig, ax = plt.subplots(1, 1, figsize=(14, 10))
    ax.set_aspect("equal")
    ax.set_facecolor("white")

    # Draw board outline
    if profile and profile.surface:
        for contour in profile.surface.contours:
            verts = contour_to_vertices(contour)
            if len(verts) < 3:
                continue
            ax.plot(verts[:, 0], verts[:, 1],
                    color=_BOARD_OUTLINE_COLOR, linewidth=1.5)
            ax.fill(verts[:, 0], verts[:, 1],
                    alpha=0.03, color=_BOARD_OUTLINE_COLOR)
            if contour.is_island:
                margin_x = (verts[:, 0].max() - verts[:, 0].min()) * 0.05
                margin_y = (verts[:, 1].max() - verts[:, 1].min()) * 0.05
                ax.set_xlim(verts[:, 0].min() - margin_x,
                            verts[:, 0].max() + margin_x)
                ax.set_ylim(verts[:, 1].min() - margin_y,
                            verts[:, 1].max() + margin_y)

    pkg_list = packages or []

    # 1. Unchanged components (dimmed background)
    if unchanged_comps:
        draw_components(ax, unchanged_comps, pkg_list,
                        color=_UNCHANGED_COLOR, alpha=_UNCHANGED_ALPHA,
                        show_pads=True, show_pkg_outlines=False,
                        show_labels=False,
                        user_symbols=user_symbols or {},
                        comp_side=comp_side)

    # 2. ADDED components (cyan)
    if added_comps:
        draw_components(ax, added_comps, pkg_list,
                        color=_ADDED_COLOR, alpha=_ADDED_ALPHA,
                        show_pads=True, show_pkg_outlines=False,
                        show_labels=True, font_size=5,
                        user_symbols=user_symbols or {},
                        comp_side=comp_side)

    # 3. REMOVED components (red, dashed outline + X marker)
    if removed_comps:
        draw_components(ax, removed_comps, pkg_list,
                        color=_REMOVED_COLOR, alpha=_REMOVED_ALPHA,
                        show_pads=True, show_pkg_outlines=False,
                        show_labels=True, font_size=5,
                        user_symbols=user_symbols or {},
                        comp_side=comp_side)
        # Add X markers at removed component positions
        for comp in removed_comps:
            ax.plot(comp.x, comp.y, "x",
                    color=_REMOVED_COLOR, markersize=8,
                    markeredgewidth=2, zorder=10)

    # 4. RELOCATED components (yellow new position + arrow from old)
    if relocated_new_comps:
        draw_components(ax, relocated_new_comps, pkg_list,
                        color=_RELOCATED_COLOR_NEW, alpha=_RELOCATED_ALPHA_NEW,
                        show_pads=True, show_pkg_outlines=False,
                        show_labels=True, font_size=5,
                        user_symbols=user_symbols or {},
                        comp_side=comp_side)

    # Draw arrows from old position to new position for relocated components
    for ch in relocated_changes:
        if (ch.old_x is not None and ch.new_x is not None):
            arrow = FancyArrowPatch(
                (ch.old_x, ch.old_y), (ch.new_x, ch.new_y),
                arrowstyle="-|>",
                color=_RELOCATED_COLOR_OLD,
                linewidth=1.5,
                mutation_scale=12,
                zorder=8,
            )
            ax.add_patch(arrow)
            # Small dot at old position
            ax.plot(ch.old_x, ch.old_y, "o",
                    color=_RELOCATED_COLOR_OLD, markersize=4,
                    markeredgecolor="none", zorder=9)

    # 5. MODIFIED components (green)
    if modified_comps:
        draw_components(ax, modified_comps, pkg_list,
                        color=_MODIFIED_COLOR, alpha=_MODIFIED_ALPHA,
                        show_pads=True, show_pkg_outlines=False,
                        show_labels=True, font_size=5,
                        user_symbols=user_symbols or {},
                        comp_side=comp_side)

    # Title
    n_added = len(added_comps)
    n_removed = len(removed_comps)
    n_relocated = len(relocated_changes)
    n_modified = len(modified_comps)
    ax.set_title(
        f"Component Changes \u2014 {layer} Layer\n"
        f"Added: {n_added}  |  Removed: {n_removed}  |  "
        f"Relocated: {n_relocated}  |  Modified: {n_modified}",
        fontsize=12, fontweight="bold",
    )

    # Legend
    legend_handles = []
    if n_added:
        legend_handles.append(mpatches.Patch(
            facecolor=_ADDED_COLOR, alpha=_ADDED_ALPHA,
            edgecolor=_ADDED_COLOR, label="ADDED"))
    if n_removed:
        legend_handles.append(mpatches.Patch(
            facecolor=_REMOVED_COLOR, alpha=_REMOVED_ALPHA,
            edgecolor=_REMOVED_COLOR, label="REMOVED"))
    if n_relocated:
        legend_handles.append(mpatches.Patch(
            facecolor=_RELOCATED_COLOR_NEW, alpha=_RELOCATED_ALPHA_NEW,
            edgecolor=_RELOCATED_COLOR_NEW, label="RELOCATED"))
    if n_modified:
        legend_handles.append(mpatches.Patch(
            facecolor=_MODIFIED_COLOR, alpha=_MODIFIED_ALPHA,
            edgecolor=_MODIFIED_COLOR, label="MODIFIED"))
    legend_handles.append(mpatches.Patch(
        facecolor=_UNCHANGED_COLOR, alpha=_UNCHANGED_ALPHA,
        edgecolor=_UNCHANGED_COLOR, label="UNCHANGED"))

    if legend_handles:
        ax.legend(handles=legend_handles, loc="upper left", fontsize=8,
                  framealpha=0.9)

    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.grid(False)

    # Save
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="odb_cmp_"))
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"comp_diff_{layer.lower()}.png"
    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)

    return output_path
