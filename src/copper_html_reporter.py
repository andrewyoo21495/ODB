"""Self-contained HTML report generator for copper ratio analysis."""

from __future__ import annotations

import base64
import html
import mimetypes
from datetime import datetime
from pathlib import Path

import numpy as np

from src.models import MatrixLayer


# ---------------------------------------------------------------------------
# CSS – embedded inline in the generated HTML
# ---------------------------------------------------------------------------

_CSS = """\
:root {
  --bg: #f8f9fa;
  --card-bg: #ffffff;
  --border: #dee2e6;
  --text: #212529;
  --muted: #6c757d;
  --primary: #0d6efd;
  --header-blue: #4472C4;
  --green: #198754;
  --green-bg: #C6EFCE;
  --yellow: #856404;
  --yellow-bg: #FFEB9C;
  --red: #dc3545;
  --red-bg: #FFC7CE;
  --grey-bg: #CCCCCC;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Malgun Gothic', 'Segoe UI', system-ui, -apple-system, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
  padding: 0 0 60px 0;
}

/* Header banner */
.header {
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
  color: #fff;
  padding: 44px 32px 36px;
  text-align: center;
}
.header h1 { font-size: 1.9rem; font-weight: 700; margin-bottom: 6px; }
.header-meta {
  font-size: 0.95rem; opacity: 0.8;
  display: flex; justify-content: center; gap: 28px; flex-wrap: wrap;
}

/* Stats bar */
.stats-bar {
  display: flex; justify-content: center; gap: 40px; padding: 20px 32px;
  background: #fff; border-bottom: 1px solid var(--border); flex-wrap: wrap;
}
.stat { text-align: center; }
.stat-value { font-size: 1.7rem; font-weight: 700; color: var(--primary); }
.stat-label { font-size: 0.8rem; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; }

/* Layout: sidebar + main */
.page-layout { display: flex; max-width: 1400px; margin: 0 auto; padding: 24px 20px; gap: 28px; }
.main-content { flex: 1; min-width: 0; }

/* ToC sidebar */
.toc-sidebar {
  width: 240px; flex-shrink: 0;
  position: sticky; top: 16px; align-self: flex-start;
  max-height: calc(100vh - 32px); overflow-y: auto;
  background: #fff; border: 1px solid var(--border); border-radius: 10px;
  padding: 18px 16px; font-size: 0.85rem;
}
.toc-sidebar h3 { font-size: 1rem; margin-bottom: 10px; }
.toc-sidebar ul { list-style: none; padding: 0; }
.toc-sidebar li { margin: 2px 0; }
.toc-sidebar a {
  color: var(--text); text-decoration: none;
  display: block; padding: 3px 6px; border-radius: 4px;
}
.toc-sidebar a:hover { background: #e9ecef; }
.toc-controls {
  display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px;
}
.toc-controls button {
  background: var(--header-blue); color: #fff; border: none; border-radius: 4px;
  padding: 3px 10px; font-size: 0.78rem; cursor: pointer;
}
.toc-controls button:hover { opacity: 0.85; }

/* Section titles */
section > h2 {
  font-size: 1.25rem; font-weight: 700; margin: 32px 0 14px;
  padding-bottom: 6px; border-bottom: 2px solid var(--header-blue);
}

/* Summary / data tables */
.data-table {
  width: 100%; border-collapse: collapse; background: #fff;
  border: 1px solid var(--border); font-size: 0.88rem;
  margin-bottom: 16px;
}
.data-table th {
  background: var(--header-blue); color: #fff; padding: 9px 10px; text-align: center;
  font-weight: 600; border: 1px solid #3a6ab5;
}
.data-table td { padding: 7px 10px; border: 1px solid var(--border); text-align: center; }

/* Layer sections */
.layer-section {
  background: #fff; border: 1px solid var(--border); border-radius: 10px;
  margin-bottom: 16px; overflow: hidden;
}
.layer-section-header {
  display: flex; align-items: center; gap: 10px; padding: 12px 18px;
  cursor: pointer; user-select: none; background: #fdfdfd; flex-wrap: wrap;
}
.layer-section-header:hover { background: #f1f3f5; }
.layer-name { font-weight: 700; font-size: 0.95rem; white-space: nowrap; }
.layer-ratio { font-size: 0.9rem; color: var(--muted); }
.ratio-badge {
  font-size: 0.75rem; font-weight: 700; padding: 3px 12px;
  border-radius: 4px; white-space: nowrap;
}
.ratio-high { background: var(--green-bg); color: var(--green); }
.ratio-mid  { background: var(--yellow-bg); color: var(--yellow); }
.ratio-low  { background: var(--red-bg); color: var(--red); }
.toggle-icon { font-size: 0.7rem; color: var(--muted); transition: transform 0.2s; margin-left: auto; }
.layer-section:not(.collapsed) .toggle-icon { transform: rotate(90deg); }
.layer-section.collapsed .layer-content { display: none; }
.layer-content { padding: 0 18px 18px; }

/* Sub-section grid */
.grid-table {
  border-collapse: collapse; font-size: 0.82rem; margin: 10px 0 14px;
}
.grid-table th {
  background: var(--header-blue); color: #fff; padding: 5px 10px;
  text-align: center; font-weight: 600; border: 1px solid #3a6ab5;
  min-width: 60px;
}
.grid-table td {
  padding: 5px 10px; border: 1px solid var(--border); text-align: center;
  min-width: 60px;
}
.cell-high { background: var(--green-bg); color: var(--green); font-weight: 600; }
.cell-mid  { background: var(--yellow-bg); color: var(--yellow); font-weight: 600; }
.cell-low  { background: var(--red-bg); color: var(--red); font-weight: 600; }
.cell-na   { background: var(--grey-bg); color: #666; }

/* Layer metadata */
.layer-meta { padding: 12px 0 8px; font-size: 0.88rem; }
.layer-meta p { margin: 3px 0; }

/* Images */
.image-block { margin: 10px 0 16px; }
.image-title {
  font-weight: 600; font-size: 0.9rem; padding: 6px 12px;
  background: #D9E1F2; border-radius: 4px 4px 0 0; margin-bottom: 0;
}
.image-block img { max-width: 100%; height: auto; border: 1px solid var(--border); display: block; }

/* Footer */
.footer { text-align: center; padding: 24px 16px; font-size: 0.82rem; color: var(--muted); }
.back-to-top { display: inline-block; margin-bottom: 8px; color: var(--primary); text-decoration: none; font-size: 0.9rem; }
.back-to-top:hover { text-decoration: underline; }

/* Responsive */
@media (max-width: 900px) {
  .page-layout { flex-direction: column; }
  .toc-sidebar { width: 100%; position: static; max-height: none; }
}

/* Print */
@media print {
  .toc-sidebar, .toc-controls, .toggle-icon, .back-to-top { display: none !important; }
  .layer-section.collapsed .layer-content { display: block !important; }
  .layer-section { break-inside: avoid; border: 1px solid #ccc; }
  .page-layout { display: block; }
  body { background: #fff; }
}
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_copper_html_report(
    layer_results: list[dict],
    copper_data: dict[str, float],
    all_matrix_layers: list[MatrixLayer],
    output_path: str | Path,
    odb_filename: str = "",
) -> None:
    """Generate a self-contained HTML report for copper ratio analysis.

    Args:
        layer_results: List of dicts per signal layer with keys:
            - layer_name, total_ratio, subsection_ratios, thickness_mm, image_path
        copper_data: dict[layer_name, thickness_mm] for all layers
        all_matrix_layers: list of MatrixLayer objects sorted by row
        output_path: Path to write the .html file
        odb_filename: Original ODB++ filename for display
    """
    output_path = Path(output_path)

    # Pre-encode images
    image_cache = _build_image_cache(layer_results, output_path.parent)

    display_name = odb_filename or "Copper Ratio Report"

    parts = [
        _build_doctype_and_head(display_name),
        _build_header_banner(display_name),
        _build_stats_bar(layer_results),
        '<div class="page-layout">',
        _build_table_of_contents(layer_results),
        '<div class="main-content">',
        _build_summary_table(layer_results),
        _build_thickness_table(copper_data, all_matrix_layers),
        *[_build_layer_section(r, image_cache) for r in layer_results],
        '</div>',   # close .main-content
        '</div>',   # close .page-layout
        _build_footer(),
        _build_script(),
        '</body></html>',
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(parts), encoding="utf-8")
    print(f"HTML copper report saved: {output_path}")


# ---------------------------------------------------------------------------
# Image cache
# ---------------------------------------------------------------------------

def _build_image_cache(
    layer_results: list[dict], report_dir: Path,
) -> dict[str, str]:
    """Read referenced image files and encode as base64 data URIs."""
    cache: dict[str, str] = {}
    for r in layer_results:
        img_path = r.get("image_path")
        if not img_path:
            continue
        p = Path(img_path)
        if not p.is_absolute():
            p = report_dir / p
        key = str(r["image_path"])
        if key in cache or not p.exists():
            continue
        mime = mimetypes.guess_type(str(p))[0] or "image/png"
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        cache[key] = f"data:{mime};base64,{b64}"
    return cache


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_doctype_and_head(title: str) -> str:
    safe_title = html.escape(title) if title else "Copper Ratio Report"
    return (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>Copper Ratio Report - {safe_title}</title>\n'
        f'<style>\n{_CSS}\n</style>\n'
        '</head>\n<body>'
    )


def _build_header_banner(display_name: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        '<div class="header">\n'
        '  <h1>Copper Ratio Analysis Report</h1>\n'
        '  <div class="header-meta">\n'
        f'    <span>Job: {html.escape(display_name)}</span>\n'
        f'    <span>Generated: {now}</span>\n'
        '  </div>\n'
        '</div>'
    )


def _ratio_badge_class(ratio: float | None) -> str:
    """Return CSS class for a copper ratio value."""
    if ratio is None:
        return "ratio-mid"
    if ratio > 0.5:
        return "ratio-high"
    if ratio >= 0.3:
        return "ratio-mid"
    return "ratio-low"


def _build_stats_bar(layer_results: list[dict]) -> str:
    total_layers = len(layer_results)
    ratios = [r["total_ratio"] for r in layer_results if r["total_ratio"] is not None]
    avg_ratio = sum(ratios) / len(ratios) if ratios else 0
    min_ratio = min(ratios) if ratios else 0
    max_ratio = max(ratios) if ratios else 0
    return (
        '<div class="stats-bar">\n'
        f'  <div class="stat"><div class="stat-value">{total_layers}</div>'
        '<div class="stat-label">Signal Layers</div></div>\n'
        f'  <div class="stat"><div class="stat-value">{avg_ratio:.1%}</div>'
        '<div class="stat-label">Avg Copper Ratio</div></div>\n'
        f'  <div class="stat"><div class="stat-value">{min_ratio:.1%}</div>'
        '<div class="stat-label">Min Ratio</div></div>\n'
        f'  <div class="stat"><div class="stat-value">{max_ratio:.1%}</div>'
        '<div class="stat-label">Max Ratio</div></div>\n'
        '</div>'
    )


def _build_table_of_contents(layer_results: list[dict]) -> str:
    lines = [
        '<nav class="toc-sidebar">',
        '<h3>Table of Contents</h3>',
        '<div class="toc-controls">',
        '  <button onclick="toggleAllSections(true)">Expand All</button>',
        '  <button onclick="toggleAllSections(false)">Collapse All</button>',
        '</div>',
        '<a href="#summary" style="display:block;margin-bottom:4px;">Copper Ratio Summary</a>',
        '<a href="#thickness" style="display:block;margin-bottom:8px;">Layer Thickness</a>',
        '<ul>',
    ]
    for r in layer_results:
        layer_name = r["layer_name"]
        anchor = _layer_anchor(layer_name)
        ratio = r["total_ratio"]
        ratio_str = f"{ratio:.1%}" if ratio is not None else "N/A"
        lines.append(
            f'<li><a href="#{anchor}">{html.escape(layer_name)} '
            f'({ratio_str})</a></li>'
        )
    lines.append('</ul></nav>')
    return "\n".join(lines)


def _layer_anchor(layer_name: str) -> str:
    """Create a safe HTML anchor id from a layer name."""
    return "layer-" + layer_name.replace(" ", "-").replace("/", "_")


def _build_summary_table(layer_results: list[dict]) -> str:
    lines = [
        '<section id="summary"><h2>Copper Ratio Summary</h2>',
        '<table class="data-table"><thead><tr>',
        '<th>Layer Name</th><th>Copper Ratio (%)</th><th>Thickness (mm)</th>',
        '</tr></thead><tbody>',
    ]
    for r in layer_results:
        ratio = r["total_ratio"]
        ratio_str = f"{ratio:.2%}" if ratio is not None else "N/A"
        thickness = r.get("thickness_mm")
        thickness_str = f"{thickness:.4f}" if thickness is not None else "N/A"
        anchor = _layer_anchor(r["layer_name"])
        lines.append(
            f'<tr>'
            f'<td style="text-align:left;"><a href="#{anchor}" style="color:var(--primary);text-decoration:none;">'
            f'{html.escape(r["layer_name"])}</a></td>'
            f'<td>{ratio_str}</td>'
            f'<td>{thickness_str}</td>'
            f'</tr>'
        )
    lines.append('</tbody></table></section>')
    return "\n".join(lines)


def _build_thickness_table(
    copper_data: dict[str, float],
    all_matrix_layers: list[MatrixLayer],
) -> str:
    lines = [
        '<section id="thickness"><h2>Layer Thickness Information</h2>',
        '<table class="data-table"><thead><tr>',
        '<th>Layer Name</th><th>Type</th><th>Thickness (mm)</th>',
        '</tr></thead><tbody>',
    ]
    total = 0.0
    for ml in all_matrix_layers:
        if ml.name not in copper_data:
            continue
        thickness = copper_data[ml.name]
        total += thickness
        lines.append(
            f'<tr>'
            f'<td style="text-align:left;">{html.escape(ml.name)}</td>'
            f'<td>{html.escape(ml.type)}</td>'
            f'<td>{thickness:.4f}</td>'
            f'</tr>'
        )
    lines.append(
        f'<tr style="font-weight:700;">'
        f'<td style="text-align:left;">TOTAL</td><td></td>'
        f'<td>{total:.4f}</td></tr>'
    )
    lines.append('</tbody></table></section>')
    return "\n".join(lines)


def _build_layer_section(result: dict, image_cache: dict[str, str]) -> str:
    layer_name = result["layer_name"]
    ratio = result["total_ratio"]
    anchor = _layer_anchor(layer_name)
    badge_cls = _ratio_badge_class(ratio)
    ratio_str = f"{ratio:.2%}" if ratio is not None else "N/A"

    lines = [
        f'<section id="{anchor}" class="layer-section collapsed">',
        '<div class="layer-section-header" '
        "onclick=\"this.parentElement.classList.toggle('collapsed')\">",
        f'  <span class="layer-name">{html.escape(layer_name)}</span>',
        f'  <span class="layer-ratio">Copper: {ratio_str}</span>',
        f'  <span class="ratio-badge {badge_cls}">{ratio_str}</span>',
        '  <span class="toggle-icon">&#9654;</span>',
        '</div>',
        '<div class="layer-content">',
    ]

    # Metadata
    lines.append('<div class="layer-meta">')
    lines.append(f'<p><strong>Layer:</strong> {html.escape(layer_name)}</p>')
    lines.append(f'<p><strong>Copper Ratio:</strong> {ratio_str}</p>')
    thickness = result.get("thickness_mm")
    if thickness is not None:
        lines.append(f'<p><strong>Thickness:</strong> {thickness:.4f} mm</p>')
    lines.append('</div>')

    # Sub-section grid
    sub_ratios = result.get("subsection_ratios")
    if sub_ratios is not None and isinstance(sub_ratios, np.ndarray):
        grid_rows, grid_cols = sub_ratios.shape
        lines.append(
            f'<p style="font-weight:600;margin:10px 0 4px;">'
            f'Sub-section Grid ({grid_rows}&times;{grid_cols}):</p>')
        lines.append('<table class="grid-table"><thead><tr><th></th>')
        for j in range(grid_cols):
            lines.append(f'<th>C{j + 1}</th>')
        lines.append('</tr></thead><tbody>')
        for i in range(grid_rows):
            lines.append(f'<tr><th>R{i + 1}</th>')
            for j in range(grid_cols):
                val = sub_ratios[i, j]
                if not np.isnan(val):
                    if val > 0.5:
                        cls = "cell-high"
                    elif val >= 0.3:
                        cls = "cell-mid"
                    else:
                        cls = "cell-low"
                    lines.append(f'<td class="{cls}">{val:.2%}</td>')
                else:
                    lines.append('<td class="cell-na">N/A</td>')
            lines.append('</tr>')
        lines.append('</tbody></table>')

    # Image
    img_key = str(result.get("image_path", ""))
    data_uri = image_cache.get(img_key)
    if data_uri:
        lines.append('<div class="image-block">')
        lines.append(
            f'<p class="image-title">{html.escape(layer_name)} Visualization</p>')
        lines.append(
            f'<img src="{data_uri}" alt="{html.escape(layer_name)}" '
            f'style="max-width:600px; width:100%;">')
        lines.append('</div>')

    lines.append('</div></section>')  # close .layer-content and .layer-section
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Footer & script
# ---------------------------------------------------------------------------

def _build_footer() -> str:
    return (
        '<footer class="footer">\n'
        '  <a href="#" class="back-to-top">&#8593; Back to Top</a>\n'
        '  <p>Generated by ODB++ Copper Ratio Analysis System</p>\n'
        '</footer>'
    )


def _build_script() -> str:
    return """\
<script>
function toggleAllSections(expand) {
  document.querySelectorAll('.layer-section').forEach(function(s) {
    if (expand) s.classList.remove('collapsed');
    else s.classList.add('collapsed');
  });
}
</script>"""
