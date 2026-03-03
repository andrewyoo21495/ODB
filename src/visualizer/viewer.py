"""Interactive matplotlib viewer with layer toggling.

Layout
------
Left  (63 % width): main board canvas.
Top-right           : layer / component checkbox panel.
Bottom-right        : selected component information panel.

Interaction
-----------
* Toggle layers via checkboxes on the top-right panel.
* Scroll the checkbox list when it overflows.
* Click anywhere on the board canvas to select the nearest visible component
  pin; its metadata is displayed in the bottom-right info panel.
"""

from __future__ import annotations

from typing import Optional

import matplotlib.pyplot as plt
from matplotlib.widgets import CheckButtons

from src.models import (
    Component, EdaData, LayerFeatures, MatrixLayer, Profile,
    StrokeFont, UserSymbol,
)
from src.visualizer.layer_renderer import LAYER_COLORS, render_layer
from src.visualizer.component_overlay import draw_components
from src.visualizer.renderer import _draw_profile

# Sentinel keys used in the checkbox list
COMP_TOP_KEY     = "__components_top__"
COMP_BOT_KEY     = "__components_bot__"
COMP_OUTLINE_KEY = "__component_outlines__"

# Right-panel geometry (normalised figure coordinates)
_PANEL_LEFT  = 0.72
_PANEL_WIDTH = 0.26
_INFO_BOTTOM = 0.04
_INFO_HEIGHT = 0.34          # info panel: y ∈ [0.04, 0.38]
_CB_TOP      = 0.97          # checkbox panel anchored to top
_CB_MAX_H    = 0.54          # checkbox panel max height (leaves room for info)
_MAIN_POS    = [0.04, 0.05, 0.63, 0.90]


class PcbViewer:
    """Interactive PCB viewer with layer toggle controls."""

    def __init__(self,
                 profile: Profile,
                 layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
                 components_top: list[Component] = None,
                 components_bot: list[Component] = None,
                 eda_data: EdaData = None,
                 user_symbols: dict[str, UserSymbol] = None,
                 font: StrokeFont = None):
        self.profile        = profile
        self.layers_data    = layers_data
        self.components_top = components_top or []
        self.components_bot = components_bot or []
        self.eda_data       = eda_data
        self.user_symbols   = user_symbols or {}
        self.font           = font
        self._selected_comp: Optional[Component] = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def show(self, initial_visible: list[str] = None,
             figsize: tuple[float, float] = (16, 10)):
        """Launch the interactive viewer.

        Args:
            initial_visible: Layer names (and/or sentinel keys) to show
                             initially.  None or [] = PCB outline only.
            figsize:         Figure dimensions in inches.
        """
        if initial_visible is None:
            initial_visible = []

        self.fig = plt.figure(figsize=figsize)
        self.ax  = self.fig.add_axes(_MAIN_POS)
        self.ax.set_aspect("equal")
        self.ax.set_title("ODB++ PCB Viewer (toggle layers with checkboxes)")

        # Board outline (always visible)
        if self.profile and self.profile.surface:
            _draw_profile(self.ax, self.profile)

        # Sorted layer list
        all_layers = sorted(
            self.layers_data.keys(),
            key=lambda n: self.layers_data[n][1].row,
        )

        # Render initially visible layers
        for layer_name in all_layers:
            if layer_name not in initial_visible:
                continue
            features, matrix_layer = self.layers_data[layer_name]
            color = LAYER_COLORS.get(matrix_layer.type, "#CC0000")
            render_layer(self.ax, features, color=color,
                         layer_type=matrix_layer.type,
                         alpha=0.7, user_symbols=self.user_symbols,
                         font=self.font)

        # Component overlays (only if in initial_visible)
        packages = self.eda_data.packages if self.eda_data else None
        if self.components_top and COMP_TOP_KEY in initial_visible:
            draw_components(self.ax, self.components_top, packages,
                            color="#87CEEB", alpha=0.4,
                            show_pads=True, show_pkg_outlines=False)
        if self.components_bot and COMP_BOT_KEY in initial_visible:
            draw_components(self.ax, self.components_bot, packages,
                            color="#FFB6C1", alpha=0.4,
                            show_pads=True, show_pkg_outlines=False)
        if COMP_OUTLINE_KEY in initial_visible:
            self._draw_outlines_initial(packages, set(initial_visible))

        # UI panels
        self._setup_checkboxes(all_layers, initial_visible)
        self._setup_info_panel()

        # Axis labels and interaction
        units      = self.profile.units if self.profile else "INCH"
        unit_label = "inches" if units == "INCH" else "mm"
        self.ax.set_xlabel(f"X ({unit_label})")
        self.ax.set_ylabel(f"Y ({unit_label})")
        self.ax.grid(True, alpha=0.2)
        self.ax.format_coord = self._format_coord
        self.fig.canvas.mpl_connect("button_press_event", self._on_click)

        plt.show()

    # ------------------------------------------------------------------
    # Checkbox panel
    # ------------------------------------------------------------------

    def _setup_checkboxes(self, all_layers: list[str], visible_items: list[str]):
        """Create layer toggle checkboxes including component overlay entries."""
        display_layers = [
            name for name in all_layers
            if self.layers_data[name][1].type not in ("DIELECTRIC", "DRILL")
        ]

        self._display_items: list[str] = list(display_layers)
        labels:  list[str]  = []
        actives: list[bool] = []

        for name in display_layers:
            ml = self.layers_data[name][1]
            labels.append(f"{name[:22]} ({ml.type[:4]})")
            actives.append(name in visible_items)

        if self.components_top:
            self._display_items.append(COMP_TOP_KEY)
            labels.append(f"Components Top ({len(self.components_top)})")
            actives.append(COMP_TOP_KEY in visible_items)

        if self.components_bot:
            self._display_items.append(COMP_BOT_KEY)
            labels.append(f"Components Bot ({len(self.components_bot)})")
            actives.append(COMP_BOT_KEY in visible_items)

        if self.components_top or self.components_bot:
            self._display_items.append(COMP_OUTLINE_KEY)
            labels.append("Comp. Outlines")
            actives.append(COMP_OUTLINE_KEY in visible_items)

        if not self._display_items:
            return

        n_items      = len(self._display_items)
        item_height  = 0.04
        total_needed = n_items * item_height
        checkbox_h   = min(_CB_MAX_H, total_needed)
        panel_bottom = _CB_TOP - checkbox_h

        rax = self.fig.add_axes([_PANEL_LEFT, panel_bottom,
                                  _PANEL_WIDTH, checkbox_h])

        self._check = CheckButtons(rax, labels, actives)
        for text in self._check.labels:
            text.set_fontsize(10)

        self._scroll_enabled = total_needed > _CB_MAX_H
        if self._scroll_enabled:
            visible_frac              = checkbox_h / total_needed
            self._scroll_visible_frac = visible_frac
            self._scroll_pos          = 1.0 - visible_frac
            self._scroll_axes         = rax
            rax.set_ylim(self._scroll_pos, self._scroll_pos + visible_frac)
            self.fig.canvas.mpl_connect("scroll_event", self._on_scroll)

        self._visible_set = set(
            item for item in visible_items if item in self._display_items
        )
        self._check.on_clicked(self._on_checkbox_click)

    def _on_scroll(self, event):
        """Scroll the checkbox list when it overflows the panel."""
        if not self._scroll_enabled:
            return
        if event.inaxes != self._scroll_axes:
            return
        step = 1.0 / len(self._display_items)
        if event.button == "up":
            self._scroll_pos = min(1.0 - self._scroll_visible_frac,
                                   self._scroll_pos + step)
        elif event.button == "down":
            self._scroll_pos = max(0.0, self._scroll_pos - step)
        self._scroll_axes.set_ylim(self._scroll_pos,
                                   self._scroll_pos + self._scroll_visible_frac)
        self.fig.canvas.draw_idle()

    def _on_checkbox_click(self, label: str):
        """Handle checkbox toggle – full redraw approach."""
        for i, text in enumerate(self._check.labels):
            if text.get_text() == label:
                item = self._display_items[i]
                if item in self._visible_set:
                    self._visible_set.remove(item)
                else:
                    self._visible_set.add(item)
                break
        self._redraw()

    # ------------------------------------------------------------------
    # Component info panel
    # ------------------------------------------------------------------

    def _setup_info_panel(self):
        """Create the bottom-right component information panel."""
        self._info_ax = self.fig.add_axes(
            [_PANEL_LEFT, _INFO_BOTTOM, _PANEL_WIDTH, _INFO_HEIGHT]
        )
        self._info_ax.set_facecolor("#f5f5f8")
        self._info_ax.set_title("Component Info", fontsize=9, pad=3)
        self._info_ax.tick_params(left=False, bottom=False,
                                   labelleft=False, labelbottom=False)
        for spine in self._info_ax.spines.values():
            spine.set_linewidth(0.5)
        self._info_ax.text(0.5, 0.55, "Click on a component",
                           ha="center", va="center", fontsize=9,
                           color="#aaaaaa", transform=self._info_ax.transAxes)
        self._info_ax.text(0.5, 0.45, "pin to view info",
                           ha="center", va="center", fontsize=9,
                           color="#aaaaaa", transform=self._info_ax.transAxes)

    def _update_info_panel(self, comp: Component):
        """Populate the info panel with data for *comp*."""
        from src.checklist.component_classifier import classify_component

        ax = self._info_ax
        ax.clear()
        ax.set_facecolor("#f5f5f8")
        ax.set_title("Component Info", fontsize=9, pad=3)
        ax.tick_params(left=False, bottom=False,
                       labelleft=False, labelbottom=False)
        for spine in ax.spines.values():
            spine.set_linewidth(0.5)

        rows: list[tuple[str, str]] = []
        rows.append(("title", comp.comp_name))
        rows.append(("kv", f"Part:  {comp.part_name or '—'}"))
        rows.append(("kv", f"Type:  {classify_component(comp).value}"))

        for key in ("TYPE", "DEVICE_TYPE", "VALUE"):
            val = comp.properties.get(key)
            if val:
                rows.append(("kv", f"{key}:  {val}"))

        units  = self.profile.units if self.profile else "INCH"
        unit_s = '"' if units == "INCH" else "mm"
        rows.append(("kv",
                     f"Pos:   ({comp.x:.4f}{unit_s}, {comp.y:.4f}{unit_s})"))
        rows.append(("kv", f"Rot:   {comp.rotation}\u00b0"))

        net_names: list[str] = []
        if self.eda_data and comp.toeprints:
            for tp in comp.toeprints:
                if 0 <= tp.net_num < len(self.eda_data.nets):
                    name = self.eda_data.nets[tp.net_num].name
                    if name and name not in net_names:
                        net_names.append(name)

        if net_names:
            rows.append(("sep", ""))
            rows.append(("kv", f"Nets ({len(net_names)}):"))
            display = ", ".join(net_names[:6])
            if len(net_names) > 6:
                display += f"  +{len(net_names) - 6}"
            rows.append(("small", display))

        if comp.bom_data:
            bom = comp.bom_data
            rows.append(("sep", ""))
            if bom.cpn:
                rows.append(("kv", f"CPN:  {bom.cpn}"))
            if bom.description:
                desc = bom.description
                if len(desc) > 26:
                    desc = desc[:24] + "\u2026"
                rows.append(("small", f"Desc: {desc}"))
            for vendor in bom.vendors[:1]:
                for mpn_entry in vendor.get("mpns", [])[:1]:
                    mpn = mpn_entry["mpn"]
                    if len(mpn) > 22:
                        mpn = mpn[:20] + "\u2026"
                    rows.append(("small", f"MPN:  {mpn}"))

        y         = 0.96
        h_kv      = 0.082
        h_sm      = 0.075
        h_sep     = 0.045

        for style, text in rows:
            if y < 0.02:
                break
            if style == "sep":
                ax.plot([0.03, 0.97], [y - 0.01, y - 0.01],
                        color="#cccccc", linewidth=0.6,
                        transform=ax.transAxes)
                y -= h_sep
                continue
            if style == "title":
                ax.text(0.05, y, text, fontsize=9, fontweight="bold",
                        va="top", transform=ax.transAxes, color="#111111")
                y -= h_kv
            elif style == "kv":
                ax.text(0.05, y, text, fontsize=8,
                        va="top", transform=ax.transAxes, color="#333333")
                y -= h_kv
            else:
                ax.text(0.08, y, text, fontsize=7,
                        va="top", transform=ax.transAxes, color="#555555")
                y -= h_sm

        self.fig.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Click handler
    # ------------------------------------------------------------------

    def _on_click(self, event):
        """Select the nearest visible component on click."""
        if event.inaxes != self.ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        comp = self._find_nearest_component(event.xdata, event.ydata)
        if comp is not None and comp is not self._selected_comp:
            self._selected_comp = comp
            self._update_info_panel(comp)

    def _find_nearest_component(self, x: float, y: float) -> Optional[Component]:
        """Return the component whose nearest toeprint/centroid is closest to (x, y).

        A threshold of 2 % of the current view width prevents accidental
        selection when clicking on empty board space.
        """
        xlim         = self.ax.get_xlim()
        threshold_sq = ((xlim[1] - xlim[0]) * 0.02) ** 2

        best_comp    = None
        best_dist_sq = threshold_sq

        candidates: list[Component] = []
        if COMP_TOP_KEY in self._visible_set:
            candidates.extend(self.components_top)
        if COMP_BOT_KEY in self._visible_set:
            candidates.extend(self.components_bot)

        for comp in candidates:
            for tp in comp.toeprints:
                d = (tp.x - x) ** 2 + (tp.y - y) ** 2
                if d < best_dist_sq:
                    best_dist_sq = d
                    best_comp    = comp
            d = (comp.x - x) ** 2 + (comp.y - y) ** 2
            if d < best_dist_sq:
                best_dist_sq = d
                best_comp    = comp

        return best_comp

    # ------------------------------------------------------------------
    # Redraw
    # ------------------------------------------------------------------

    def _redraw(self):
        """Clear and redraw all visible layers and overlays."""
        self.ax.clear()

        if self.profile and self.profile.surface:
            _draw_profile(self.ax, self.profile)

        for layer_name in self._visible_set:
            if layer_name not in self.layers_data:
                continue
            features, matrix_layer = self.layers_data[layer_name]
            color = LAYER_COLORS.get(matrix_layer.type, "#CC0000")
            render_layer(self.ax, features, color=color,
                         layer_type=matrix_layer.type,
                         alpha=0.7, user_symbols=self.user_symbols,
                         font=self.font)

        packages = self.eda_data.packages if self.eda_data else None

        if COMP_TOP_KEY in self._visible_set and self.components_top:
            draw_components(self.ax, self.components_top, packages,
                            color="#00B7FF", alpha=0.99,
                            show_pads=True, show_pkg_outlines=False)

        if COMP_BOT_KEY in self._visible_set and self.components_bot:
            draw_components(self.ax, self.components_bot, packages,
                            color="#FF3150", alpha=0.99,
                            show_pads=True, show_pkg_outlines=False)

        if COMP_OUTLINE_KEY in self._visible_set:
            self._draw_outlines(packages)

        units      = self.profile.units if self.profile else "INCH"
        unit_label = "inches" if units == "INCH" else "mm"
        self.ax.set_xlabel(f"X ({unit_label})")
        self.ax.set_ylabel(f"Y ({unit_label})")
        self.ax.grid(True, alpha=0.2)
        self.ax.set_aspect("equal")
        self.ax.format_coord = self._format_coord

        self.fig.canvas.draw_idle()

    def _draw_outlines(self, packages):
        """Draw yellow package outlines for currently visible component layers."""
        drew_top = COMP_TOP_KEY in self._visible_set
        drew_bot = COMP_BOT_KEY in self._visible_set

        if drew_top and self.components_top:
            draw_components(self.ax, self.components_top, packages,
                            color="#FFFF00", alpha=0.95,
                            show_pads=False, show_pkg_outlines=True)
        if drew_bot and self.components_bot:
            draw_components(self.ax, self.components_bot, packages,
                            color="#FFFF00", alpha=0.95,
                            show_pads=False, show_pkg_outlines=True)
        # Outline-only view when no component pad layer is checked
        if not drew_top and not drew_bot:
            all_comps = self.components_top + self.components_bot
            if all_comps:
                draw_components(self.ax, all_comps, packages,
                                color="#FFFF00", alpha=0.95,
                                show_pads=False, show_pkg_outlines=True)

    def _draw_outlines_initial(self, packages, visible_set: set):
        """Same as _draw_outlines but uses a passed visible_set for initial render."""
        drew_top = COMP_TOP_KEY in visible_set
        drew_bot = COMP_BOT_KEY in visible_set
        if drew_top and self.components_top:
            draw_components(self.ax, self.components_top, packages,
                            color="#FFFF00", alpha=0.95,
                            show_pads=False, show_pkg_outlines=True)
        if drew_bot and self.components_bot:
            draw_components(self.ax, self.components_bot, packages,
                            color="#FFFF00", alpha=0.95,
                            show_pads=False, show_pkg_outlines=True)
        if not drew_top and not drew_bot:
            all_comps = self.components_top + self.components_bot
            if all_comps:
                draw_components(self.ax, all_comps, packages,
                                color="#FFFF00", alpha=0.95,
                                show_pads=False, show_pkg_outlines=True)

    # ------------------------------------------------------------------
    # Coordinate formatter
    # ------------------------------------------------------------------

    def _format_coord(self, x: float, y: float) -> str:
        units = self.profile.units if self.profile else "INCH"
        if units == "INCH":
            return f'x={x:.6f}" y={y:.6f}"'
        return f"x={x:.4f}mm y={y:.4f}mm"
