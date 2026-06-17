"""Copper service: per-layer and per-subsection copper ratio + HTML report.

Interface-independent core of the "Copper Calculator" hub feature, extracted
from the calculation loop in ``CopperCalculateViewer``.  HTML-only (the Excel
``copper_reporter`` is kept dormant).

A headless matplotlib backend (Agg) is forced at import time because layer
images are rendered in background server threads with no GUI/Tk available.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")  # must precede any pyplot import in this process

from src.services import data_service

LogFn = Callable[[str], None]
ProgressFn = Callable[[float, str], None]

# Characters that are unsafe in image file names.
_UNSAFE = '/\\:[]*?'


def _safe_name(layer_name: str) -> str:
    out = layer_name
    for ch in _UNSAFE:
        out = out.replace(ch, "_")
    return out


def _load(cache_dir: str | Path, cache_name: str):
    """Load job data + copper thicknesses + ordered matrix layers (mirrors the
    old ``cmd_copper_calculate._load_data``)."""
    from src.cache_manager import load_cache, reconstruct_matrix_layers

    cache_dir = Path(cache_dir)
    data = data_service.load_job(cache_dir, cache_name, log=lambda m: None)

    copper_data: dict[str, float] = {}
    copper_file = cache_dir / cache_name / "copper_data.json"
    if copper_file.exists():
        copper_data = json.loads(copper_file.read_text(encoding="utf-8"))

    raw = load_cache(cache_dir, cache_name)
    matrix_layers = reconstruct_matrix_layers(raw.get("matrix_layers", []))
    matrix_layers_ordered = sorted(matrix_layers, key=lambda x: x.row)

    return data, copper_data, matrix_layers_ordered


def run_report(cache_dir: str | Path, cache_name: str, *, html_path: Path,
               images_dir: Path, odb_filename: str,
               n_rows: int = 5, n_cols: int = 5, method: str = "vector",
               log: LogFn | None = None,
               progress: ProgressFn | None = None) -> dict:
    """Compute copper ratios for all signal layers and write the HTML report.

    Returns a summary dict ``{"layers", "avg_ratio", "report"}``.
    """
    _log = log if log is not None else (lambda m: None)
    _progress = progress if progress is not None else (lambda f, m: None)
    from src.visualizer import copper_utils, copper_vector
    from src.copper_html_reporter import generate_copper_html_report

    data, copper_data, all_matrix_layers = _load(cache_dir, cache_name)
    profile = data.get("profile")
    layers_data = data.get("layers_data", {})
    user_symbols = data.get("user_symbols", {})
    font = data.get("font")

    signal_layers = [
        name for name, (_, ml) in sorted(layers_data.items(), key=lambda x: x[1][1].row)
        if ml.type == "SIGNAL"
    ]
    _log(f"{len(signal_layers)} signal layers ({method}, {n_rows}x{n_cols})")

    html_path = Path(html_path)
    images_dir = Path(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    use_vector = method == "vector"

    layer_results: list[dict] = []
    n_layers = len(signal_layers) or 1
    for i, layer_name in enumerate(signal_layers):
        _log(f"[{i + 1}/{len(signal_layers)}] {layer_name}")
        # Layer loop occupies 0–90%; report writing the final 10%.
        _progress(round((i / n_layers) * 0.9, 3),
                  f"{layer_name} ({i + 1}/{len(signal_layers)})")

        if use_vector:
            total_ratio = copper_vector.calculate_copper_ratio(
                layer_name, profile, layers_data, user_symbols, font,
            )
            sub_ratios = copper_vector.calculate_subsection_ratios(
                layer_name, profile, layers_data, user_symbols, font,
                n_rows=n_rows, n_cols=n_cols,
            )
        else:
            raster = copper_utils.rasterize_layer(
                layer_name, profile, layers_data, user_symbols, font,
            )
            total_ratio = copper_utils.calculate_copper_ratio(
                layer_name, profile, layers_data, user_symbols, font,
                raster_data=raster,
            )
            sub_ratios = copper_utils.calculate_subsection_ratios(
                layer_name, profile, layers_data, user_symbols, font,
                n_rows=n_rows, n_cols=n_cols, raster_data=raster,
            )

        img_path = images_dir / f"{_safe_name(layer_name)}.png"
        copper_utils.save_layer_image(
            layer_name, profile, layers_data, user_symbols, font,
            sub_ratios, img_path, n_rows=n_rows, n_cols=n_cols,
        )

        layer_results.append({
            "layer_name": layer_name,
            "total_ratio": total_ratio,
            "subsection_ratios": sub_ratios,
            "thickness_mm": copper_data.get(layer_name),
            # image path relative to the HTML report dir (reporter base64-embeds it)
            "image_path": img_path.relative_to(html_path.parent),
        })

    _log("Generating HTML report...")
    _progress(0.9, "generating report")
    generate_copper_html_report(
        layer_results, copper_data, all_matrix_layers,
        html_path, odb_filename=odb_filename,
    )

    ratios = [r["total_ratio"] for r in layer_results if r["total_ratio"] is not None]
    avg_ratio = sum(ratios) / len(ratios) if ratios else 0.0
    return {
        "layers": len(layer_results), 
        "avg_ratio": avg_ratio, 
        "report": html_path.name,
        "_layer_results:": layer_results,  #internal use for JSON export
    }

def batch_run_reports(cache_dir: str | Path, cache_names: list[str], output_dir: Path,
                      n_rows: int=5, n_cols: int=5, formats: list[str] | None = None,
                      log: LogFn | None=None,
                      progress: ProgressFn | None=None) -> dict:
    """Run copper ratio calculations for multiple cache entries and write reports.

    For each cache_name, runs run_report() and generates reports in specified formats.
    Individual HTML reports are writeen to output_dir/[COPPER]{cache_name}.html
    JSON reports (if requested) are writeen to output_dir/[COPPER]{cache_name}.json

    Returns:
        {
            'files_processed': int,
            'avg_ratio': float,
            'results': list[dict] # per-file details
        }
    """

    _log = log if log is not None else (lambda m: None)
    _progress = progress if progress is not None else (lambda f, m: None)

    if formats is None:
        formats = ["html"]

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    n_files = len(cache_names) or 1

    for i, cache_name in enumerate(cache_names):
        _progress(i / n_files, f"Processing {cache_name}...")
        _log(f"\n[{i + 1}/{len(cache_names)}] {cache_name}")

        # Per-file output paths
        html_path = output_dir / f"[COPPER]{cache_name}.html"
        images_dir = output_dir / f"images_{cache_name}"

        # Run existing run_report()
        summary = run_report(
            cache_dir=cache_dir,
            cache_name=cache_name,
            html_path=html_path,
            images_dir=images_dir,
            odb_filename=cache_name,
            n_rows=n_rows,
            n_cols=n_cols,
            method="vector",
            log=_log,
            progress=_progress
        )

        # Write JSON report if requested
        if "json" in formats:
            json_path = output_dir / f"[COPPER]{cache_name}.json"
            layer_results = summary.get('_layer_results', [])
            json_layers = [
                {"layer_name": lr["layer_name"], "ratio": lr["total_ratio"]}
                for lr in layer_results
            ]
            json_data = {
                "average_ratio": summary.get('avg_ratio', 0),
                "layers": json_layers,
            }
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, indent=2, ensure_ascii=False)
            _log(f"JSON report: {json_path}")

        results.append({
            'cache_name': cache_name,
            'layers': summary.get('layers', 0),
            'avg_ratio': summary.get('avg_ratio', 0),
            'report_path': str(html_path.relative_to(output_dir)),
        })

    avg_overall = sum(r['avg_ratio'] for r in results) / len(results) if results else 0.0

    _progress(1.0, "complete")

    return {
        'files_processed': len(results),
        'avg_ratio' : avg_overall,
        'results' : results,
    }
