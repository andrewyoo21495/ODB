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

All coordinate data (components, EDA packages, profile, layer features) is
normalised to MM before being passed to the viewer.
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
from src.visualizer.symbol_renderer import symbol_to_patch, user_symbol_to_patches
from src.visualizer.layer_renderer import LAYER_COLORS, render_layer, is_bottom_layer
from src.visualizer.component_overlay import draw_components
from src.visualizer.renderer import _draw_profile
from src.visualizer import copper_utils
from src.visualizer import copper_vector

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
    """Return (frame, Listbox) with dark styling and a scrollbar.

    Pass ``selectmode=tk.SINGLE`` (or any tk constant) to override the
    default ``tk.MULTIPLE`` behaviour.
    """
    selectmode = kwargs.pop("selectmode", tk.MULTIPLE)
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
        selectmode=selectmode,
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
                        comp: Component, profile, eda_data,
                        pin_name: str = "") -> None:
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

    widget.insert(tk.END,
                  f"Pos:   ({comp.x:.4f}mm, {comp.y:.4f}mm)\n", "kv")
    widget.insert(tk.END, f"Rot:   {comp.rotation}\u00b0\n", "kv")
    if pin_name:
        widget.insert(tk.END, f"Pin:   {pin_name}\n", "kv")

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

        self._selected_comp:     Optional[Component] = None
        self._selected_pin_name: str               = ""
        self._visible_set:       set[str]          = set()
        self._display_items:     list[str]         = []

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
                         font=self.font,
                         flip_x=is_bottom_layer(layer_name))

        packages = self.eda_data.packages if self.eda_data else None
        if COMP_TOP_KEY in self._visible_set and self.components_top:
            draw_components(self.ax, self.components_top, packages,
                            color="#2BFFF4", alpha=0.99,
                            show_pads=True, show_pkg_outlines=False,
                            user_symbols=self.user_symbols,
                            comp_side="T")
        if COMP_BOT_KEY in self._visible_set and self.components_bot:
            draw_components(self.ax, self.components_bot, packages,
                            color="#FC5BA1", alpha=0.99,
                            show_pads=True, show_pkg_outlines=False,
                            user_symbols=self.user_symbols,
                            comp_side="B")
        if COMP_OUTLINE_KEY in self._visible_set:
            self._draw_outlines(packages)

        # Selection highlight – draw selected component in red on top
        if self._selected_comp is not None:
            visible_comps: list[Component] = []
            if COMP_TOP_KEY in self._visible_set:
                visible_comps.extend(self.components_top)
            if COMP_BOT_KEY in self._visible_set:
                visible_comps.extend(self.components_bot)
            if self._selected_comp in visible_comps:
                is_bot = self._selected_comp in self.components_bot
                draw_components(self.ax, [self._selected_comp], packages,
                                color="#FF0000", alpha=1.0,
                                show_pads=True, show_pkg_outlines=True,
                                user_symbols=self.user_symbols,
                                comp_side="B" if is_bot else "T")

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
        if drew_top and self.components_top:
            draw_components(self.ax, self.components_top, packages,
                            color="#FFFF00", alpha=0.95,
                            show_pads=False, show_pkg_outlines=True,
                            user_symbols=self.user_symbols,
                            comp_side="T")
        if drew_bot and self.components_bot:
            draw_components(self.ax, self.components_bot, packages,
                            color="#FFFF00", alpha=0.95,
                            show_pads=False, show_pkg_outlines=True,
                            user_symbols=self.user_symbols,
                            comp_side="B")
        if not drew_top and not drew_bot:
            all_comps = self.components_top + self.components_bot
            if all_comps:
                draw_components(self.ax, all_comps, packages,
                                color="#FFFF00", alpha=0.95,
                                show_pads=False, show_pkg_outlines=True)

    # ------------------------------------------------------------------
    # Click handler
    # ------------------------------------------------------------------

    def _on_click(self, event):
        if event.inaxes != self.ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        comp, pin_name = self._find_nearest_component(event.xdata, event.ydata)
        if comp is not None:
            if comp is not self._selected_comp or pin_name != self._selected_pin_name:
                self._selected_comp     = comp
                self._selected_pin_name = pin_name
                _populate_info_text(self._info_text, comp,
                                    self.profile, self.eda_data, pin_name)
                self._redraw()

    def _find_nearest_component(self, x: float,
                                 y: float) -> tuple[Optional[Component], str]:
        xlim         = self.ax.get_xlim()
        threshold_sq = ((xlim[1] - xlim[0]) * 0.02) ** 2
        best_comp    = None
        best_dist_sq = threshold_sq
        best_pin     = ""

        candidates: list[Component] = []
        if COMP_TOP_KEY in self._visible_set:
            candidates.extend(self.components_top)
        if COMP_BOT_KEY in self._visible_set:
            candidates.extend(self.components_bot)

        for comp in candidates:
            # Centroid
            d = (comp.x - x) ** 2 + (comp.y - y) ** 2
            if d < best_dist_sq:
                best_dist_sq = d
                best_comp    = comp
                best_pin     = ""
            # Toeprints (override centroid if closer)
            for tp in comp.toeprints:
                d = (tp.x - x) ** 2 + (tp.y - y) ** 2
                if d < best_dist_sq:
                    best_dist_sq = d
                    best_comp    = comp
                    best_pin     = tp.name

        return best_comp, best_pin

    # ------------------------------------------------------------------
    # Coordinate formatter
    # ------------------------------------------------------------------

    def _format_coord(self, x: float, y: float) -> str:
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
                 eda_data: EdaData = None,
                 layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]] = None,
                 user_symbols: dict[str, UserSymbol] = None):
        self.profile         = profile
        self.components_top  = components_top or []
        self.components_bot  = components_bot or []
        self.eda_data        = eda_data
        self.user_symbols    = user_symbols or {}
        layers_data          = layers_data or {}

        # Resolve VIA features — prefer .pad_usage attribute, fall back to
        # EDA subnet FID resolution when the attribute is not present.
        self._via_features: list = []
        if layers_data:
            from src.visualizer.fid_lookup import (
                collect_via_pads_by_attribute,
                _find_top_bottom_signal_layers,
            )
            self._via_features = collect_via_pads_by_attribute(layers_data)
            if not self._via_features and eda_data and eda_data.layer_names:
                from src.visualizer.fid_lookup import resolve_via_features
                self._via_features = resolve_via_features(eda_data, layers_data)

        # Identify top/bottom signal layer names for filtering vias by layer
        self._via_layer_top: set[str] = set()
        self._via_layer_bot: set[str] = set()
        if layers_data:
            top_sig, bot_sig = _find_top_bottom_signal_layers(layers_data)
            if top_sig:
                self._via_layer_top.add(top_sig)
            if bot_sig:
                self._via_layer_bot.add(bot_sig)

        self._selected_comp:     Optional[Component] = None
        self._selected_pin_name: str               = ""
        self._current_layer      = "Both"
        self._drawn_comps:       list[Component]   = []
        self._comp_names:        list[str]         = []
        self._current_comps:     list[Component]   = []
        self._current_show_pins: bool              = True
        self._current_show_outline: bool           = False
        self._show_vias: bool                      = False

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

        lb_frame, self._comp_lb = _make_listbox(left, height=10)
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
        self._show_via_var     = tk.BooleanVar(value=False)
        for text, var in [("Show Pins", self._show_pins_var),
                          ("Show Component Outline", self._show_outline_var),
                          ("Show Via", self._show_via_var)]:
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
        info_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 4))
        self._info_text = _make_info_text(info_frame, height=12)
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
        self._drawn_comps       = comps
        self._current_comps     = comps
        self._current_show_pins = show_pins
        self._current_show_outline = show_outline
        self._show_vias = self._show_via_var.get()
        self._redraw(comps, show_pins, show_outline)

    # ------------------------------------------------------------------
    # Draw helpers
    # ------------------------------------------------------------------

    def _draw_board_only(self):
        self.ax.clear()
        _style_axes(self.ax)
        if self.profile and self.profile.surface:
            _draw_profile(self.ax, self.profile)
        if self._show_vias:
            self._draw_vias()
        self._apply_axis_labels()
        self.canvas.draw()

    def _redraw(self, comps: list[Component],
                show_pins: bool, show_outline: bool):
        self.ax.clear()
        _style_axes(self.ax)

        if self.profile and self.profile.surface:
            _draw_profile(self.ax, self.profile)

        packages = self.eda_data.packages if self.eda_data else None
        if comps and (show_pins or show_outline):
            top_set   = {c.comp_name for c in self.components_top}
            top_comps = [c for c in comps if c.comp_name in top_set]
            bot_comps = [c for c in comps if c.comp_name not in top_set]
            if show_pins:
                if top_comps:
                    draw_components(self.ax, top_comps, packages,
                                    color="#2BFFF4", alpha=0.99,
                                    show_pads=True, show_pkg_outlines=False,
                                    user_symbols=self.user_symbols,
                                    comp_side="T")
                if bot_comps:
                    draw_components(self.ax, bot_comps, packages,
                                    color="#FC5BA1", alpha=0.99,
                                    show_pads=True, show_pkg_outlines=False,
                                    user_symbols=self.user_symbols,
                                    comp_side="B")
            if show_outline:
                if top_comps:
                    draw_components(self.ax, top_comps, packages,
                                    color="#FFFF00", alpha=0.99,
                                    show_pads=False, show_pkg_outlines=True,
                                    user_symbols=self.user_symbols,
                                    comp_side="T")
                if bot_comps:
                    draw_components(self.ax, bot_comps, packages,
                                    color="#FFFF00", alpha=0.99,
                                    show_pads=False, show_pkg_outlines=True,
                                    user_symbols=self.user_symbols,
                                    comp_side="B")

        # Selection highlight – draw selected component in red on top
        if self._selected_comp is not None and self._selected_comp in (comps or []):
            is_bot = self._selected_comp in self.components_bot
            draw_components(self.ax, [self._selected_comp], packages,
                            color="#FF0000", alpha=1.0,
                            show_pads=True, show_pkg_outlines=True,
                            user_symbols=self.user_symbols,
                            comp_side="B" if is_bot else "T")

        # Draw vias on top of all component/selection graphics
        if self._show_vias:
            self._draw_vias()

        self._apply_axis_labels()
        self.canvas.draw()

    def _apply_axis_labels(self):
        self.ax.set_xlabel("X", color="#000000")
        self.ax.set_ylabel("Y", color="#000000")

        # Dynamic title based on selected layer
        layer = self._layer_var.get() if hasattr(self, '_layer_var') else "Both"
        via_suffix = " + VIA" if self._show_vias else ""
        self.ax.set_title(f"Components: {layer}{via_suffix}", color="#000000")
        self.ax.grid(False)
        self.ax.set_aspect("equal")
        self.ax.format_coord = self._format_coord

    # ------------------------------------------------------------------
    # VIA drawing
    # ------------------------------------------------------------------

    _VIA_COLOR = "#505050"   # dark grey

    def _draw_vias(self):
        """Render VIA pad features in dark grey, filtered by current layer."""
        if not self._via_features:
            return

        layer = self._current_layer
        for rpf in self._via_features:
            # Filter by layer when viewing a single side
            if layer == "Top" and rpf.layer_name not in self._via_layer_top:
                continue
            if layer == "Bottom" and rpf.layer_name not in self._via_layer_bot:
                continue

            pad = rpf.pad
            sym_name = rpf.symbol.name
            units = rpf.units
            unit_override = rpf.symbol.unit_override

            # Try user-defined symbol first, then standard
            if sym_name in self.user_symbols:
                patches = user_symbol_to_patches(
                    self.user_symbols[sym_name],
                    pad.x, pad.y,
                    rotation=pad.rotation,
                    mirror=pad.mirror,
                    color=self._VIA_COLOR,
                    alpha=0.85,
                )
                for p in patches:
                    self.ax.add_patch(p)
            else:
                p = symbol_to_patch(
                    sym_name, pad.x, pad.y,
                    rotation=pad.rotation,
                    mirror=pad.mirror,
                    units=units,
                    unit_override=unit_override,
                    color=self._VIA_COLOR,
                    alpha=0.85,
                )
                if p is not None:
                    self.ax.add_patch(p)

    # ------------------------------------------------------------------
    # Click handler
    # ------------------------------------------------------------------

    def _on_click(self, event):
        if event.inaxes != self.ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        comp, pin_name = self._find_nearest_component(event.xdata, event.ydata)
        if comp is not None:
            if comp is not self._selected_comp or pin_name != self._selected_pin_name:
                self._selected_comp     = comp
                self._selected_pin_name = pin_name
                _populate_info_text(self._info_text, comp,
                                    self.profile, self.eda_data, pin_name)
                self._redraw(self._current_comps,
                             self._current_show_pins,
                             self._current_show_outline)

    def _find_nearest_component(self, x: float,
                                 y: float) -> tuple[Optional[Component], str]:
        xlim         = self.ax.get_xlim()
        threshold_sq = ((xlim[1] - xlim[0]) * 0.02) ** 2
        best_comp    = None
        best_dist_sq = threshold_sq
        best_pin     = ""
        for comp in self._drawn_comps:
            # Centroid
            d = (comp.x - x) ** 2 + (comp.y - y) ** 2
            if d < best_dist_sq:
                best_dist_sq = d
                best_comp    = comp
                best_pin     = ""
            # Toeprints (override centroid if closer)
            for tp in comp.toeprints:
                d = (tp.x - x) ** 2 + (tp.y - y) ** 2
                if d < best_dist_sq:
                    best_dist_sq = d
                    best_comp    = comp
                    best_pin     = tp.name
        return best_comp, best_pin

    # ------------------------------------------------------------------
    # Coordinate formatter  (ComponentViewer)
    # ------------------------------------------------------------------

    def _format_coord(self, x: float, y: float) -> str:
        return f"x={x:.4f}mm y={y:.4f}mm"



# ===========================================================================
# Copper Ratio viewer
# ===========================================================================

class CopperRatioViewer:
    """Signal-layer copper fill ratio calculator.

    Left panel (top → bottom):
      - Layer Selection  : Listbox (single-select, SIGNAL layers only)
      - Calculate Copper Ratio button
      - Result label
      - Layer Thickness  : read-only table from copper_data cache

    Right panel: matplotlib canvas that renders the selected signal layer
    together with the PCB outline.  Clicking "Calculate Copper Ratio"
    performs a pixel-based fill analysis and displays the result.
    """

    def __init__(self,
                 profile: Profile,
                 layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
                 copper_data: dict[str, float] = None,
                 user_symbols: dict[str, UserSymbol] = None,
                 font: StrokeFont = None):
        self.profile      = profile
        self.layers_data  = layers_data
        self.copper_data  = copper_data or {}
        self.user_symbols = user_symbols or {}
        self.font         = font

        # Build ordered list of SIGNAL layers only
        self._signal_layers: list[str] = [
            name for name, (_, ml) in sorted(
                layers_data.items(), key=lambda x: x[1][1].row
            )
            if ml.type == "SIGNAL"
        ]

        self._selected_layer: Optional[str] = None
        self._ratio_result:   Optional[float] = None
        self._subsection_ratios = None   # np.ndarray (n_rows, n_cols) or None
        self._n_rows: int = 5
        self._n_cols: int = 5
        self._colorbar = None            # matplotlib Colorbar or None
        self._subsection_mode = None     # tk.BooleanVar, set in show()
        self._vector_mode = None         # tk.BooleanVar, set in show()
        self._subsection_text = None     # tk.Text widget for grid results
        self._root: Optional[tk.Tk] = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def show(self, figsize: tuple[float, float] = (14, 9)):
        """Launch the copper ratio viewer."""
        root = tk.Tk()
        self._root = root
        root.title("ODB++ Copper Ratio Viewer")
        root.configure(bg=_BG)
        try:
            root.state("zoomed")
        except tk.TclError:
            pass

        # ---- Left panel ---------------------------------------------------
        left = tk.Frame(root, bg=_BG, width=240)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(6, 3), pady=6)
        left.pack_propagate(False)

        # Layer selection (SIGNAL layers, single-select)
        _section_label(left, "Layer Selection").pack(anchor="w", pady=(4, 4))

        lb_frame, self._layer_lb = _make_listbox(
            left, height=10, selectmode=tk.SINGLE,
        )
        lb_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 6))

        for name in self._signal_layers:
            self._layer_lb.insert(tk.END, name)
        self._layer_lb.bind("<<ListboxSelect>>", self._on_layer_select)

        _divider(left).pack(fill=tk.X, pady=(0, 6))

        # Calculate button
        tk.Button(
            left, text="Calculate Copper Ratio",
            bg="#1a73e8", fg="#ffffff",
            activebackground="#1557b0", activeforeground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT, cursor="hand2",
            command=self._on_calculate,
        ).pack(fill=tk.X, pady=(0, 4), padx=2)

        # Sub-section checkbox
        self._subsection_mode = tk.BooleanVar(value=False)
        tk.Checkbutton(
            left, text="Calculate by Sub-section",
            variable=self._subsection_mode,
            bg=_BG, fg="#333333",
            font=("Segoe UI", 9),
            activebackground=_BG,
            command=self._on_subsection_toggle,
        ).pack(anchor="w", padx=2, pady=(0, 2))

        # Vector method checkbox
        self._vector_mode = tk.BooleanVar(value=False)
        tk.Checkbutton(
            left, text="Use Vector Method",
            variable=self._vector_mode,
            bg=_BG, fg="#333333",
            font=("Segoe UI", 9),
            activebackground=_BG,
            command=self._on_method_toggle,
        ).pack(anchor="w", padx=2, pady=(0, 6))

        # Result label
        self._result_var = tk.StringVar(value="")
        tk.Label(
            left, textvariable=self._result_var,
            bg=_BG, fg="#1a73e8",
            font=("Segoe UI", 10, "bold"),
            anchor="w", wraplength=220,
        ).pack(fill=tk.X, padx=4, pady=(0, 4))

        # Sub-section grid result (shown when grid mode is active)
        _section_label(left, "Sub-section Results").pack(anchor="w", pady=(0, 2))
        self._subsection_text = tk.Text(
            left,
            height=9,
            bg=_BG2,
            fg="#333333",
            font=("Consolas", 8),
            borderwidth=0,
            highlightbackground="#cccccc",
            highlightthickness=1,
            wrap=tk.NONE,
            state=tk.DISABLED,
            cursor="arrow",
        )
        self._subsection_text.tag_configure(
            "sep", font=("Consolas", 8), foreground="#999999")
        self._subsection_text.tag_configure(
            "kv",  font=("Consolas", 8), foreground="#333333")
        self._subsection_text.tag_configure(
            "title", font=("Consolas", 8, "bold"), foreground="#000000")
        self._subsection_text.pack(fill=tk.X, padx=2, pady=(0, 6))

        _divider(left).pack(fill=tk.X, pady=(0, 6))

        # Layer Thickness table
        _section_label(left, "Layer Thickness").pack(anchor="w", pady=(0, 4))
        self._thickness_text = _make_info_text(left, height=10)
        self._thickness_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 6))
        self._populate_thickness_table()

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
        root.mainloop()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _populate_thickness_table(self):
        self._thickness_text.config(state=tk.NORMAL)
        self._thickness_text.delete("1.0", tk.END)
        if not self.copper_data:
            self._thickness_text.insert(tk.END, "(no data available)", "small")
        else:
            self._thickness_text.insert(
                tk.END, f"{'Layer':<19} {'mm':>7}\n", "sep")
            self._thickness_text.insert(tk.END, "\u2500" * 26 + "\n", "sep")
            total = 0.0
            for layer_name, thickness in self.copper_data.items():
                total += thickness
                self._thickness_text.insert(
                    tk.END,
                    f"{layer_name[:18]:<19} {thickness:>7.4f}\n",
                    "kv",
                )
            self._thickness_text.insert(tk.END, "\u2500" * 26 + "\n", "sep")
            self._thickness_text.insert(
                tk.END, f"{'Total':<19} {total:>7.4f}\n", "title")
        self._thickness_text.config(state=tk.DISABLED)

    # ---------------------------------------------------------
    # ---------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_layer_select(self, _event):
        sel = self._layer_lb.curselection()
        self._selected_layer = self._signal_layers[sel[0]] if sel else None
        self._ratio_result = None
        self._subsection_ratios = None
        self._result_var.set("")
        self._clear_subsection_display()
        self._redraw()

    def _on_subsection_toggle(self):
        """Clear results when the sub-section checkbox is toggled."""
        self._ratio_result = None
        self._subsection_ratios = None
        self._result_var.set("")
        self._clear_subsection_display()
        self._redraw()

    def _on_method_toggle(self):
        """Clear results when the calculation method is toggled."""
        self._ratio_result = None
        self._subsection_ratios = None
        self._result_var.set("")
        self._clear_subsection_display()
        self._redraw()

    def _on_calculate(self):
        import numpy as np

        if self._selected_layer is None:
            self._result_var.set("Select a layer first.")
            return

        use_vector = self._vector_mode and self._vector_mode.get()
        method_label = " [vector]" if use_vector else " [raster]"
        self._result_var.set("Calculating\u2026" + method_label)
        if self._root:
            self._root.update_idletasks()

        if use_vector:
            # ---- Vector-based calculation --------------------------------
            if self._subsection_mode and self._subsection_mode.get():
                self._ratio_result = None
                ratios = copper_vector.calculate_subsection_ratios(
                    self._selected_layer, self.profile, self.layers_data,
                    self.user_symbols, self.font,
                    n_rows=self._n_rows, n_cols=self._n_cols,
                )
                if ratios is not None:
                    self._subsection_ratios = ratios
                    valid = ratios[~np.isnan(ratios)]
                    if len(valid):
                        avg = float(valid.mean())
                        lo  = float(valid.min())
                        hi  = float(valid.max())
                        self._result_var.set(
                            f"Avg: {avg*100:.2f}%  "
                            f"[{lo*100:.1f}% – {hi*100:.1f}%]"
                            + method_label
                        )
                    else:
                        self._result_var.set("No PCB area found.")
                    self._update_subsection_display()
                    self._redraw()
                else:
                    self._result_var.set("Calculation failed.")
            else:
                self._subsection_ratios = None
                self._clear_subsection_display()
                ratio = copper_vector.calculate_copper_ratio(
                    self._selected_layer, self.profile, self.layers_data,
                    self.user_symbols, self.font,
                )
                if ratio is not None:
                    self._ratio_result = ratio
                    self._result_var.set(
                        f"Ratio: {ratio:.4f}  ({ratio * 100:.2f}%)"
                        + method_label
                    )
                    self._redraw()
                else:
                    self._result_var.set("Calculation failed.")
        else:
            # ---- Raster-based calculation (existing) ---------------------
            raster = self._rasterize_layer()
            if raster is None:
                self._result_var.set("Calculation failed.")
                return

            if self._subsection_mode and self._subsection_mode.get():
                self._ratio_result = None
                ratios = self._calculate_subsection_ratios(raster_data=raster)
                if ratios is not None:
                    self._subsection_ratios = ratios
                    valid = ratios[~np.isnan(ratios)]
                    if len(valid):
                        avg = float(valid.mean())
                        lo  = float(valid.min())
                        hi  = float(valid.max())
                        self._result_var.set(
                            f"Avg: {avg*100:.2f}%  "
                            f"[{lo*100:.1f}% – {hi*100:.1f}%]"
                            + method_label
                        )
                    else:
                        self._result_var.set("No PCB area found.")
                    self._update_subsection_display()
                    self._redraw()
                else:
                    self._result_var.set("Calculation failed.")
            else:
                self._subsection_ratios = None
                self._clear_subsection_display()
                ratio = self._calculate_ratio(raster_data=raster)
                if ratio is not None:
                    self._ratio_result = ratio
                    self._result_var.set(
                        f"Ratio: {ratio:.4f}  ({ratio * 100:.2f}%)"
                        + method_label
                    )
                    self._redraw()
                else:
                    self._result_var.set("Calculation failed.")

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _redraw(self):
        # Remove previous colorbar before clearing axes
        if self._colorbar is not None:
            self._colorbar.remove()
            self._colorbar = None

        self.ax.clear()
        _style_axes(self.ax)

        if self.profile and self.profile.surface:
            _draw_profile(self.ax, self.profile)

        if self._selected_layer and self._selected_layer in self.layers_data:
            features, matrix_layer = self.layers_data[self._selected_layer]
            color = LAYER_COLORS.get(matrix_layer.type, "#00CC00")
            render_layer(self.ax, features, color=color,
                         layer_type=matrix_layer.type,
                         alpha=0.85, user_symbols=self.user_symbols,
                         font=self.font,
                         flip_x=is_bottom_layer(self._selected_layer))

        if self._subsection_ratios is not None:
            self._draw_subsection_overlay()

        if self._selected_layer:
            title = self._selected_layer
            if self._ratio_result is not None:
                title += f"  |  Copper Ratio: {self._ratio_result:.4f}"
            elif self._subsection_ratios is not None:
                title += (f"  |  Sub-section Ratios "
                          f"({self._n_rows}\u00d7{self._n_cols})")
        else:
            title = "Select a Signal Layer"

        self.ax.set_title(title, color="#000000")
        self.ax.set_xlabel("X", color="#000000")
        self.ax.set_ylabel("Y", color="#000000")
        self.ax.grid(False)
        self.ax.set_aspect("equal")
        self.ax.format_coord = lambda x, y: f"x={x:.4f}mm y={y:.4f}mm"
        self.canvas.draw()

    # ------------------------------------------------------------------
    # Ratio calculation
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Rasterization helper (shared by whole-board and grid calculations)
    # ------------------------------------------------------------------

    def _rasterize_layer(self) -> Optional[dict]:
        """Render the selected layer off-screen and return pixel data.

        Delegates to copper_utils.rasterize_layer.
        """
        if self._selected_layer is None:
            return None
        return copper_utils.rasterize_layer(
            self._selected_layer, self.profile, self.layers_data,
            self.user_symbols, self.font
        )

    # ------------------------------------------------------------------
    # Ratio calculation
    # ------------------------------------------------------------------

    def _calculate_ratio(self, raster_data: dict = None) -> Optional[float]:
        """Copper fill ratio for the entire selected layer (0 – 1).

        If *raster_data* is supplied, the expensive rasterization step
        is skipped and the pre-computed masks are reused directly.
        """
        if self._selected_layer is None:
            return None
        return copper_utils.calculate_copper_ratio(
            self._selected_layer, self.profile, self.layers_data,
            self.user_symbols, self.font, raster_data=raster_data,
        )

    def _calculate_subsection_ratios(self, raster_data: dict = None):
        """Copper fill ratio for each cell of an n_rows × n_cols grid.

        If *raster_data* is supplied, the expensive rasterization step
        is skipped and the pre-computed masks are reused directly.
        """
        if self._selected_layer is None:
            return None
        return copper_utils.calculate_subsection_ratios(
            self._selected_layer, self.profile, self.layers_data,
            self.user_symbols, self.font,
            n_rows=self._n_rows, n_cols=self._n_cols,
            raster_data=raster_data,
        )

    # ------------------------------------------------------------------
    # Sub-section overlay (drawn on the interactive canvas)
    # ------------------------------------------------------------------

    def _draw_subsection_overlay(self):
        """Draw a colour-coded grid heatmap on self.ax.

        Delegates to copper_utils.draw_subsection_overlay.
        """
        if self._subsection_ratios is None:
            return
        self._colorbar = copper_utils.draw_subsection_overlay(
            self.ax, self.fig, self._subsection_ratios, self.profile,
            n_rows=self._n_rows, n_cols=self._n_cols
        )

    # ------------------------------------------------------------------
    # Sub-section text-panel helpers
    # ------------------------------------------------------------------

    def _update_subsection_display(self):
        """Populate the sub-section Text widget with a formatted grid."""
        import numpy as np

        if self._subsection_text is None:
            return

        self._subsection_text.config(state=tk.NORMAL)
        self._subsection_text.delete("1.0", tk.END)

        ratios = self._subsection_ratios
        if ratios is None:
            self._subsection_text.insert(tk.END, "(no data)", "sep")
            self._subsection_text.config(state=tk.DISABLED)
            return

        # Column header
        hdr = "    " + " ".join(f" C{j+1:1d}  " for j in range(self._n_cols))
        self._subsection_text.insert(tk.END, hdr + "\n", "sep")
        self._subsection_text.insert(
            tk.END, "\u2500" * len(hdr) + "\n", "sep")

        for i in range(self._n_rows):
            row = f"R{i+1} "
            for j in range(self._n_cols):
                v = ratios[i, j]
                row += ("  -- " if np.isnan(v) else f"{v*100:5.1f}%") + " "
            self._subsection_text.insert(tk.END, row.rstrip() + "\n", "kv")

        valid = ratios[~np.isnan(ratios)]
        if len(valid):
            sep = "\u2500" * len(hdr)
            self._subsection_text.insert(tk.END, sep + "\n", "sep")
            self._subsection_text.insert(
                tk.END,
                f"Min {valid.min()*100:5.1f}%  Max {valid.max()*100:5.1f}%\n",
                "kv",
            )
            self._subsection_text.insert(
                tk.END,
                f"Avg {valid.mean()*100:5.1f}%\n",
                "title",
            )

        self._subsection_text.config(state=tk.DISABLED)

    def _clear_subsection_display(self):
        """Clear the sub-section Text widget."""
        if self._subsection_text is None:
            return
        self._subsection_text.config(state=tk.NORMAL)
        self._subsection_text.delete("1.0", tk.END)
        self._subsection_text.config(state=tk.DISABLED)


# ===========================================================================
# Copper Batch Calculator GUI
# ===========================================================================


class CopperCalculateViewer:
    """Batch copper ratio calculator with GUI file/path selectors."""

    def __init__(self, load_data_fn, cache_dir=None):
        """Initialize the viewer.

        Args:
            load_data_fn: Callable(odb_path: str) -> dict with keys:
                profile, layers_data, user_symbols, font, copper_data, matrix_layers_ordered
            cache_dir: Path to cache directory (for reference)
        """
        from pathlib import Path
        self._load_data_fn = load_data_fn
        self._cache_dir = cache_dir or Path("cache")
        self._root: Optional[tk.Tk] = None
        self._status_text: Optional[tk.Text] = None
        self._calc_btn: Optional[tk.Button] = None
        self._odb_var: Optional[tk.StringVar] = None
        self._excel_var: Optional[tk.StringVar] = None
        self._grid_var: Optional[tk.StringVar] = None

    def show(self):
        """Launch the GUI window."""
        import tkinter.filedialog as filedialog

        self._root = tk.Tk()
        self._root.title("Copper Ratio Batch Calculator")
        self._root.geometry("650x400")
        self._root.configure(bg=_BG)

        # Create StringVars after root window exists
        self._odb_var = tk.StringVar(value="")
        self._excel_var = tk.StringVar(value="")
        self._grid_var = tk.StringVar(value="5x5")
        self._vector_var = tk.BooleanVar(value=False)

        # ---- Main layout ----
        main_frame = tk.Frame(self._root, bg=_BG)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # ODB++ file row
        row1 = tk.Frame(main_frame, bg=_BG)
        row1.pack(fill=tk.X, pady=(0, 6))

        tk.Label(row1, text="ODB++ File:", bg=_BG, fg=_FG, font=_FONT).pack(
            side=tk.LEFT, padx=(0, 6))
        tk.Entry(row1, textvariable=self._odb_var, bg=_BG2, fg=_FG,
                 font=_FONT, width=40).pack(side=tk.LEFT, padx=(0, 6), fill=tk.X, expand=True)
        tk.Button(row1, text="Browse...", bg="#1a73e8", fg="#ffffff",
                  activebackground="#1557b0", relief=tk.FLAT,
                  command=self._browse_odb).pack(side=tk.LEFT)

        # Excel output row
        row2 = tk.Frame(main_frame, bg=_BG)
        row2.pack(fill=tk.X, pady=(0, 6))

        tk.Label(row2, text="Excel Output:", bg=_BG, fg=_FG, font=_FONT).pack(
            side=tk.LEFT, padx=(0, 6))
        tk.Entry(row2, textvariable=self._excel_var, bg=_BG2, fg=_FG,
                 font=_FONT, width=40).pack(side=tk.LEFT, padx=(0, 6), fill=tk.X, expand=True)
        tk.Button(row2, text="Save As...", bg="#1a73e8", fg="#ffffff",
                  activebackground="#1557b0", relief=tk.FLAT,
                  command=self._browse_excel).pack(side=tk.LEFT)

        # Sub-section grid row
        row_grid = tk.Frame(main_frame, bg=_BG)
        row_grid.pack(fill=tk.X, pady=(0, 6))

        tk.Label(row_grid, text="Sub-section Grid:", bg=_BG, fg=_FG, font=_FONT).pack(
            side=tk.LEFT, padx=(0, 6))
        tk.Entry(row_grid, textvariable=self._grid_var, bg=_BG2, fg=_FG,
                 font=_FONT, width=8).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(row_grid, text="(rows x cols, e.g. 4x5)", bg=_BG, fg="#888888",
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)

        # Vector method checkbox
        row_vec = tk.Frame(main_frame, bg=_BG)
        row_vec.pack(fill=tk.X, pady=(0, 6))
        tk.Checkbutton(
            row_vec, text="Use Vector Method (exact geometry, no rasterization)",
            variable=self._vector_var,
            bg=_BG, fg="#333333",
            font=("Segoe UI", 9),
            activebackground=_BG,
        ).pack(anchor="w")

        # Button row
        row3 = tk.Frame(main_frame, bg=_BG)
        row3.pack(fill=tk.X, pady=(0, 12))

        self._calc_btn = tk.Button(
            row3, text="Calculate", bg="#1a73e8", fg="#ffffff",
            activebackground="#1557b0", activeforeground="#ffffff",
            font=("Segoe UI", 11, "bold"), relief=tk.FLAT, cursor="hand2",
            command=self._on_calculate)
        self._calc_btn.pack(side=tk.LEFT, padx=6)

        # Status section
        _section_label(main_frame, "Status").pack(anchor="w", pady=(0, 4))

        status_frame = tk.Frame(main_frame, bg=_BG2, highlightbackground="#cccccc",
                                highlightthickness=1)
        status_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        scrollbar = tk.Scrollbar(status_frame, orient=tk.VERTICAL, bg=_BG,
                                 troughcolor="#e0e0e0", relief=tk.FLAT)
        self._status_text = tk.Text(
            status_frame, height=12, bg=_BG2, fg=_FG, font=("Consolas", 9),
            borderwidth=0, highlightthickness=0, yscrollcommand=scrollbar.set,
            state=tk.DISABLED, wrap=tk.WORD
        )
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._status_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self._status_text.yview)

        self._root.mainloop()

    def _browse_odb(self):
        """Open file dialog for ODB++ file."""
        import tkinter.filedialog as filedialog
        path = filedialog.askopenfilename(
            filetypes=[
                ("ODB++ Archives", "*.tgz *.tar.gz *.zip"),
                ("All files", "*.*")
            ]
        )
        if path:
            self._odb_var.set(path)

    def _browse_excel(self):
        """Open file dialog for Excel output."""
        import tkinter.filedialog as filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")]
        )
        if path:
            self._excel_var.set(path)

    def _on_calculate(self):
        """Start the calculation in a background thread."""
        import threading

        odb_path = self._odb_var.get().strip()
        excel_path = self._excel_var.get().strip()

        if not odb_path or not excel_path:
            self._log("Error: ODB++ path and Excel output path are required.")
            return

        # Parse grid specification
        grid_str = self._grid_var.get().strip()
        import re
        m = re.match(r"^(\d+)\s*[xX×]\s*(\d+)$", grid_str)
        if not m or int(m.group(1)) < 1 or int(m.group(2)) < 1:
            self._log(f"Error: Invalid grid format '{grid_str}'. Use NxM (e.g. 4x5).")
            return
        n_rows, n_cols = int(m.group(1)), int(m.group(2))

        use_vector = self._vector_var.get()

        self._calc_btn.config(state=tk.DISABLED)
        self._status_text.config(state=tk.NORMAL)
        self._status_text.delete("1.0", tk.END)
        self._status_text.config(state=tk.DISABLED)

        t = threading.Thread(target=self._run_calculation,
                             args=(odb_path, excel_path, n_rows, n_cols,
                                   use_vector),
                             daemon=True)
        t.start()

    def _run_calculation(self, odb_path: str, excel_path: str,
                         n_rows: int = 5, n_cols: int = 5,
                         use_vector: bool = False):
        """Run the full calculation loop (background thread)."""
        import numpy as np
        from pathlib import Path
        from src.copper_reporter import generate_copper_report

        method_label = "vector" if use_vector else "raster"

        try:
            self._log(f"Loading ODB++ data... (grid: {n_rows}×{n_cols}, method: {method_label})")
            data = self._load_data_fn(odb_path)

            profile = data.get("profile")
            layers_data = data.get("layers_data", {})
            user_symbols = data.get("user_symbols", {})
            font = data.get("font")
            copper_data = data.get("copper_data", {})
            all_matrix_layers = data.get("matrix_layers_ordered", [])

            # Build ordered list of signal layers
            signal_layers = [
                name for name, (_, ml) in sorted(
                    layers_data.items(), key=lambda x: x[1][1].row
                )
                if ml.type == "SIGNAL"
            ]

            self._log(f"Found {len(signal_layers)} signal layers.")

            # Create images directory
            excel_dir = Path(excel_path).parent
            images_dir = excel_dir / "images"
            images_dir.mkdir(parents=True, exist_ok=True)

            layer_results = []
            for i, layer_name in enumerate(signal_layers):
                self._log(f"[{i + 1}/{len(signal_layers)}] Processing {layer_name} ({method_label})...")

                if use_vector:
                    self._log(f"  Calculating copper ratio (vector)...")
                    total_ratio = copper_vector.calculate_copper_ratio(
                        layer_name, profile, layers_data, user_symbols, font,
                    )

                    self._log(f"  Calculating sub-section ratios ({n_rows}×{n_cols}, vector)...")
                    sub_ratios = copper_vector.calculate_subsection_ratios(
                        layer_name, profile, layers_data, user_symbols, font,
                        n_rows=n_rows, n_cols=n_cols,
                    )

                    # Still use raster for the PNG visualization
                    self._log(f"  Saving image...")
                    safe_name = (
                        layer_name
                        .replace("/", "_").replace("\\", "_").replace(":", "_")
                        .replace("[", "_").replace("]", "_").replace("*", "_").replace("?", "_")
                    )
                    img_path = images_dir / f"{safe_name}.png"
                    copper_utils.save_layer_image(
                        layer_name, profile, layers_data, user_symbols, font,
                        sub_ratios, img_path,
                        n_rows=n_rows, n_cols=n_cols,
                    )
                else:
                    self._log(f"  Rasterizing layer...")
                    raster = copper_utils.rasterize_layer(
                        layer_name, profile, layers_data, user_symbols, font
                    )

                    self._log(f"  Calculating copper ratio (raster)...")
                    total_ratio = copper_utils.calculate_copper_ratio(
                        layer_name, profile, layers_data, user_symbols, font,
                        raster_data=raster,
                    )

                    self._log(f"  Calculating sub-section ratios ({n_rows}×{n_cols}, raster)...")
                    sub_ratios = copper_utils.calculate_subsection_ratios(
                        layer_name, profile, layers_data, user_symbols, font,
                        n_rows=n_rows, n_cols=n_cols,
                        raster_data=raster,
                    )

                    self._log(f"  Saving image...")
                    safe_name = (
                        layer_name
                        .replace("/", "_").replace("\\", "_").replace(":", "_")
                        .replace("[", "_").replace("]", "_").replace("*", "_").replace("?", "_")
                    )
                    img_path = images_dir / f"{safe_name}.png"
                    copper_utils.save_layer_image(
                        layer_name, profile, layers_data, user_symbols, font,
                        sub_ratios, img_path,
                        n_rows=n_rows, n_cols=n_cols,
                    )

                _, ml = layers_data[layer_name]
                thickness = copper_data.get(layer_name)

                layer_results.append({
                    "layer_name": layer_name,
                    "total_ratio": total_ratio,
                    "subsection_ratios": sub_ratios,
                    "thickness_mm": thickness,
                    "image_path": img_path.relative_to(excel_dir),
                })

            self._log("Generating Excel report...")
            generate_copper_report(layer_results, copper_data, all_matrix_layers, excel_path)

            self._log(f"Done! Report saved to: {excel_path}")
            self._log("Window will close in 2 seconds...")

            if self._root:
                self._root.after(2000, self._root.destroy)

        except Exception as e:
            self._log(f"Error: {e}")
            import traceback
            self._log(traceback.format_exc())
            if self._root:
                self._root.after(0, lambda: self._calc_btn.config(state=tk.NORMAL))

    def _log(self, message: str):
        """Append a message to the status text widget (thread-safe)."""
        def _update():
            if self._status_text:
                self._status_text.config(state=tk.NORMAL)
                self._status_text.insert(tk.END, message + "\n")
                self._status_text.see(tk.END)
                self._status_text.config(state=tk.DISABLED)

        if self._root:
            self._root.after(0, _update)


# ===========================================================================
# Net Viewer
# ===========================================================================

class NetViewer:
    """Signal-layer net visualizer.

    Left panel (top → bottom):
      - Signal Layer Selection : Listbox (single-select, SIGNAL layers only)
      - Net Search             : Entry widget for filtering net names
      - Net Selection          : Listbox (multi-select, scrollable)
      - Selection buttons      : Select All / Deselect All / Invert
      - Update Visualization   : button
      - Info                   : selected layer / net count summary

    Right panel: matplotlib canvas.

    Interaction:
      1. Select a signal layer  → net list is rebuilt for that layer.
      2. Filter nets via search → net list filters in real-time.
      3. Select nets and click "Update Visualization" → renders filtered features.
    """

    def __init__(self,
                 profile: Profile,
                 layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
                 eda_data: EdaData,
                 user_symbols: dict[str, UserSymbol] = None,
                 font: StrokeFont = None):
        self.profile      = profile
        self.layers_data  = layers_data
        self.eda_data     = eda_data
        self.user_symbols = user_symbols or {}
        self.font         = font

        from src.visualizer.net_filter import (
            build_net_feature_index, get_signal_layers,
        )
        self._net_index   = build_net_feature_index(eda_data, layers_data)
        self._signal_layers: list[str] = get_signal_layers(layers_data)

        # All net names for the currently selected layer
        self._layer_nets: list[str] = []
        # Net names currently shown in the listbox (after search filter)
        self._visible_nets: list[str] = []

        self._selected_layer: Optional[str] = None
        self._info_var: Optional[tk.StringVar] = None
        self._net_lb: Optional[tk.Listbox] = None
        self._search_var: Optional[tk.StringVar] = None
        self._root: Optional[tk.Tk] = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def show(self, figsize: tuple[float, float] = (14, 9)):
        root = tk.Tk()
        self._root = root
        root.title("ODB++ Net Viewer")
        root.configure(bg=_BG)
        try:
            root.state("zoomed")
        except tk.TclError:
            pass

        # ---- Left panel ---------------------------------------------------
        left = tk.Frame(root, bg=_BG, width=240)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(6, 3), pady=6)
        left.pack_propagate(False)

        # Signal layer selection (single-select)
        _section_label(left, "Signal Layer").pack(anchor="w", pady=(4, 4))
        lb_layer_frame, self._layer_lb = _make_listbox(
            left, height=6, selectmode=tk.SINGLE,
        )
        lb_layer_frame.pack(fill=tk.X, pady=(0, 4))
        for name in self._signal_layers:
            self._layer_lb.insert(tk.END, name)
        self._layer_lb.bind("<<ListboxSelect>>", self._on_layer_select)

        _divider(left).pack(fill=tk.X, pady=(0, 4))

        # Net search
        _section_label(left, "Net Selection").pack(anchor="w", pady=(0, 2))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search_change)
        search_entry = tk.Entry(
            left,
            textvariable=self._search_var,
            bg=_BG2, fg=_FG,
            insertbackground=_FG,
            relief=tk.FLAT,
            font=_FONT,
            highlightbackground="#cccccc",
            highlightthickness=1,
        )
        search_entry.pack(fill=tk.X, padx=2, pady=(0, 4))

        # Net listbox (multi-select, expands to fill space)
        lb_net_frame, self._net_lb = _make_listbox(left, height=12)
        lb_net_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        # Selection control buttons
        btn_frame = tk.Frame(left, bg=_BG)
        btn_frame.pack(fill=tk.X, pady=(0, 6))
        for label, cmd in [
            ("Select All",   self._select_all),
            ("Deselect All", self._deselect_all),
            ("Invert",       self._invert_selection),
        ]:
            tk.Button(
                btn_frame, text=label,
                bg="#e0e0e0", fg="#1a1a1a",
                activebackground="#c8c8c8", activeforeground="#1a1a1a",
                font=("Segoe UI", 9),
                relief=tk.FLAT, cursor="hand2",
                command=cmd,
            ).pack(fill=tk.X, pady=1, padx=2)

        # Update button
        tk.Button(
            left, text="Update Visualization",
            bg="#1a73e8", fg="#ffffff",
            activebackground="#1557b0", activeforeground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT, cursor="hand2",
            command=self._on_update,
        ).pack(fill=tk.X, pady=(0, 8), padx=2)

        # Info text
        _divider(left).pack(fill=tk.X, pady=(0, 4))
        _section_label(left, "Info").pack(anchor="w", pady=(0, 4))
        self._info_var = tk.StringVar(value="Select a layer to begin.")
        tk.Label(
            left,
            textvariable=self._info_var,
            bg=_BG, fg="#333333",
            font=("Segoe UI", 9),
            anchor="w",
            justify=tk.LEFT,
            wraplength=220,
        ).pack(fill=tk.X, padx=4)

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

        root.mainloop()

    # ------------------------------------------------------------------
    # Layer selection
    # ------------------------------------------------------------------

    def _on_layer_select(self, _event=None):
        sel = self._layer_lb.curselection()
        if not sel:
            return
        self._selected_layer = self._signal_layers[sel[0]]
        self._rebuild_net_list()
        self._draw_board_only()

    def _rebuild_net_list(self):
        from src.visualizer.net_filter import get_nets_for_layer
        if self._selected_layer is None:
            return
        self._layer_nets = get_nets_for_layer(
            self._selected_layer, self._net_index
        )
        self._apply_search_filter()

    # ------------------------------------------------------------------
    # Net search
    # ------------------------------------------------------------------

    def _on_search_change(self, *_):
        self._apply_search_filter()

    def _apply_search_filter(self):
        query = (self._search_var.get() if self._search_var else "").strip().lower()
        if query:
            self._visible_nets = [n for n in self._layer_nets if query in n.lower()]
        else:
            self._visible_nets = list(self._layer_nets)

        self._net_lb.delete(0, tk.END)
        for name in self._visible_nets:
            self._net_lb.insert(tk.END, name)

        total = len(self._layer_nets)
        shown = len(self._visible_nets)
        layer = self._selected_layer or "—"
        if query:
            self._info_var.set(
                f"Layer: {layer}\nNets: {shown}/{total} shown"
            )
        else:
            self._info_var.set(
                f"Layer: {layer}\nNets: {total} total"
            )

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def _select_all(self):
        self._net_lb.selection_set(0, tk.END)

    def _deselect_all(self):
        self._net_lb.selection_clear(0, tk.END)

    def _invert_selection(self):
        for i in range(self._net_lb.size()):
            if self._net_lb.selection_includes(i):
                self._net_lb.selection_clear(i)
            else:
                self._net_lb.selection_set(i)

    # ------------------------------------------------------------------
    # Update / render
    # ------------------------------------------------------------------

    def _on_update(self):
        if self._selected_layer is None:
            self._info_var.set("Please select a signal layer first.")
            return

        selected_indices = self._net_lb.curselection()
        selected_nets = [self._visible_nets[i] for i in selected_indices]

        if not selected_nets:
            self._info_var.set("No nets selected.")
            self._draw_board_only()
            return

        # Union of feature indices for all selected nets on this layer
        from src.visualizer.net_filter import filter_layer_features
        allowed: set[int] = set()
        for net_name in selected_nets:
            layer_map = self._net_index.get(net_name, {})
            allowed |= layer_map.get(self._selected_layer, set())

        layer_features, matrix_layer = self.layers_data[self._selected_layer]
        filtered = filter_layer_features(layer_features, allowed)
        flip = is_bottom_layer(self._selected_layer)

        self.ax.clear()
        _style_axes(self.ax)
        if self.profile and self.profile.surface:
            _draw_profile(self.ax, self.profile)

        # Background: full layer at low opacity
        color = LAYER_COLORS.get(matrix_layer.type, "#008E5C")
        render_layer(
            self.ax, layer_features,
            color=color,
            layer_type=matrix_layer.type,
            alpha=0.25,
            user_symbols=self.user_symbols,
            font=self.font,
            flip_x=flip,
        )

        # Foreground: selected net features in red
        render_layer(
            self.ax, filtered,
            color="#FF7E7E",
            layer_type=matrix_layer.type,
            alpha=0.95,
            user_symbols=self.user_symbols,
            font=self.font,
            flip_x=flip,
        )

        self.ax.set_xlabel("X", color="#000000")
        self.ax.set_ylabel("Y", color="#000000")
        self.ax.set_title(
            f"Layer: {self._selected_layer}  |  "
            f"{len(selected_nets)} net(s)  |  {len(filtered.features)} feature(s)",
            color="#000000",
        )
        self.ax.grid(False)
        self.ax.set_aspect("equal")
        self.canvas.draw()

        self._info_var.set(
            f"Layer: {self._selected_layer}\n"
            f"Selected nets: {len(selected_nets)}\n"
            f"Features shown: {len(filtered.features)}"
        )

    # ------------------------------------------------------------------
    # Board-only draw
    # ------------------------------------------------------------------

    def _draw_board_only(self):
        self.ax.clear()
        _style_axes(self.ax)
        if self.profile and self.profile.surface:
            _draw_profile(self.ax, self.profile)

        layer = self._selected_layer or ""
        if layer and layer in self.layers_data:
            _, matrix_layer = self.layers_data[layer]
            color = LAYER_COLORS.get(matrix_layer.type, "#008E5C")
            layer_features, _ = self.layers_data[layer]
            render_layer(
                self.ax, layer_features,
                color=color,
                layer_type=matrix_layer.type,
                alpha=0.4,
                user_symbols=self.user_symbols,
                font=self.font,
                flip_x=is_bottom_layer(layer),
            )

        self.ax.set_xlabel("X", color="#000000")
        self.ax.set_ylabel("Y", color="#000000")
        title = f"Layer: {layer}" if layer else "Select a layer"
        self.ax.set_title(title, color="#000000")
        self.ax.grid(False)
        self.ax.set_aspect("equal")
        self.canvas.draw()
