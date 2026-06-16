"""Extract service: filter components by category and export JSON + images.

Interface-independent core of the "JSON Extractor" hub feature's part-extraction
side: given selected component categories, it writes a ``parts.json``, renders a
per-side overview image (board outline + highlighted parts), and builds a
self-contained HTML report (table + base64 images).

A headless matplotlib backend (Agg) is forced at import time (server threads,
no GUI).
"""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")  # must precede any pyplot import in this process

import matplotlib.pyplot as plt

from src.checklist.component_classifier import classify_component
from src.services import data_service

LogFn = Callable[[str], None]

_HIGHLIGHT = "#1677ff"


def _part_dict(comp, category: str, side: str) -> dict:
    props = comp.properties or {}
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


def _img_data_uri(path: Path) -> str:
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _write_html(html_path: Path, odb_filename: str, parts: list[dict],
                by_category: dict[str, int], top_png: Path, bot_png: Path) -> None:
    cat_summary = ", ".join(f"{k}: {v}" for k, v in sorted(by_category.items()))
    rows = "\n".join(
        "<tr>" + "".join(
            f"<td>{html.escape(str(p[c]))}</td>"
            for c in ("refdes", "part_name", "side", "category",
                      "x", "y", "rotation", "device_type")
        ) + "</tr>"
        for p in parts
    )
    doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>Extract — {html.escape(odb_filename)}</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 24px; color:#222; }}
 h1 {{ font-size: 1.3rem; }} .muted {{ color:#666; }}
 .imgs {{ display:flex; gap:16px; flex-wrap:wrap; margin:16px 0; }}
 .imgs figure {{ margin:0; }} .imgs img {{ max-width:480px; border:1px solid #eee; }}
 table {{ border-collapse: collapse; width:100%; font-size:0.85rem; }}
 th,td {{ border:1px solid #e5e5e5; padding:4px 8px; text-align:left; }}
 th {{ background:#fafafa; }}
</style></head><body>
<h1>Extract — {html.escape(odb_filename)}</h1>
<p class="muted">총 {len(parts)} parts &nbsp;|&nbsp; {html.escape(cat_summary)}</p>
<div class="imgs">
 <figure><figcaption>TOP</figcaption><img src="{_img_data_uri(top_png)}"></figure>
 <figure><figcaption>BOTTOM</figcaption><img src="{_img_data_uri(bot_png)}"></figure>
</div>
<table><thead><tr>
 <th>RefDes</th><th>Part</th><th>Side</th><th>Category</th>
 <th>X</th><th>Y</th><th>Rot</th><th>Device Type</th>
</tr></thead><tbody>
{rows}
</tbody></table>
</body></html>"""
    html_path.write_text(doc, encoding="utf-8")


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

    selected = set(categories) if categories else None

    def _filter(comps):
        kept = []
        for comp in comps:
            cat = classify_component(comp).value
            if selected is None or cat in selected:
                kept.append((comp, cat))
        return kept

    top = _filter(data.get("components_top", []))
    bot = _filter(data.get("components_bot", []))
    _log(f"selected {len(top)} top / {len(bot)} bot parts "
         f"(categories={sorted(selected) if selected else 'all'})")

    parts = (
        [_part_dict(c, cat, "top") for c, cat in top]
        + [_part_dict(c, cat, "bottom") for c, cat in bot]
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

    _write_html(out_dir / html_name, odb_filename, parts, by_category, top_png, bot_png)

    return {
        "count": len(parts),
        "by_category": by_category,
        "report": html_name,
        "json": json_name,
    }
