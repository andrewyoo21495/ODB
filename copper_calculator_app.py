"""Standalone Copper Ratio Calculator Application.

This is a self-contained GUI application that extracts the copper-calculate
functionality from the ODB++ Processing System and packages it for
distribution as a standalone .exe.

Usage:
    python copper_calculator_app.py          (launch GUI)
    pyinstaller copper_calculator.spec       (build .exe)
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import tkinter as tk
import tkinter.filedialog as filedialog
import traceback
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent))

from src import odb_loader
from src.cache_manager import (
    cache_job, cache_layer, is_cache_valid, load_cache,
    reconstruct_profile, reconstruct_eda_data, reconstruct_components,
    reconstruct_layer_features, reconstruct_matrix_layers,
    reconstruct_font, reconstruct_user_symbols,
)
from src.visualizer import copper_utils
from src.copper_reporter import generate_copper_report

# ── UI constants ──────────────────────────────────────────────────────────
_BG = "#f4f4f4"
_BG2 = "#ffffff"
_FG = "#1a1a1a"
_ACCENT = "#1a73e8"
_ACCENT_ACTIVE = "#1557b0"
_FONT = ("Segoe UI", 10)
_FONT_BOLD = ("Segoe UI", 11, "bold")
_FONT_MONO = ("Consolas", 9)


# ── Data loading (adapted from main.py) ──────────────────────────────────

def _parse_attrlist_value(attrlist_path: Path, key: str) -> float | None:
    """Read a numeric value for *key* from a layer attrlist file."""
    prefix = key if key.endswith("=") else key + "="
    try:
        with open(attrlist_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith(prefix):
                    return float(line.split("=", 1)[1].strip())
    except Exception:
        pass
    return None


def _select_step(job):
    """Select the appropriate step: 'array' step if available, else first."""
    for name, sp in job.steps.items():
        if name.lower() == "array":
            return name, sp
    name, sp = next(iter(job.steps.items()))
    return name, sp


def _cmd_cache(odb_path: str, cache_dir: Path, log_fn=None):
    """Parse ODB++ data and cache to JSON files (subset of main.cmd_cache)."""
    from src.parsers.matrix_parser import parse_matrix
    from src.parsers.feature_parser import parse_features
    from src.parsers.profile_parser import parse_profile

    job = odb_loader.load(odb_path)
    cache_name = Path(odb_path).stem

    data = {}
    data["data_type"] = job.data_type

    # Parse matrix
    layer_type_map: dict[str, str] = {}
    if job.matrix_path:
        steps, layers = parse_matrix(job.matrix_path)
        data["matrix_steps"] = steps
        data["matrix_layers"] = layers
        layer_type_map = {ml.name: ml.type for ml in layers}

    # Parse font
    if job.font_path:
        from src.parsers.font_parser import parse_font
        font = parse_font(job.font_path)
        data["font"] = font

    # Parse the relevant step
    step_name, step_paths = _select_step(job)

    # Step header
    if step_paths.stephdr:
        from src.parsers.stephdr_parser import parse_stephdr
        header = parse_stephdr(step_paths.stephdr)
        data["step_header"] = header

    # Profile
    if step_paths.profile:
        profile = parse_profile(step_paths.profile)
        data["profile"] = profile

    # Symbols
    if job.symbols:
        from src.parsers.symbol_parser import parse_user_symbol
        symbols = {}
        for sym_name, sym_paths in job.symbols.items():
            if sym_paths.features:
                try:
                    sym_features = parse_features(sym_paths.features)
                    from src.models import UserSymbol
                    symbols[sym_name] = UserSymbol(name=sym_name, features=sym_features)
                except Exception:
                    pass
        if symbols:
            data["symbols"] = symbols

    # Layer features + copper data
    copper_data: dict[str, float] = {}
    for layer_name, layer_paths in step_paths.layers.items():
        if layer_paths.features:
            try:
                features = parse_features(layer_paths.features)
                data[f"layer_features:{layer_name}"] = features
            except Exception:
                pass

        layer_type = layer_type_map.get(layer_name, "")
        if layer_paths.attrlist:
            if layer_type == "SIGNAL":
                cw = _parse_attrlist_value(layer_paths.attrlist, ".copper_weight")
                if cw is not None:
                    copper_data[layer_name] = cw / 1000.0
            elif layer_type == "DIELECTRIC":
                dt = _parse_attrlist_value(layer_paths.attrlist, ".layer_dielectric")
                if dt is not None:
                    copper_data[layer_name] = dt

    if copper_data:
        data["copper_data"] = copper_data

    # Save cache
    cache_job(cache_dir, cache_name, data)
    job.cleanup()
    return cache_name


def _ensure_cache(odb_path: str, cache_dir: Path, log_fn=None) -> str:
    """Ensure a JSON cache exists; build it automatically if missing."""
    cache_name = Path(odb_path).stem
    cache_path = cache_dir / cache_name
    cache_files = list(cache_path.glob("*.json")) if cache_path.exists() else []
    if not cache_files:
        if log_fn:
            log_fn("No cache found. Building cache first...")
        _cmd_cache(odb_path, cache_dir, log_fn)
    return cache_name


def _load_from_cache(cache_dir: Path, cache_name: str) -> dict:
    """Load and reconstruct all job data from the JSON cache."""
    from src.models import JobInfo

    raw = load_cache(cache_dir, cache_name)
    if not raw:
        raise RuntimeError(f"Cache is empty or missing: {cache_dir / cache_name}")

    result: dict = {
        "job": None,
        "data_type": raw.get("data_type", "unit"),
        "components_top": [],
        "components_bot": [],
        "layers_data": {},
        "user_symbols": {},
    }

    if "profile" in raw:
        result["profile"] = reconstruct_profile(raw["profile"])
    if "components_top" in raw:
        result["components_top"] = reconstruct_components(raw["components_top"])
    if "components_bot" in raw:
        result["components_bot"] = reconstruct_components(raw["components_bot"])

    matrix_layers = reconstruct_matrix_layers(raw.get("matrix_layers", []))
    layer_lookup = {ml.name: ml for ml in matrix_layers}
    for key, value in raw.items():
        if key.startswith("layer_features:"):
            layer_name = key[len("layer_features:"):]
            ml = layer_lookup.get(layer_name)
            if ml:
                result["layers_data"][layer_name] = (
                    reconstruct_layer_features(value), ml
                )

    if "font" in raw:
        result["font"] = reconstruct_font(raw["font"])
    if "symbols" in raw:
        result["user_symbols"] = reconstruct_user_symbols(raw["symbols"])

    return result


def load_odb_data(odb_path: str, cache_dir: Path, log_fn=None) -> dict:
    """Load ODB++ data with copper and matrix layer info."""
    cn = _ensure_cache(odb_path, cache_dir, log_fn)
    data = _load_from_cache(cache_dir, cn)

    copper_file = cache_dir / cn / "copper_data.json"
    if copper_file.exists():
        with open(copper_file, "r", encoding="utf-8") as f:
            data["copper_data"] = json.load(f)
    else:
        data["copper_data"] = {}

    raw = load_cache(cache_dir, cn)
    ml_list = reconstruct_matrix_layers(raw.get("matrix_layers", []))
    data["matrix_layers_ordered"] = sorted(ml_list, key=lambda x: x.row)

    return data


# ── GUI Application ──────────────────────────────────────────────────────

class CopperCalculatorApp:
    """Standalone copper ratio batch calculator GUI."""

    def __init__(self):
        self._root: tk.Tk | None = None
        self._status_text: tk.Text | None = None
        self._calc_btn: tk.Button | None = None
        self._odb_var: tk.StringVar | None = None
        self._excel_var: tk.StringVar | None = None

    def run(self):
        """Launch the GUI window."""
        import matplotlib
        matplotlib.use("TkAgg")

        self._root = tk.Tk()
        self._root.title("Copper Ratio Calculator")
        self._root.geometry("700x450")
        self._root.configure(bg=_BG)
        self._root.minsize(500, 350)

        self._odb_var = tk.StringVar(value="")
        self._excel_var = tk.StringVar(value="")

        # ── Main layout ──
        main = tk.Frame(self._root, bg=_BG)
        main.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        # Title
        tk.Label(main, text="Copper Ratio Calculator", bg=_BG, fg=_FG,
                 font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 12))

        # ODB++ file row
        row1 = tk.Frame(main, bg=_BG)
        row1.pack(fill=tk.X, pady=(0, 6))

        tk.Label(row1, text="ODB++ File:", bg=_BG, fg=_FG, font=_FONT,
                 width=12, anchor="w").pack(side=tk.LEFT)
        tk.Entry(row1, textvariable=self._odb_var, bg=_BG2, fg=_FG,
                 font=_FONT).pack(side=tk.LEFT, padx=(0, 6), fill=tk.X, expand=True)
        tk.Button(row1, text="Browse...", bg=_ACCENT, fg="#ffffff",
                  activebackground=_ACCENT_ACTIVE, relief=tk.FLAT,
                  command=self._browse_odb).pack(side=tk.LEFT)

        # Excel output row
        row2 = tk.Frame(main, bg=_BG)
        row2.pack(fill=tk.X, pady=(0, 6))

        tk.Label(row2, text="Excel Output:", bg=_BG, fg=_FG, font=_FONT,
                 width=12, anchor="w").pack(side=tk.LEFT)
        tk.Entry(row2, textvariable=self._excel_var, bg=_BG2, fg=_FG,
                 font=_FONT).pack(side=tk.LEFT, padx=(0, 6), fill=tk.X, expand=True)
        tk.Button(row2, text="Save As...", bg=_ACCENT, fg="#ffffff",
                  activebackground=_ACCENT_ACTIVE, relief=tk.FLAT,
                  command=self._browse_excel).pack(side=tk.LEFT)

        # Button row
        row3 = tk.Frame(main, bg=_BG)
        row3.pack(fill=tk.X, pady=(6, 12))

        self._calc_btn = tk.Button(
            row3, text="Calculate", bg=_ACCENT, fg="#ffffff",
            activebackground=_ACCENT_ACTIVE, activeforeground="#ffffff",
            font=_FONT_BOLD, relief=tk.FLAT, cursor="hand2",
            command=self._on_calculate)
        self._calc_btn.pack(side=tk.LEFT)

        # Status section
        tk.Label(main, text="Status", bg=_BG, fg=_FG,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))

        status_frame = tk.Frame(main, bg=_BG2, highlightbackground="#cccccc",
                                highlightthickness=1)
        status_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(status_frame, orient=tk.VERTICAL, bg=_BG,
                                 troughcolor="#e0e0e0", relief=tk.FLAT)
        self._status_text = tk.Text(
            status_frame, height=12, bg=_BG2, fg=_FG, font=_FONT_MONO,
            borderwidth=0, highlightthickness=0, yscrollcommand=scrollbar.set,
            state=tk.DISABLED, wrap=tk.WORD)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._status_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self._status_text.yview)

        self._root.mainloop()

    def _browse_odb(self):
        path = filedialog.askopenfilename(
            filetypes=[
                ("ODB++ Archives", "*.tgz *.tar.gz *.zip"),
                ("All files", "*.*"),
            ])
        if path:
            self._odb_var.set(path)
            # Auto-suggest excel output path
            if not self._excel_var.get().strip():
                stem = Path(path).stem
                default_out = Path(path).parent / f"{stem}_copper_report.xlsx"
                self._excel_var.set(str(default_out))

    def _browse_excel(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")])
        if path:
            self._excel_var.set(path)

    def _on_calculate(self):
        odb_path = self._odb_var.get().strip()
        excel_path = self._excel_var.get().strip()

        if not odb_path:
            self._log("Error: Please select an ODB++ file.")
            return
        if not excel_path:
            self._log("Error: Please specify an Excel output path.")
            return

        self._calc_btn.config(state=tk.DISABLED)
        self._status_text.config(state=tk.NORMAL)
        self._status_text.delete("1.0", tk.END)
        self._status_text.config(state=tk.DISABLED)

        t = threading.Thread(target=self._run_calculation,
                             args=(odb_path, excel_path), daemon=True)
        t.start()

    def _run_calculation(self, odb_path: str, excel_path: str):
        try:
            # Use a cache directory next to the ODB file
            cache_dir = Path(odb_path).parent / ".copper_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)

            self._log("Loading ODB++ data...")
            data = load_odb_data(odb_path, cache_dir, log_fn=self._log)

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

            # Create images directory next to Excel output
            excel_dir = Path(excel_path).parent
            images_dir = excel_dir / "images"
            images_dir.mkdir(parents=True, exist_ok=True)

            layer_results = []
            for i, layer_name in enumerate(signal_layers):
                self._log(f"[{i + 1}/{len(signal_layers)}] Processing {layer_name}...")

                total_ratio = copper_utils.calculate_copper_ratio(
                    layer_name, profile, layers_data, user_symbols, font
                )
                self._log(f"  Copper ratio: {total_ratio * 100:.1f}%")

                sub_ratios = copper_utils.calculate_subsection_ratios(
                    layer_name, profile, layers_data, user_symbols, font
                )

                safe_name = (
                    layer_name
                    .replace("/", "_").replace("\\", "_").replace(":", "_")
                    .replace("[", "_").replace("]", "_").replace("*", "_")
                    .replace("?", "_")
                )
                img_path = images_dir / f"{safe_name}.png"
                copper_utils.save_layer_image(
                    layer_name, profile, layers_data, user_symbols, font,
                    sub_ratios, img_path
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
            generate_copper_report(layer_results, copper_data,
                                   all_matrix_layers, excel_path)

            self._log(f"Done! Report saved to: {excel_path}")

        except Exception as e:
            self._log(f"Error: {e}")
            self._log(traceback.format_exc())
            if self._root:
                self._root.after(0, lambda: self._calc_btn.config(state=tk.NORMAL))
            return

        # Re-enable button on success
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


def main():
    app = CopperCalculatorApp()
    app.run()


if __name__ == "__main__":
    main()
