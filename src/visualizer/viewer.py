"""Interactive matplotlib + Tkinter viewer with layer toggling.

Layout (standard view mode)
----------------------------
Left  (~240 px): "Layer Selection" Listbox + "Component Info" text panel.
Right (rest)   : matplotlib canvas (black background).

Layout (component view mode)
-----------------------------
Left  (~240 px): Layer radio-buttons, Component Listbox, Display Options,
                 Update button, Component Info text panel.
Right (rest)   : matplotlib canvas (black background).

Interaction
-----------
* Toggle layers by clicking rows in the Layer Selection listbox (view).
* Select components then click "Update Visualization" (view-comp).
* Click anywhere on the canvas to select the nearest visible component pin;
  its metadata is displayed in the Component Info text panel.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from src.models import (
    Component, EdaData, LayerFeatures, MatrixLayer, Profile,
    StrokeFont, UserSymbol,
)
from src.visualizer.layer_renderer import LAYER_COLORS, render_layer
from src.visualizer.component_overlay import draw_components
from src.visualizer.renderer import _draw_profile

# Sentinel keys used in the layer list
COMP_TOP_KEY     = "__components_top__"
COMP_BOT_KEY     = "__components_bot__"
COMP_OUTLINE_KEY = "__component_outlines__"

# ---------------------------------------------------------------------------
# Colour constants  (light UI, black plot area)
# ---------------------------------------------------------------------------
_BG     = "#f4f4f4"   # panel / window background
_BG2    = "#ffffff"   # listbox / text-widget background
_FG     = "#1a1a1a"   # normal foreground text
_SEL_BG = "#1a73e8"   # listbox row selection (blue)
_SEL_FG = "#ffffff"   # listbox selection text
_FONT   = ("Segoe UI", 10)


# ---------------------------------------------------------------------------
# Shared UI helpers
# ---------------------------------------------------------------------------

def _style_axes(ax) -> None:
    """Apply dark-theme styling to a matplotlib Axes after ax.clear()."""
    ax.set_facecolor("#000000")
    ax.tick_params(colors="#000000")
    for spine in ax.spines.values():
        spine.set_color("#000000")


def _make_listbox(parent, **kwargs) -> tuple[tk.Frame, tk.Listbox]:
    """Return (frame, Listbox) with dark multi-select styling and a scrollbar."""
    frame = tk.Frame(
        parent, bg=_BG2,
        highlightbackground="#cccccc", highlightthickness=1,
    )
    scrollbar = tk.Scrollbar(
        frame, orient=tk.VERTICAL,
        bg=_BG, troughcolor="#e0e0e0", relief=tk.FLAT,
    )
    lb = tk.Listbox(
        frame,
        selectmode=tk.MULTIPLE,
        bg=_BG2,
        fg=_FG,
        selectbackground=_SEL_BG,
        selectforeground=_SEL_FG,
        font=_FONT,
        borderwidth=0,
        highlightthickness=0,
        activestyle="none",
        yscrollcommand=scrollbar.set,
        **kwargs,
    )
    scrollbar.config(command=lb.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    return frame, lb


def _section_label(parent, text: str) -> tk.Label:
    return tk.Label(
        parent, text=text,
        bg=_BG, fg=_FG,
        font=("Segoe UI", 10, "bold"), anchor="w",
    )


def _divider(parent) -> tk.Frame:
    return tk.Frame(parent, bg="#cccccc", height=1)


def _make_info_text(parent, height: int = 12) -> tk.Text:
    """Create a styled, read-only Text widget for component metadata."""
    t = tk.Text(
        parent,
        height=height,
        bg=_BG2,
        fg=_FG,
        font=("Segoe UI", 9),
        borderwidth=0,
        highlightbackground="#cccccc",
        highlightthickness=1,
        wrap=tk.WORD,
        state=tk.DISABLED,
        cursor="arrow",
    )
    t.tag_configure("title", font=("Segoe UI", 10, "bold"), foreground="#000000")
    t.tag_configure("kv",    font=("Segoe UI", 9),          foreground="#333333")
    t.tag_configure("small", font=("Segoe UI", 8),          foreground="#666666")
    t.tag_configure("sep",   font=("Segoe UI", 8),          foreground="#999999")
    return t


def _populate_info_text(widget: tk.Text,
                        comp: Component, profile, eda_data) -> None:
    """Fill *widget* with component metadata."""
    from src.checklist.component_classifier import classify_component

    widget.config(state=tk.NORMAL)
    widget.delete("1.0", tk.END)

    widget.insert(tk.END, comp.comp_name + "\n", "title")
    widget.insert(tk.END, f"Part:  {comp.part_name or '—'}\n", "kv")
    widget.insert(tk.END, f"Type:  {classify_component(comp).value}\n", "kv")

    for key in ("TYPE", "DEVICE_TYPE", "VALUE"):
        val = comp.properties.get(key)
        if val:
            widget.insert(tk.END, f"{key}:  {val}\n", "kv")

    units  = profile.units if profile else "INCH"
    unit_s = '"' if units == "INCH" else "mm"
    widget.insert(tk.END,
                  f"Pos:   ({comp.x:.4f}{unit_s}, {comp.y:.4f}{unit_s})\n", "kv")
    widget.insert(tk.END, f"Rot:   {comp.rotation}\u00b0\n", "kv")

    net_names: list[str] = []
    if eda_data and comp.toeprints:
        for tp in comp.toeprints:
            if 0 <= tp.net_num < len(eda_data.nets):
                name = eda_data.nets[tp.net_num].name
                if name and name not in net_names:
                    net_names.append(name)

    if net_names:
        widget.insert(tk.END, "\u2500" * 22 + "\n", "sep")
        widget.insert(tk.END, f"Nets ({len(net_names)}):\n", "kv")
        display = ", ".join(net_names[:6])
        if len(net_names) > 6:
            display += f"  +{len(net_names) - 6}"
        widget.insert(tk.END, display + "\n", "small")

    if comp.bom_data:
        bom = comp.bom_data
        widget.insert(tk.END, "\u2500" * 22 + "\n", "sep")
        if bom.cpn:
            widget.insert(tk.END, f"CPN:  {bom.cpn}\n", "kv")
        if bom.description:
            desc = bom.description
            if len(desc) > 26:
                desc = desc[:24] + "\u2026"
            widget.insert(tk.END, f"Desc: {desc}\n", "small")
        for vendor in bom.vendors[:1]:
            for mpn_entry in vendor.get("mpns", [])[:1]:
                mpn = mpn_entry["mpn"]
                if len(mpn) > 22:
                    mpn = mpn[:20] + "\u2026"
                widget.insert(tk.END, f"MPN:  {mpn}\n", "small")

    widget.config(state=tk.DISABLED)


# ===========================================================================
# Standard PCB viewer
# ===========================================================================

class PcbViewer:
    """Interactive PCB viewer with a Tkinter Listbox for layer toggling."""

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
        self._visible_set:   set[str]            = set()
        self._display_items: list[str]           = []

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def show(self, initial_visible: list[str] = None,
             figsize: tuple[float, float] = (14, 9)):
        """Launch the interactive viewer."""
        if initial_visible is None:
            initial_visible = []

        # Build the ordered display-item list
        all_layers = sorted(
            self.layers_data.keys(),
            key=lambda n: self.layers_data[n][1].row,
        )
        display_layers = [
            name for name in all_layers
            if self.layers_data[name][1].type not in ("DIELECTRIC", "DRILL")
            and "comp_+" not in name
        ]
        self._display_items = list(display_layers)
        labels: list[str] = []
        for name in display_layers:
            ml = self.layers_data[name][1]
            labels.append(f"{name[:22]} ({ml.type[:4]})")

        if self.components_top:
            self._display_items.append(COMP_TOP_KEY)
            labels.append(f"Components Top ({len(self.components_top)})")
        if self.components_bot:
            self._display_items.append(COMP_BOT_KEY)
            labels.append(f"Components Bot ({len(self.components_bot)})")
        if self.components_top or self.components_bot:
            self._display_items.append(COMP_OUTLINE_KEY)
            labels.append("Comp. Outlines")

        self._visible_set = {
            item for item in initial_visible if item in self._display_items
        }

        # ---- Tkinter window -----------------------------------------------
        root = tk.Tk()
        root.title("ODB++ PCB Viewer")
        root.configure(bg=_BG)
        try:
            root.state("zoomed")          # maximise on Windows
        except tk.TclError:
            pass

        # ---- Left panel ---------------------------------------------------
        left = tk.Frame(root, bg=_BG, width=240)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(6, 3), pady=6)
        left.pack_propagate(False)

        _section_label(left, "Layer Selection").pack(anchor="w", pady=(4, 4))

        lb_frame, self._layer_lb = _make_listbox(left, height=14)
        lb_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        for lbl in labels:
            self._layer_lb.insert(tk.END, lbl)
        for i, item in enumerate(self._display_items):
            if item in self._visible_set:
                self._layer_lb.selection_set(i)
        self._layer_lb.bind("<<ListboxSelect>>", self._on_layer_select)

        _divider(left).pack(fill=tk.X, pady=(0, 4))
        _section_label(left, "Component Info").pack(anchor="w", pady=(0, 4))

        info_frame = tk.Frame(left, bg=_BG)
        info_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 6))
        self._info_text = _make_info_text(info_frame, height=4)
        self._info_text.pack(fill=tk.BOTH, expand=True)
        self._info_text.config(state=tk.NORMAL)
        self._info_text.insert(
            tk.END, "Click on a component\npin to view info", "sep")
        self._info_text.config(state=tk.DISABLED)

        # ---- Right panel (matplotlib canvas) ------------------------------
        right = tk.Frame(root, bg="white")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                   padx=(3, 6), pady=6)

        self.fig = Figure(figsize=figsize, facecolor="white")
        self.ax  = self.fig.add_axes([0.07, 0.07, 0.90, 0.88])
        _style_axes(self.ax)

        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        toolbar = NavigationToolbar2Tk(self.canvas, right)
        toolbar.update()
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self._redraw()
        self.canvas.mpl_connect("button_press_event", self._on_click)

        root.mainloop()

    # ------------------------------------------------------------------
    # Layer selection handler
    # ------------------------------------------------------------------

    def _on_layer_select(self, _event):
        selected = self._layer_lb.curselection()
        self._visible_set = {self._display_items[i] for i in selected}
        self._redraw()

    # ------------------------------------------------------------------
    # Redraw
    # ------------------------------------------------------------------

    def _redraw(self):
        self.ax.clear()
        _style_axes(self.ax)

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
        eda_u = self.eda_data.units if self.eda_data else None
        board_u = self.profile.units if self.profile else None
        if COMP_TOP_KEY in self._visible_set and self.components_top:
            draw_components(self.ax, self.components_top, packages,
                            color="#00B7FF", alpha=0.99,
                            show_pads=True, show_pkg_outlines=False,
                            eda_units=eda_u, board_units=board_u)
        if COMP_BOT_KEY in self._visible_set and self.components_bot:
            draw_components(self.ax, self.components_bot, packages,
                            color="#FF3150", alpha=0.99,
                            show_pads=True, show_pkg_outlines=False,
                            eda_units=eda_u, board_units=board_u)
        if COMP_OUTLINE_KEY in self._visible_set:
            self._draw_outlines(packages)

        self.ax.set_xlabel("X", color="#000000")
        self.ax.set_ylabel("Y", color="#000000")

        # Build dynamic title from selected layers
        visible_names = [name for name in self._visible_set
                         if not name.startswith("__")]
        if visible_names:
            title = "Layers: " + ", ".join(sorted(visible_names))
        else:
            title = "ODB++ PCB Viewer"
        self.ax.set_title(title, color="#000000")
        self.ax.grid(False)
        self.ax.set_aspect("equal")
        self.ax.format_coord = self._format_coord

        self.canvas.draw()

    def _draw_outlines(self, packages):
        drew_top = COMP_TOP_KEY in self._visible_set
        drew_bot = COMP_BOT_KEY in self._visible_set
        eda_u = self.eda_data.units if self.eda_data else None
        board_u = self.profile.units if self.profile else None
        if drew_top and self.components_top:
            draw_components(self.ax, self.components_top, packages,
                            color="#FFFF00", alpha=0.95,
                            show_pads=False, show_pkg_outlines=True,
                            eda_units=eda_u, board_units=board_u)
        if drew_bot and self.components_bot:
            draw_components(self.ax, self.components_bot, packages,
                            color="#FFFF00", alpha=0.95,
                            show_pads=False, show_pkg_outlines=True,
                            eda_units=eda_u, board_units=board_u)
        if not drew_top and not drew_bot:
            all_comps = self.components_top + self.components_bot
            if all_comps:
                draw_components(self.ax, all_comps, packages,
                                color="#FFFF00", alpha=0.95,
                                show_pads=False, show_pkg_outlines=True,
                                eda_units=eda_u, board_units=board_u)

    # ------------------------------------------------------------------
    # Click handler
    # ------------------------------------------------------------------

    def _on_click(self, event):
        if event.inaxes != self.ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        comp = self._find_nearest_component(event.xdata, event.ydata)
        if comp is not None and comp is not self._selected_comp:
            self._selected_comp = comp
            _populate_info_text(self._info_text, comp,
                                self.profile, self.eda_data)

    def _find_nearest_component(self, x: float, y: float) -> Optional[Component]:
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
    # Coordinate formatter
    # ------------------------------------------------------------------

    def _format_coord(self, x: float, y: float) -> str:
        units = self.profile.units if self.profile else "INCH"
        if units == "INCH":
            return f'x={x:.6f}" y={y:.6f}"'
        return f"x={x:.4f}mm y={y:.4f}mm"


# ===========================================================================
# Component viewer
# ===========================================================================

class ComponentViewer:
    """Interactive component-focused viewer with Tkinter Listbox for components.

    Left panel (top → bottom):
      - Layer Selection   : Tkinter Radiobuttons (Top / Bottom / Both)
      - Component Selection : Tkinter Listbox (multi-select, scrollable)
      - Display Options   : Tkinter Checkbuttons
      - Update Visualization button
      - Component Info    : Tkinter Text widget

    Right panel: matplotlib canvas (full black background).
    """

    def __init__(self,
                 profile: Profile,
                 components_top: list[Component] = None,
                 components_bot: list[Component] = None,
                 eda_data: EdaData = None):
        self.profile         = profile
        self.components_top  = components_top or []
        self.components_bot  = components_bot or []
        self.eda_data        = eda_data
        self._selected_comp: Optional[Component] = None
        self._current_layer  = "Both"
        self._drawn_comps:   list[Component] = []
        self._comp_names:    list[str]       = []

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def show(self, figsize: tuple[float, float] = (14, 9)):
        """Launch the component viewer."""
        root = tk.Tk()
        root.title("ODB++ Component Viewer")
        root.configure(bg=_BG)
        try:
            root.state("zoomed")
        except tk.TclError:
            pass

        # ---- Left panel ---------------------------------------------------
        left = tk.Frame(root, bg=_BG, width=240)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(6, 3), pady=6)
        left.pack_propagate(False)

        # Layer selection
        _section_label(left, "Layer Selection").pack(anchor="w", pady=(4, 4))
        radio_frame = tk.Frame(left, bg=_BG)
        radio_frame.pack(fill=tk.X, pady=(0, 6))
        self._layer_var = tk.StringVar(value="Both")
        for label in ("Top", "Bottom", "Both"):
            tk.Radiobutton(
                radio_frame, text=label,
                variable=self._layer_var, value=label,
                bg=_BG, fg=_FG,
                selectcolor="#d0d8e8",
                activebackground=_BG, activeforeground=_FG,
                font=_FONT,
                command=self._on_layer_change,
            ).pack(side=tk.LEFT, padx=(0, 6))

        # Component selection
        _divider(left).pack(fill=tk.X, pady=(0, 4))
        _section_label(left, "Component Selection").pack(anchor="w", pady=(0, 4))

        lb_frame, self._comp_lb = _make_listbox(left, height=12)
        lb_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        # Selection control buttons
        sel_btn_frame = tk.Frame(left, bg=_BG)
        sel_btn_frame.pack(fill=tk.X, pady=(0, 6))
        for btn_text, btn_cmd in [
            ("Select All",       self._select_all),
            ("Deselect All",     self._deselect_all),
            ("Invert Selection", self._invert_selection),
        ]:
            tk.Button(
                sel_btn_frame, text=btn_text,
                bg="#e0e0e0", fg="#1a1a1a",
                activebackground="#c8c8c8", activeforeground="#1a1a1a",
                font=("Segoe UI", 9),
                relief=tk.FLAT, cursor="hand2",
                command=btn_cmd,
            ).pack(fill=tk.X, pady=1, padx=2)

        # Display options
        _divider(left).pack(fill=tk.X, pady=(0, 4))
        _section_label(left, "Display Options").pack(anchor="w", pady=(0, 4))
        opts_frame = tk.Frame(left, bg=_BG)
        opts_frame.pack(fill=tk.X, pady=(0, 6))
        self._show_pins_var    = tk.BooleanVar(value=True)
        self._show_outline_var = tk.BooleanVar(value=False)
        for text, var in [("Show Pins", self._show_pins_var),
                          ("Show Component Outline", self._show_outline_var)]:
            tk.Checkbutton(
                opts_frame, text=text, variable=var,
                bg=_BG, fg=_FG,
                selectcolor="#d0d8e8",
                activebackground=_BG, activeforeground=_FG,
                font=("Segoe UI", 9),
            ).pack(anchor="w")

        # Update button
        tk.Button(
            left, text="Update Visualization",
            bg="#1a73e8", fg="#ffffff",
            activebackground="#1557b0", activeforeground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT, cursor="hand2",
            command=self._on_update_click,
        ).pack(fill=tk.X, pady=(0, 8), padx=2)

        # Component info (~40% of panel height)
        _divider(left).pack(fill=tk.X, pady=(0, 4))
        _section_label(left, "Component Info").pack(anchor="w", pady=(0, 4))
        info_frame = tk.Frame(left, bg=_BG)
        info_frame.pack(fill=tk.BOTH, expand=False, padx=2, pady=(0, 4))
        self._info_text = _make_info_text(info_frame, height=10)
        self._info_text.pack(fill=tk.BOTH, expand=True)
        self._info_text.config(state=tk.NORMAL)
        self._info_text.insert(
            tk.END, "Click on a component\npin to view info", "sep")
        self._info_text.config(state=tk.DISABLED)

        # ---- Right panel (matplotlib canvas) ------------------------------
        right = tk.Frame(root, bg="white")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                   padx=(3, 6), pady=6)

        self.fig = Figure(figsize=figsize, facecolor="white")
        self.ax  = self.fig.add_axes([0.07, 0.07, 0.90, 0.88])
        _style_axes(self.ax)

        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        toolbar = NavigationToolbar2Tk(self.canvas, right)
        toolbar.update()
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self._draw_board_only()
        self.canvas.mpl_connect("button_press_event", self._on_click)

        # Populate component list for the default "Both" layer
        self._rebuild_component_list()

        root.mainloop()

    # ------------------------------------------------------------------
    # Layer radio handler
    # ------------------------------------------------------------------

    def _on_layer_change(self):
        self._current_layer = self._layer_var.get()
        self._rebuild_component_list()

    def _get_layer_components(self) -> list[Component]:
        if self._current_layer == "Top":
            return list(self.components_top)
        if self._current_layer == "Bottom":
            return list(self.components_bot)
        return list(self.components_top) + list(self.components_bot)

    def _rebuild_component_list(self):
        self._comp_lb.delete(0, tk.END)
        comps = sorted(self._get_layer_components(), key=lambda c: c.comp_name)
        self._comp_names = [c.comp_name for c in comps]
        for name in self._comp_names:
            self._comp_lb.insert(tk.END, name)

    def _select_all(self):
        self._comp_lb.selection_set(0, tk.END)

    def _deselect_all(self):
        self._comp_lb.selection_clear(0, tk.END)

    def _invert_selection(self):
        for i in range(self._comp_lb.size()):
            if self._comp_lb.selection_includes(i):
                self._comp_lb.selection_clear(i)
            else:
                self._comp_lb.selection_set(i)

    # ------------------------------------------------------------------
    # Update button
    # ------------------------------------------------------------------

    def _on_update_click(self):
        selected = self._comp_lb.curselection()
        selected_names = {self._comp_names[i] for i in selected}
        show_pins    = self._show_pins_var.get()
        show_outline = self._show_outline_var.get()
        comps = [c for c in self._get_layer_components()
                 if c.comp_name in selected_names]
        self._drawn_comps = comps
        self._redraw(comps, show_pins, show_outline)

    # ------------------------------------------------------------------
    # Draw helpers
    # ------------------------------------------------------------------

    def _draw_board_only(self):
        self.ax.clear()
        _style_axes(self.ax)
        if self.profile and self.profile.surface:
            _draw_profile(self.ax, self.profile)
        self._apply_axis_labels()
        self.canvas.draw()

    def _redraw(self, comps: list[Component],
                show_pins: bool, show_outline: bool):
        self.ax.clear()
        _style_axes(self.ax)

        if self.profile and self.profile.surface:
            _draw_profile(self.ax, self.profile)

        packages = self.eda_data.packages if self.eda_data else None
        eda_u = self.eda_data.units if self.eda_data else None
        board_u = self.profile.units if self.profile else None
        if comps and (show_pins or show_outline):
            top_set   = {c.comp_name for c in self.components_top}
            top_comps = [c for c in comps if c.comp_name in top_set]
            bot_comps = [c for c in comps if c.comp_name not in top_set]
            if top_comps:
                draw_components(self.ax, top_comps, packages,
                                color="#00B7FF", alpha=0.99,
                                show_pads=show_pins,
                                show_pkg_outlines=show_outline,
                                eda_units=eda_u, board_units=board_u)
            if bot_comps:
                draw_components(self.ax, bot_comps, packages,
                                color="#FF3150", alpha=0.99,
                                show_pads=show_pins,
                                show_pkg_outlines=show_outline,
                                eda_units=eda_u, board_units=board_u)

        self._apply_axis_labels()
        self.canvas.draw()

    def _apply_axis_labels(self):
        self.ax.set_xlabel("X", color="#000000")
        self.ax.set_ylabel("Y", color="#000000")

        # Dynamic title based on selected layer
        layer = self._layer_var.get() if hasattr(self, '_layer_var') else "Both"
        self.ax.set_title(f"Components: {layer}", color="#000000")
        self.ax.grid(False)
        self.ax.set_aspect("equal")
        self.ax.format_coord = self._format_coord

    # ------------------------------------------------------------------
    # Click handler
    # ------------------------------------------------------------------

    def _on_click(self, event):
        if event.inaxes != self.ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        comp = self._find_nearest_component(event.xdata, event.ydata)
        if comp is not None and comp is not self._selected_comp:
            self._selected_comp = comp
            _populate_info_text(self._info_text, comp,
                                self.profile, self.eda_data)

    def _find_nearest_component(self, x: float, y: float) -> Optional[Component]:
        xlim         = self.ax.get_xlim()
        threshold_sq = ((xlim[1] - xlim[0]) * 0.02) ** 2
        best_comp    = None
        best_dist_sq = threshold_sq
        for comp in self._drawn_comps:
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
    # Coordinate formatter
    # ------------------------------------------------------------------

    def _format_coord(self, x: float, y: float) -> str:
        units = self.profile.units if self.profile else "INCH"
        if units == "INCH":
            return f'x={x:.6f}" y={y:.6f}"'
        return f"x={x:.4f}mm y={y:.4f}mm"
