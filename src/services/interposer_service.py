"""Interposer service: per-side interposer-area / PCB-area ratio + HTML report.

Interface-independent core of the "Interposer Analyzer" hub feature.  For each
side (top/bottom) it finds interposer components (``find_interposers`` — refdes
starting with INP/INT), computes the board (PCB) area and the summed interposer
footprint area, the ratio, renders a per-side overview image, and builds a
self-contained HTML report.

Interposer footprint area uses the package outline polygon (largest outline =
body/courtyard), falling back to the package bounding box.  Areas are summed per
side (interposers do not overlap or exceed the board — a stated assumption).

Headless matplotlib (Agg) is forced at import (server threads, no GUI).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")  # must precede any pyplot import in this process

import matplotlib.pyplot as plt

from src.checklist.component_classifier import find_interposers
from src.services import data_service

LogFn = Callable[[str], None]

_HIGHLIGHT = "#fa541c"


def _outline_area(outline) -> float:
    """Area (mm^2) of a single package outline in package-local space.

    Area is invariant under the placement transform (mirror/rotate/translate),
    so the local shape is sufficient.
    """
    p = outline.params or {}
    t = outline.type
    if t in ("CR", "CT"):
        r = p.get("radius", 0.0)
        return math.pi * r * r
    if t == "RC":
        return abs(p.get("width", 0.0) * p.get("height", 0.0))
    if t == "SQ":
        hs = p.get("half_side", 0.0)
        return (2 * hs) * (2 * hs)
    if t == "CONTOUR" and outline.contour is not None:
        from src.visualizer.symbol_renderer import contour_to_vertices
        verts = contour_to_vertices(outline.contour)
        if len(verts) >= 3:
            try:
                from shapely.geometry import Polygon as SPoly
                return abs(SPoly(verts).area)
            except Exception:
                return 0.0
    return 0.0


def _component_area(comp, pkg) -> float:
    """Interposer footprint area: largest package outline, else bbox area."""
    if pkg and getattr(pkg, "outlines", None):
        largest = max((_outline_area(o) for o in pkg.outlines), default=0.0)
        if largest > 0:
            return largest
    if pkg and getattr(pkg, "bbox", None):
        b = pkg.bbox
        return abs((b.xmax - b.xmin) * (b.ymax - b.ymin))
    return 0.0


def _pcb_area(profile) -> float:
    from src.visualizer import copper_vector
    poly = copper_vector._profile_to_poly(profile) if profile else None
    return float(poly.area) if poly is not None else 0.0


def _fill_counted_areas(ax, comps, packages, is_bottom: bool) -> None:
    """Shade the region that is actually summed into the interposer area — the
    largest package outline per interposer (matches ``_component_area``)."""
    from src.visualizer.component_overlay import _outline_to_patch

    pkg_lookup = {i: pkg for i, pkg in enumerate(packages)} if packages else {}
    for comp in comps:
        pkg = pkg_lookup.get(comp.pkg_ref)
        if not (pkg and getattr(pkg, "outlines", None)):
            continue
        largest = max(pkg.outlines, key=_outline_area, default=None)
        if largest is None or _outline_area(largest) <= 0:
            continue
        patch = _outline_to_patch(largest, comp, _HIGHLIGHT, 0.4,
                                  filled=True, is_bottom=is_bottom)
        if patch is not None:
            ax.add_patch(patch)


def _render_side(profile, comps, packages, user_symbols, side: str,
                 out_path: Path, title: str) -> None:
    from src.visualizer import copper_vector
    from src.visualizer.component_overlay import draw_components
    from src.visualizer.renderer import _draw_profile

    fig, ax = plt.subplots(figsize=(8, 8))
    try:
        if profile and profile.surface:
            _draw_profile(ax, profile, fill=False, outline_color="#888888")
        # Shade the counted area first so component outlines/labels stay on top.
        _fill_counted_areas(ax, comps, packages, is_bottom=(side == "B"))
        draw_components(
            ax, comps, packages,
            color=_HIGHLIGHT, alpha=0.9,
            show_labels=True, font_size=5,
            show_pads=False, show_pkg_outlines=True,
            user_symbols=user_symbols or {}, comp_side=side,
        )
        poly = copper_vector._profile_to_poly(profile) if profile else None
        if poly is not None:
            minx, miny, maxx, maxy = poly.bounds
            ax.set_xlim(minx, maxx)
            ax.set_ylim(miny, maxy)
        ax.set_aspect("equal")
        ax.set_title(f"{title} ({len(comps)} interposers)")
        ax.axis("off")
        fig.savefig(out_path, dpi=120, bbox_inches="tight")
    finally:
        plt.close(fig)


def run_interposer(cache_dir: str | Path, cache_name: str, *, out_dir: Path,
                   odb_filename: str, html_name: str = "interposer.html",
                   log: LogFn | None = None) -> dict:
    """Compute interposer ratios per side and write the HTML report.

    Returns ``{"report", "top": {...}, "bottom": {...}}`` where each side has
    ``pcb_area, interposer_area, ratio, count, items``.
    """
    _log = log if log is not None else (lambda m: None)

    data = data_service.load_job(cache_dir, cache_name, log=lambda m: None)
    profile = data.get("profile")
    eda = data.get("eda_data")
    packages = eda.packages if eda else None
    pkg_lookup = {i: pkg for i, pkg in enumerate(packages)} if packages else {}
    user_symbols = data.get("user_symbols", {})

    pcb_area = _pcb_area(profile)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sides: dict[str, dict] = {}
    for side_key, comps_key, side_char, title in (
        ("top", "components_top", "T", "TOP"),
        ("bottom", "components_bot", "B", "BOTTOM"),
    ):
        comps = find_interposers(data.get(comps_key, []))
        items = [
            {"refdes": c.comp_name, "area_mm2": round(_component_area(c, pkg_lookup.get(c.pkg_ref)), 4)}
            for c in comps
        ]
        interposer_area = sum(it["area_mm2"] for it in items)
        ratio = (interposer_area / pcb_area) if pcb_area > 0 else 0.0
        _log(f"{title}: {len(items)} interposers, area={interposer_area:.3f} / pcb={pcb_area:.3f} -> {ratio*100:.2f}%")

        png = out_dir / f"interposer_{side_key}.png"
        _render_side(profile, comps, packages, user_symbols, side_char, png, title)

        sides[side_key] = {
            "pcb_area": round(pcb_area, 4),
            "interposer_area": round(interposer_area, 4),
            "ratio": ratio,
            "count": len(items),
            "items": items,
            "_png": png,
        }

    from src.interposer_html_reporter import generate_interposer_html_report
    generate_interposer_html_report(out_dir / html_name, odb_filename=odb_filename, sides=sides)

    # Strip the internal PNG path from the returned summary.
    result = {"report": html_name}
    for k, v in sides.items():
        result[k] = {kk: vv for kk, vv in v.items() if kk != "_png"}
    return result
