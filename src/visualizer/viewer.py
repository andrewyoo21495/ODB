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

        # Extract component-layer features for accurate pad rendering.
        # comp_+_top / comp_+_bot layers are loaded but not shown as layers;
        # we pull them here so draw_components can use the real pad shapes.
        self._comp_layer_top: Optional[LayerFeatures] = next(
            (lf for name, (lf, _) in layers_data.items() if "comp_+_top" in name),
            None,
        )
        self._comp_layer_bot: Optional[LayerFeatures] = next(
            (lf for name, (lf, _) in layers_data.items() if "comp_+_bot" in name),
            None,
        )

        # Build FID-based pin-to-feature lookup (primary pad rendering path).
        self._fid_resolved: dict = {}
        if eda_data and eda_data.layer_names:
            from src.visualizer.fid_lookup import build_fid_map, resolve_fid_features
            fid_map = build_fid_map(eda_data)
            if fid_map:
                self._fid_resolved = resolve_fid_features(
                    fid_map, eda_data.layer_names, layers_data,
                )

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
                         font=self.font)

        packages = self.eda_data.packages if self.eda_data else None
        if COMP_TOP_KEY in self._visible_set and self.components_top:
            draw_components(self.ax, self.components_top, packages,
                            color="#2BFFF4", alpha=0.99,
                            show_pads=True, show_pkg_outlines=False,
                            comp_layer_features=self._comp_layer_top,
                            user_symbols=self.user_symbols,
                            fid_resolved=self._fid_resolved, comp_side="T")
        if COMP_BOT_KEY in self._visible_set and self.components_bot:
            draw_components(self.ax, self.components_bot, packages,
                            color="#FC5BA1", alpha=0.99,
                            show_pads=True, show_pkg_outlines=False,
                            comp_layer_features=self._comp_layer_bot,
                            user_symbols=self.user_symbols,
                            fid_resolved=self._fid_resolved, comp_side="B")
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
                                comp_layer_features=(self._comp_layer_bot
                                                     if is_bot
                                                     else self._comp_layer_top),
                                user_symbols=self.user_symbols,
                                fid_resolved=self._fid_resolved,
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
                            comp_layer_features=self._comp_layer_top,
                            user_symbols=self.user_symbols,
                            fid_resolved=self._fid_resolved, comp_side="T")
        if drew_bot and self.components_bot:
            draw_components(self.ax, self.components_bot, packages,
                            color="#FFFF00", alpha=0.95,
                            show_pads=False, show_pkg_outlines=True,
                            comp_layer_features=self._comp_layer_bot,
                            user_symbols=self.user_symbols,
                            fid_resolved=self._fid_resolved, comp_side="B")
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

        self._comp_layer_top: Optional[LayerFeatures] = next(
            (lf for name, (lf, _) in layers_data.items() if "comp_+_top" in name),
            None,
        )
        self._comp_layer_bot: Optional[LayerFeatures] = next(
            (lf for name, (lf, _) in layers_data.items() if "comp_+_bot" in name),
            None,
        )

        self._fid_resolved: dict = {}
        if eda_data and eda_data.layer_names and layers_data:
            from src.visualizer.fid_lookup import build_fid_map, resolve_fid_features
            fid_map = build_fid_map(eda_data)
            if fid_map:
                self._fid_resolved = resolve_fid_features(
                    fid_map, eda_data.layer_names, layers_data,
                )

        self._selected_comp:     Optional[Component] = None
        self._selected_pin_name: str               = ""
        self._current_layer      = "Both"
        self._drawn_comps:       list[Component]   = []
        self._comp_names:        list[str]         = []
        self._current_comps:     list[Component]   = []
        self._current_show_pins: bool              = True
        self._current_show_outline: bool           = False

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
        if comps and (show_pins or show_outline):
            top_set   = {c.comp_name for c in self.components_top}
            top_comps = [c for c in comps if c.comp_name in top_set]
            bot_comps = [c for c in comps if c.comp_name not in top_set]
            if show_pins:
                if top_comps:
                    draw_components(self.ax, top_comps, packages,
                                    color="#2BFFF4", alpha=0.99,
                                    show_pads=True, show_pkg_outlines=False,
                                    comp_layer_features=self._comp_layer_top,
                                    user_symbols=self.user_symbols,
                                    fid_resolved=self._fid_resolved,
                                    comp_side="T")
                if bot_comps:
                    draw_components(self.ax, bot_comps, packages,
                                    color="#FC5BA1", alpha=0.99,
                                    show_pads=True, show_pkg_outlines=False,
                                    comp_layer_features=self._comp_layer_bot,
                                    user_symbols=self.user_symbols,
                                    fid_resolved=self._fid_resolved,
                                    comp_side="B")
            if show_outline:
                if top_comps:
                    draw_components(self.ax, top_comps, packages,
                                    color="#FFFF00", alpha=0.99,
                                    show_pads=False, show_pkg_outlines=True,
                                    comp_layer_features=self._comp_layer_top,
                                    user_symbols=self.user_symbols,
                                    fid_resolved=self._fid_resolved,
                                    comp_side="T")
                if bot_comps:
                    draw_components(self.ax, bot_comps, packages,
                                    color="#FFFF00", alpha=0.99,
                                    show_pads=False, show_pkg_outlines=True,
                                    comp_layer_features=self._comp_layer_bot,
                                    user_symbols=self.user_symbols,
                                    fid_resolved=self._fid_resolved,
                                    comp_side="B")

        # Selection highlight – draw selected component in red on top
        if self._selected_comp is not None and self._selected_comp in (comps or []):
            is_bot = self._selected_comp in self.components_bot
            draw_components(self.ax, [self._selected_comp], packages,
                            color="#FF0000", alpha=1.0,
                            show_pads=True, show_pkg_outlines=True,
                            comp_layer_features=(self._comp_layer_bot
                                                 if is_bot
                                                 else self._comp_layer_top),
                            user_symbols=self.user_symbols,
                            fid_resolved=self._fid_resolved,
                            comp_side="B" if is_bot else "T")

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
# Via viewer  (extends ComponentViewer with VIA overlay)
# ===========================================================================

class ViaViewer:
    """Component viewer with an additional VIA visualize toggle.

    Shares the same base as ``ComponentViewer`` — top/bottom layer radio
    buttons, component listbox, display options — but adds a *VIA visualize*
    button that overlays SNT VIA pad features in dark grey.
    """

    _VIA_COLOR = "#505050"   # dark grey

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

        self._comp_layer_top: Optional[LayerFeatures] = next(
            (lf for name, (lf, _) in layers_data.items() if "comp_+_top" in name),
            None,
        )
        self._comp_layer_bot: Optional[LayerFeatures] = next(
            (lf for name, (lf, _) in layers_data.items() if "comp_+_bot" in name),
            None,
        )

        self._fid_resolved: dict = {}
        if eda_data and eda_data.layer_names and layers_data:
            from src.visualizer.fid_lookup import build_fid_map, resolve_fid_features
            fid_map = build_fid_map(eda_data)
            if fid_map:
                self._fid_resolved = resolve_fid_features(
                    fid_map, eda_data.layer_names, layers_data,
                )

        # Resolve VIA features
        self._via_features: list = []
        if eda_data and eda_data.layer_names and layers_data:
            from src.visualizer.fid_lookup import resolve_via_features
            self._via_features = resolve_via_features(eda_data, layers_data)

        # Identify top/bottom signal layer names for filtering vias by layer
        self._via_layer_top: set[str] = set()
        self._via_layer_bot: set[str] = set()
        if eda_data and eda_data.layer_names and layers_data:
            from src.visualizer.fid_lookup import identify_signal_layers
            matrix_map = {n: ml for n, (_, ml) in layers_data.items()}
            sig = identify_signal_layers(eda_data.layer_names, matrix_map)
            if "sigt" in sig:
                self._via_layer_top.add(sig["sigt"])
            if "sigb" in sig:
                self._via_layer_bot.add(sig["sigb"])

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
        root = tk.Tk()
        root.title("ODB++ Via Viewer")
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

        # VIA visualize button
        _divider(left).pack(fill=tk.X, pady=(0, 4))
        self._via_btn = tk.Button(
            left, text="VIA visualize",
            bg="#e0e0e0", fg="#1a1a1a",
            activebackground="#c8c8c8", activeforeground="#1a1a1a",
            font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT, cursor="hand2",
            command=self._toggle_vias,
        )
        self._via_btn.pack(fill=tk.X, pady=(0, 8), padx=2)

        # Component info
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

        self._rebuild_component_list()

        root.mainloop()

    # ------------------------------------------------------------------
    # VIA toggle
    # ------------------------------------------------------------------

    def _toggle_vias(self):
        self._show_vias = not self._show_vias
        if self._show_vias:
            self._via_btn.configure(bg="#505050", fg="#ffffff",
                                    activebackground="#666666",
                                    activeforeground="#ffffff")
        else:
            self._via_btn.configure(bg="#e0e0e0", fg="#1a1a1a",
                                    activebackground="#c8c8c8",
                                    activeforeground="#1a1a1a")
        self._redraw(self._current_comps,
                     self._current_show_pins,
                     self._current_show_outline)

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

        # Draw vias underneath components when enabled
        if self._show_vias:
            self._draw_vias()

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
                                    comp_layer_features=self._comp_layer_top,
                                    user_symbols=self.user_symbols,
                                    fid_resolved=self._fid_resolved,
                                    comp_side="T")
                if bot_comps:
                    draw_components(self.ax, bot_comps, packages,
                                    color="#FC5BA1", alpha=0.99,
                                    show_pads=True, show_pkg_outlines=False,
                                    comp_layer_features=self._comp_layer_bot,
                                    user_symbols=self.user_symbols,
                                    fid_resolved=self._fid_resolved,
                                    comp_side="B")
            if show_outline:
                if top_comps:
                    draw_components(self.ax, top_comps, packages,
                                    color="#FFFF00", alpha=0.99,
                                    show_pads=False, show_pkg_outlines=True,
                                    comp_layer_features=self._comp_layer_top,
                                    user_symbols=self.user_symbols,
                                    fid_resolved=self._fid_resolved,
                                    comp_side="T")
                if bot_comps:
                    draw_components(self.ax, bot_comps, packages,
                                    color="#FFFF00", alpha=0.99,
                                    show_pads=False, show_pkg_outlines=True,
                                    comp_layer_features=self._comp_layer_bot,
                                    user_symbols=self.user_symbols,
                                    fid_resolved=self._fid_resolved,
                                    comp_side="B")

        # Selection highlight
        if self._selected_comp is not None and self._selected_comp in (comps or []):
            is_bot = self._selected_comp in self.components_bot
            draw_components(self.ax, [self._selected_comp], packages,
                            color="#FF0000", alpha=1.0,
                            show_pads=True, show_pkg_outlines=True,
                            comp_layer_features=(self._comp_layer_bot
                                                 if is_bot
                                                 else self._comp_layer_top),
                            user_symbols=self.user_symbols,
                            fid_resolved=self._fid_resolved,
                            comp_side="B" if is_bot else "T")

        self._apply_axis_labels()
        self.canvas.draw()

    def _apply_axis_labels(self):
        self.ax.set_xlabel("X", color="#000000")
        self.ax.set_ylabel("Y", color="#000000")
        layer = self._layer_var.get() if hasattr(self, '_layer_var') else "Both"
        via_suffix = " + VIA" if self._show_vias else ""
        self.ax.set_title(f"Components: {layer}{via_suffix}", color="#000000")
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
            d = (comp.x - x) ** 2 + (comp.y - y) ** 2
            if d < best_dist_sq:
                best_dist_sq = d
                best_comp    = comp
                best_pin     = ""
            for tp in comp.toeprints:
                d = (tp.x - x) ** 2 + (tp.y - y) ** 2
                if d < best_dist_sq:
                    best_dist_sq = d
                    best_comp    = comp
                    best_pin     = tp.name
        return best_comp, best_pin

    # ------------------------------------------------------------------
    # Coordinate formatter  (ViaViewer)
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

    def _on_calculate(self):
        import numpy as np

        if self._selected_layer is None:
            self._result_var.set("Select a layer first.")
            return
        self._result_var.set("Calculating\u2026")
        if self._root:
            self._root.update_idletasks()

        if self._subsection_mode and self._subsection_mode.get():
            # ---- Grid-based calculation -----------------------------------
            self._ratio_result = None
            ratios = self._calculate_subsection_ratios()
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
                    )
                else:
                    self._result_var.set("No PCB area found.")
                self._update_subsection_display()
                self._redraw()
            else:
                self._result_var.set("Calculation failed.")
        else:
            # ---- Whole-board calculation (existing) -----------------------
            self._subsection_ratios = None
            self._clear_subsection_display()
            ratio = self._calculate_ratio()
            if ratio is not None:
                self._ratio_result = ratio
                self._result_var.set(
                    f"Ratio: {ratio:.4f}  ({ratio * 100:.2f}%)"
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
                         font=self.font)

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

        Returns a dict with keys:
            rgb       – np.ndarray (H, W, 3) uint8 rendered image
            pcb_mask  – np.ndarray (H, W) bool, True inside PCB outline
            xmin, xmax, ymin, ymax  – bounding box in data coords (mm)
            img_w, img_h            – image dimensions in pixels

        Returns None if the profile or selected layer is unavailable.

        Algorithm
        ---------
        A dedicated **off-screen** figure is created at 200 DPI with the
        axes tight-fitted to the PCB bounding box so the result is
        completely independent of the user's zoom level or window size.
        """
        import numpy as np
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.path import Path
        from src.visualizer.symbol_renderer import contour_to_vertices

        if not self.profile or not self.profile.surface:
            return None
        if self._selected_layer not in self.layers_data:
            return None

        # ---- 1. Find the PCB outline (island contour) --------------------
        outline_verts = None
        for contour in self.profile.surface.contours:
            verts = contour_to_vertices(contour)
            if contour.is_island and len(verts) >= 3:
                outline_verts = verts
                break
        if outline_verts is None:
            return None

        # ---- 2. Compute tight PCB bounding box ---------------------------
        xmin = float(outline_verts[:, 0].min())
        xmax = float(outline_verts[:, 0].max())
        ymin = float(outline_verts[:, 1].min())
        ymax = float(outline_verts[:, 1].max())
        board_w = xmax - xmin
        board_h = ymax - ymin
        if board_w <= 0 or board_h <= 0:
            return None

        # ---- 3. Build a fixed-resolution off-screen figure ---------------
        # Target ~2 000 px on the longer axis at 200 DPI → figure is
        # ~10 in on that axis regardless of actual board physical size.
        _DPI  = 200
        _LONG = 10.0
        if board_w >= board_h:
            fig_w, fig_h = _LONG, _LONG * board_h / board_w
        else:
            fig_w, fig_h = _LONG * board_w / board_h, _LONG
        fig_w = max(fig_w, 1.0)
        fig_h = max(fig_h, 1.0)

        calc_fig = Figure(figsize=(fig_w, fig_h), dpi=_DPI, facecolor="black")
        calc_ax  = calc_fig.add_axes([0.0, 0.0, 1.0, 1.0])
        calc_ax.set_facecolor("#000000")
        calc_ax.set_xlim(xmin, xmax)
        calc_ax.set_ylim(ymin, ymax)
        calc_ax.set_aspect("equal", adjustable="box")
        calc_ax.axis("off")

        # NOTE: _draw_profile is intentionally omitted here.
        # The PCB polygon mask is built from outline_verts geometrically
        # (Path.contains_points), so the rendered outline is not needed.
        # Including it causes anti-aliased edge pixels (blended red+black)
        # to be miscounted as copper, especially in narrow/tail regions.
        features, matrix_layer = self.layers_data[self._selected_layer]
        color = LAYER_COLORS.get(matrix_layer.type, "#00CC00")
        render_layer(calc_ax, features, color=color,
                     layer_type=matrix_layer.type,
                     alpha=1.0, user_symbols=self.user_symbols,
                     font=self.font)

        # ---- 4. Rasterise to numpy RGBA ----------------------------------
        agg = FigureCanvasAgg(calc_fig)
        agg.draw()
        buf  = agg.buffer_rgba()
        w, h = agg.get_width_height()
        img  = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
        rgb  = img[:, :, :3]

        # ---- 5. Map outline → image-pixel coordinates --------------------
        # transData: data → display pixels (origin bottom-left of figure)
        # image:     origin top-left, y increases downward  →  flip y
        display_pts = calc_ax.transData.transform(outline_verts)
        img_pts = np.column_stack([
            display_pts[:, 0],
            h - display_pts[:, 1],
        ])

        # ---- 6. Inside-PCB mask ------------------------------------------
        path = Path(img_pts)
        ys, xs = np.mgrid[0:h, 0:w]
        pts = np.column_stack([xs.ravel() + 0.5, ys.ravel() + 0.5])
        pcb_mask = path.contains_points(pts).reshape(h, w)

        return {
            "rgb":      rgb,
            "pcb_mask": pcb_mask,
            "xmin": xmin, "xmax": xmax,
            "ymin": ymin, "ymax": ymax,
            "img_w": w,   "img_h": h,
        }

    # ------------------------------------------------------------------
    # Ratio calculation
    # ------------------------------------------------------------------

    def _calculate_ratio(self) -> Optional[float]:
        """Copper fill ratio for the entire selected layer (0 – 1)."""
        import numpy as np

        data = self._rasterize_layer()
        if data is None:
            return None

        rgb        = data["rgb"]
        inside_mask = data["pcb_mask"]
        total_inside = int(inside_mask.sum())
        if total_inside == 0:
            return None

        # "copper" = non-black AND not the red profile-outline colour
        is_nonblack = np.any(rgb > 20, axis=2)
        is_red = (
            (rgb[:, :, 0] > 180) &
            (rgb[:, :, 1] < 60)  &
            (rgb[:, :, 2] < 60)
        )
        is_copper    = is_nonblack & ~is_red
        copper_inside = int((inside_mask & is_copper).sum())
        return copper_inside / total_inside

    def _calculate_subsection_ratios(self):
        """Copper fill ratio for each cell of an n_rows × n_cols grid.

        Returns an np.ndarray of shape (n_rows, n_cols) with values in
        [0, 1].  Cells that contain no PCB area are set to np.nan.
        Returns None if rasterization fails.

        Grid orientation
        ----------------
        Row 0 is the *top* of the PCB (y = ymax), row n_rows-1 is the
        bottom (y = ymin), matching standard image-coordinate order.
        Column 0 is the *left* (x = xmin).
        """
        import numpy as np

        data = self._rasterize_layer()
        if data is None:
            return None

        rgb      = data["rgb"]
        pcb_mask = data["pcb_mask"]
        h, w     = data["img_h"], data["img_w"]

        # Copper pixel classification (same thresholds as _calculate_ratio)
        is_nonblack = np.any(rgb > 20, axis=2)
        is_red = (
            (rgb[:, :, 0] > 180) &
            (rgb[:, :, 1] < 60)  &
            (rgb[:, :, 2] < 60)
        )
        is_copper = is_nonblack & ~is_red

        ratios = np.full((self._n_rows, self._n_cols), np.nan)
        for i in range(self._n_rows):
            r0 = round(i       * h / self._n_rows)
            r1 = round((i + 1) * h / self._n_rows)
            for j in range(self._n_cols):
                c0 = round(j       * w / self._n_cols)
                c1 = round((j + 1) * w / self._n_cols)

                cell_pcb = pcb_mask[r0:r1, c0:c1]
                total    = int(cell_pcb.sum())
                if total == 0:
                    continue
                copper = int((cell_pcb & is_copper[r0:r1, c0:c1]).sum())
                ratios[i, j] = copper / total

        return ratios

    # ------------------------------------------------------------------
    # Sub-section overlay (drawn on the interactive canvas)
    # ------------------------------------------------------------------

    def _draw_subsection_overlay(self):
        """Draw a colour-coded grid heatmap on self.ax.

        Each cell is filled with a RdYlGn colour proportional to its
        copper ratio.  Cells with no PCB area are drawn as translucent
        grey.  A colorbar legend is added to the figure.
        """
        import numpy as np
        import matplotlib.cm as cm
        import matplotlib.colors as mcolors
        import matplotlib.patches as mpatches
        from src.visualizer.symbol_renderer import contour_to_vertices

        ratios = self._subsection_ratios
        if ratios is None:
            return

        # Re-derive bounding box from profile (fast, no rendering)
        outline_verts = None
        for contour in self.profile.surface.contours:
            verts = contour_to_vertices(contour)
            if contour.is_island and len(verts) >= 3:
                outline_verts = verts
                break
        if outline_verts is None:
            return

        xmin = float(outline_verts[:, 0].min())
        xmax = float(outline_verts[:, 0].max())
        ymin = float(outline_verts[:, 1].min())
        ymax = float(outline_verts[:, 1].max())
        board_w = xmax - xmin
        board_h = ymax - ymin
        cell_w  = board_w / self._n_cols
        cell_h  = board_h / self._n_rows

        cmap = cm.RdYlGn
        norm = mcolors.Normalize(vmin=0.0, vmax=1.0)

        for i in range(self._n_rows):
            # Row 0 in ratios array = top of board = ymax
            y_bottom = ymax - (i + 1) * cell_h
            for j in range(self._n_cols):
                x_left = xmin + j * cell_w
                ratio  = ratios[i, j]

                if np.isnan(ratio):
                    facecolor = "#aaaaaa"
                    alpha     = 0.15
                    label     = ""
                else:
                    facecolor = cmap(norm(ratio))
                    alpha     = 0.55
                    label     = f"{ratio * 100:.1f}%"

                rect = mpatches.Rectangle(
                    (x_left, y_bottom), cell_w, cell_h,
                    facecolor=facecolor,
                    edgecolor="white",
                    linewidth=0.8,
                    alpha=alpha,
                    zorder=5,
                )
                self.ax.add_patch(rect)

                if label:
                    cx = x_left  + cell_w / 2
                    cy = y_bottom + cell_h / 2
                    # Pick text colour for readability over the cell fill
                    r, g, b, _ = cmap(norm(ratio))
                    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
                    txt_color = "black" if lum > 0.40 else "white"
                    self.ax.text(
                        cx, cy, label,
                        ha="center", va="center",
                        fontsize=7, color=txt_color,
                        fontweight="bold", zorder=6,
                    )

        # Colorbar
        sm = cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        self._colorbar = self.fig.colorbar(
            sm, ax=self.ax,
            fraction=0.02, pad=0.02, shrink=0.6,
            label="Copper Ratio",
        )
        self._colorbar.set_ticks([0, 0.25, 0.50, 0.75, 1.0])
        self._colorbar.set_ticklabels(["0%", "25%", "50%", "75%", "100%"])

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
