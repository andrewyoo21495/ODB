"""Extract service: filter components by category and export JSON + images.

Interface-independent core of the "JSON Extractor" hub feature's part-extraction
side: given selected component categories, it writes a ``parts.json``, renders a
per-side overview image (board outline + highlighted parts), and builds a
self-contained HTML report (table + base64 images).

A headless matplotlib backend (Agg) is forced at import time (server threads,
no GUI).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")  # must precede any pyplot import in this process

import matplotlib.pyplot as plt

from src.checklist.component_classifier import ComponentCategory, classify_component
from src.extract_html_reporter import generate_extract_html_report
from src.services import data_service

LogFn = Callable[[str], None]

_HIGHLIGHT = "#1677ff"

# "Unknown" is never a selectable/extractable category — only the categories
# component_classifier confidently identifies are exported (see hub Extract tab).
_UNKNOWN = ComponentCategory.UNKNOWN.value


def _pin_dict(tp, net_names: list[str]) -> dict:
    """One pin/pad record from a component toeprint.

    ``net_names`` is positional (``net_num`` indexes ``eda.nets``); ``pad`` is the
    FID-resolved pad symbol name when available.
    """
    net = net_names[tp.net_num] if 0 <= tp.net_num < len(net_names) else ""
    return {
        "pin_num": tp.pin_num,
        "name": tp.name,
        "net": net,
        "pad": tp.geom.symbol_name if tp.geom else "",
        "x": round(tp.x, 4),
        "y": round(tp.y, 4),
        "rotation": tp.rotation,
        "mirror": tp.mirror,
    }


def _part_dict(comp, category: str, side: str, net_names: list[str]) -> dict:
    props = comp.properties or {}
    pins = [_pin_dict(tp, net_names) for tp in (comp.toeprints or [])]
    return {
        "refdes": comp.comp_name,
        "part_name": comp.part_name,
        "side": side,
        "category": category,
        "x": round(comp.x, 4),
        "y": round(comp.y, 4),
        "rotation": comp.rotation,
        "mirror": comp.mirror,
        "device_type": props.get("DEVICE_TYPE", ""),
        "type": props.get("TYPE", ""),
        "pin_count": len(pins),
        "pins": pins,
        "properties": dict(props),
    }


def _render_side(profile, comps, packages, user_symbols, side: str,
                 out_path: Path, title: str) -> None:
    from src.visualizer import copper_vector
    from src.visualizer.component_overlay import draw_components
    from src.visualizer.renderer import _draw_profile

    fig, ax = plt.subplots(figsize=(8, 8))
    try:
        if profile and profile.surface:
            _draw_profile(ax, profile, fill=False, outline_color="#888888")
        draw_components(
            ax, comps, packages,
            color=_HIGHLIGHT, alpha=0.6,
            show_labels=True, font_size=4,
            show_pads=True, show_pkg_outlines=True,
            user_symbols=user_symbols or {}, comp_side=side,
        )
        # Fit view to the board outline when available.
        poly = copper_vector._profile_to_poly(profile) if profile else None
        if poly is not None:
            minx, miny, maxx, maxy = poly.bounds
            ax.set_xlim(minx, maxx)
            ax.set_ylim(miny, maxy)
        ax.set_aspect("equal")
        ax.set_title(f"{title} ({len(comps)} parts)")
        ax.axis("off")
        fig.savefig(out_path, dpi=120, bbox_inches="tight")
    finally:
        plt.close(fig)


def run_extract(cache_dir: str | Path, cache_name: str, *, out_dir: Path,
                odb_filename: str, categories: list[str] | None = None,
                html_name: str = "extract.html", json_name: str = "parts.json",
                log: LogFn | None = None) -> dict:
    """Filter components by category, write JSON + per-side images + HTML report.

    Returns ``{"count", "by_category", "report", "json"}``.
    """
    _log = log if log is not None else (lambda m: None)

    data = data_service.load_job(cache_dir, cache_name, log=lambda m: None)
    profile = data.get("profile")
    eda = data.get("eda_data")
    packages = eda.packages if eda else None
    user_symbols = data.get("user_symbols", {})
    # net_num on a toeprint is a positional index into eda.nets.
    net_names = [n.name for n in eda.nets] if eda else []

    # Drop "Unknown" from any explicit selection; when nothing is selected
    # ("전체"), keep every confidently-classified category but still exclude
    # Unknown (it is never an extractable category).
    selected = {c for c in categories if c != _UNKNOWN} if categories else None

    def _filter(comps):
        kept = []
        for comp in comps:
            cat = classify_component(comp).value
            if cat == _UNKNOWN:
                continue
            if selected is None or cat in selected:
                kept.append((comp, cat))
        return kept

    top = _filter(data.get("components_top", []))
    bot = _filter(data.get("components_bot", []))
    _log(f"selected {len(top)} top / {len(bot)} bot parts "
         f"(categories={sorted(selected) if selected else 'all'})")

    parts = (
        [_part_dict(c, cat, "top", net_names) for c, cat in top]
        + [_part_dict(c, cat, "bottom", net_names) for c, cat in bot]
    )

    by_category: dict[str, int] = {}
    for p in parts:
        by_category[p["category"]] = by_category.get(p["category"], 0) + 1

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / json_name).write_text(
        json.dumps(parts, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    top_png = out_dir / "extract_top.png"
    bot_png = out_dir / "extract_bottom.png"
    _render_side(profile, [c for c, _ in top], packages, user_symbols, "T", top_png, "TOP")
    _render_side(profile, [c for c, _ in bot], packages, user_symbols, "B", bot_png, "BOTTOM")

    generate_extract_html_report(
        out_dir / html_name,
        odb_filename=odb_filename,
        parts=parts,
        by_category=by_category,
        top_png=top_png,
        bot_png=bot_png,
    )

    return {
        "count": len(parts),
        "by_category": by_category,
        "report": html_name,
        "json": json_name,
    }
