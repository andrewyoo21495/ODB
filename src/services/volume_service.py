"""Volume service: per-side component volume (area x height) + HTML report.

Interface-independent core of the "Volume Analyzer" hub feature.  For each side
(top/bottom) it walks **every** placed component, computes its footprint area
(``component_area`` — the same largest-outline approach used by the Interposer
Analyzer) and its mean height, and multiplies them into a per-component volume.

Mean height comes from the component ``properties``: ``comp_height_max`` and
``comp_height_min`` (string values), averaged.  Components missing either value
are excluded from the volume sum and counted as ``missing_height`` (some ODB++
archives carry no height data at all).

Per side it renders a volume heat-map (each component shaded by its volume
magnitude) and reports the per-side total plus the combined grand total.

Headless matplotlib (Agg) is forced at import (server threads, no GUI).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")  # must precede any pyplot import in this process

import matplotlib.pyplot as plt

from src.services import data_service
from src.services.component_area import component_area, outline_area

LogFn = Callable[[str], None]

# Colormap for the volume heat-map; components with no height data are grey.
_CMAP_NAME = "YlOrRd"
_NO_HEIGHT = "#bbbbbb"


def _mean_height(comp) -> float | None:
    """Mean component height (mm) from properties, or None if data is absent.

    ``comp_height_max`` / ``comp_height_min`` are stored as strings (when
    present at all).  Returns None when either value is missing or unparseable.
    """
    props = getattr(comp, "properties", None) or {}
    raw_max = props.get("comp_height_max")
    raw_min = props.get("comp_height_min")
    if raw_max is None or raw_min is None:
        return None
    try:
        h_max = float(raw_max)
        h_min = float(raw_min)
    except (TypeError, ValueError):
        return None
    return (h_max + h_min) / 2.0


def _side_items(comps, pkg_lookup) -> list[dict]:
    """Per-component volume rows for one side."""
    items: list[dict] = []
    for c in comps:
        area = component_area(c, pkg_lookup.get(c.pkg_ref))
        h_mean = _mean_height(c)
        volume = (area * h_mean) if h_mean is not None else None
        items.append({
            "refdes": c.comp_name,
            "area_mm2": round(area, 4),
            "height_mean_mm": (round(h_mean, 4) if h_mean is not None else None),
            "volume_mm3": (round(volume, 4) if volume is not None else None),
        })
    return items


def _render_side(profile, comps, packages, side: str, items: list[dict],
                 out_path: Path, title: str) -> None:
    """Volume heat-map: shade each component's largest outline by its volume."""
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import Normalize, to_hex
    from src.visualizer import copper_vector
    from src.visualizer.component_overlay import _outline_to_patch
    from src.visualizer.renderer import _draw_profile

    pkg_lookup = {i: pkg for i, pkg in enumerate(packages)} if packages else {}
    vol_by_refdes = {it["refdes"]: it["volume_mm3"] for it in items}
    volumes = [v for v in vol_by_refdes.values() if v is not None and v > 0]
    vmax = max(volumes) if volumes else 1.0
    vmin = min(volumes) if volumes else 0.0
    norm = Normalize(vmin=vmin, vmax=vmax)
    cmap = plt.get_cmap(_CMAP_NAME)
    is_bottom = (side == "B")

    fig, ax = plt.subplots(figsize=(8, 8))
    try:
        if profile and profile.surface:
            _draw_profile(ax, profile, fill=False, outline_color="#888888")

        for comp in comps:
            pkg = pkg_lookup.get(comp.pkg_ref)
            if not (pkg and getattr(pkg, "outlines", None)):
                continue
            largest = max(pkg.outlines, key=outline_area, default=None)
            if largest is None or outline_area(largest) <= 0:
                continue
            vol = vol_by_refdes.get(comp.comp_name)
            color = _NO_HEIGHT if not vol else to_hex(cmap(norm(vol)))
            patch = _outline_to_patch(largest, comp, color, 0.85,
                                      filled=True, is_bottom=is_bottom)
            if patch is not None:
                ax.add_patch(patch)

        poly = copper_vector._profile_to_poly(profile) if profile else None
        if poly is not None:
            minx, miny, maxx, maxy = poly.bounds
            ax.set_xlim(minx, maxx)
            ax.set_ylim(miny, maxy)
        ax.set_aspect("equal")
        ax.set_title(f"{title} ({len(comps)} components)")
        ax.axis("off")

        if volumes:
            sm = ScalarMappable(norm=norm, cmap=cmap)
            sm.set_array([])
            cbar = fig.colorbar(sm, ax=ax, fraction=0.046, pad=0.04)
            cbar.set_label("Volume (mm³)")

        fig.savefig(out_path, dpi=120, bbox_inches="tight")
    finally:
        plt.close(fig)


def run_volume(cache_dir: str | Path, cache_name: str, *, out_dir: Path,
               odb_filename: str, html_name: str = "volume.html",
               log: LogFn | None = None) -> dict:
    """Compute per-side component volumes and write the HTML report.

    Returns ``{"report", "grand_total_mm3", "top": {...}, "bottom": {...}}``
    where each side has ``count, total_volume_mm3, missing_height, items``.
    """
    _log = log if log is not None else (lambda m: None)

    data = data_service.load_job(cache_dir, cache_name, log=lambda m: None)
    profile = data.get("profile")
    eda = data.get("eda_data")
    packages = eda.packages if eda else None
    pkg_lookup = {i: pkg for i, pkg in enumerate(packages)} if packages else {}

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sides: dict[str, dict] = {}
    for side_key, comps_key, side_char, title in (
        ("top", "components_top", "T", "TOP"),
        ("bottom", "components_bot", "B", "BOTTOM"),
    ):
        comps = data.get(comps_key, [])
        items = _side_items(comps, pkg_lookup)
        total_volume = sum(it["volume_mm3"] for it in items
                           if it["volume_mm3"] is not None)
        missing = sum(1 for it in items if it["volume_mm3"] is None)
        _log(f"{title}: {len(items)} components, volume={total_volume:.3f} mm^3, "
             f"{missing} missing height")

        png = out_dir / f"volume_{side_key}.png"
        _render_side(profile, comps, packages, side_char, items, png, title)

        sides[side_key] = {
            "count": len(items),
            "total_volume_mm3": round(total_volume, 4),
            "missing_height": missing,
            "items": items,
            "_png": png,
        }

    grand_total = round(
        sides["top"]["total_volume_mm3"] + sides["bottom"]["total_volume_mm3"], 4)

    from src.volume_html_reporter import generate_volume_html_report
    generate_volume_html_report(out_dir / html_name, odb_filename=odb_filename,
                                sides=sides, grand_total=grand_total)

    result = {"report": html_name, "grand_total_mm3": grand_total}
    for k, v in sides.items():
        result[k] = {kk: vv for kk, vv in v.items() if kk != "_png"}
    return result
