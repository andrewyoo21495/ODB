"""Self-contained HTML report generator for interposer-area analysis.

Mirrors the look of the copper / checklist reports (shared CSS, gradient header
banner, stats bar, summary table, collapsible per-side sections) so all hub
reports share one consistent UI.
"""

from __future__ import annotations

import base64
import html
import mimetypes
from datetime import datetime
from pathlib import Path

# Reuse the copper report stylesheet verbatim for a consistent look across
# every hub report.
from src.copper_html_reporter import _CSS

# Neutral badge style — interposer ratio is an area fraction, so the copper
# traffic-light (green/yellow/red) thresholds do not apply here.
_BADGE_STYLE = "background:#D9E1F2;color:#2a4d8f;"


def _img_data_uri(path: Path) -> str:
    p = Path(path)
    mime = mimetypes.guess_type(str(p))[0] or "image/png"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def generate_interposer_html_report(
    output_path: str | Path, *, odb_filename: str, sides: dict,
) -> None:
    """Write the interposer HTML report.

    Args:
        output_path: destination ``.html`` path.
        odb_filename: original ODB++ filename for display.
        sides: ``{"top": {...}, "bottom": {...}}`` where each side has
            ``pcb_area, interposer_area, ratio, count, items, _png``.
    """
    output_path = Path(output_path)
    display_name = odb_filename or "Interposer Report"

    parts = [
        _build_head(display_name),
        _build_header_banner(display_name),
        _build_stats_bar(sides),
        '<div class="page-layout">',
        '<div class="main-content" style="margin:0 auto;">',
        _build_summary_table(sides),
        _build_side_section("TOP", sides.get("top")),
        _build_side_section("BOTTOM", sides.get("bottom")),
        '</div>',   # .main-content
        '</div>',   # .page-layout
        _build_footer(),
        _build_script(),
        '</body></html>',
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(parts), encoding="utf-8")
    print(f"HTML interposer report saved: {output_path}")


def _build_head(title: str) -> str:
    safe_title = html.escape(title)
    return (
        '<!DOCTYPE html>\n'
        '<html lang="ko">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>Interposer Report - {safe_title}</title>\n'
        f'<style>\n{_CSS}\n</style>\n'
        '</head>\n<body>'
    )


def _build_header_banner(display_name: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        '<div class="header">\n'
        '  <h1>Interposer Analysis Report</h1>\n'
        '  <div class="header-meta">\n'
        f'    <span>Job: {html.escape(display_name)}</span>\n'
        f'    <span>Generated: {now}</span>\n'
        '  </div>\n'
        '</div>'
    )


def _build_stats_bar(sides: dict) -> str:
    top = sides.get("top") or {}
    bot = sides.get("bottom") or {}
    return (
        '<div class="stats-bar">\n'
        f'  <div class="stat"><div class="stat-value">{top.get("ratio", 0) * 100:.2f}%</div>'
        '<div class="stat-label">TOP Ratio</div></div>\n'
        f'  <div class="stat"><div class="stat-value">{bot.get("ratio", 0) * 100:.2f}%</div>'
        '<div class="stat-label">BOTTOM Ratio</div></div>\n'
        f'  <div class="stat"><div class="stat-value">{top.get("count", 0)}</div>'
        '<div class="stat-label">TOP Count</div></div>\n'
        f'  <div class="stat"><div class="stat-value">{bot.get("count", 0)}</div>'
        '<div class="stat-label">BOTTOM Count</div></div>\n'
        '</div>'
    )


def _build_summary_table(sides: dict) -> str:
    lines = [
        '<section id="summary"><h2>Interposer Area Summary</h2>',
        '<table class="data-table"><thead><tr>',
        '<th>Side</th><th>PCB Area (mm&sup2;)</th><th>Interposer Area (mm&sup2;)</th>',
        '<th>Ratio</th><th>Count</th>',
        '</tr></thead><tbody>',
    ]
    for label, key in (("TOP", "top"), ("BOTTOM", "bottom")):
        s = sides.get(key) or {}
        lines.append(
            '<tr>'
            f'<td style="text-align:left;font-weight:600;">{label}</td>'
            f'<td>{s.get("pcb_area", 0):.3f}</td>'
            f'<td>{s.get("interposer_area", 0):.3f}</td>'
            f'<td>{s.get("ratio", 0) * 100:.2f}%</td>'
            f'<td>{s.get("count", 0)}</td>'
            '</tr>'
        )
    lines.append('</tbody></table></section>')
    return "\n".join(lines)


def _build_side_section(label: str, side: dict | None) -> str:
    side = side or {}
    anchor = f"side-{label.lower()}"
    ratio_str = f"{side.get('ratio', 0) * 100:.2f}%"
    items = side.get("items", [])

    lines = [
        f'<section id="{anchor}" class="layer-section">',
        '<div class="layer-section-header" '
        "onclick=\"this.parentElement.classList.toggle('collapsed')\">",
        f'  <span class="layer-name">{html.escape(label)}</span>',
        f'  <span class="layer-ratio">Interposer / PCB: {ratio_str}</span>',
        f'  <span class="ratio-badge" style="{_BADGE_STYLE}">{ratio_str}</span>',
        '  <span class="toggle-icon">&#9654;</span>',
        '</div>',
        '<div class="layer-content">',
        '<div class="layer-meta">',
        f'<p><strong>PCB Area:</strong> {side.get("pcb_area", 0):.3f} mm&sup2;</p>',
        f'<p><strong>Interposer Area:</strong> {side.get("interposer_area", 0):.3f} mm&sup2;</p>',
        f'<p><strong>Ratio:</strong> {ratio_str}</p>',
        f'<p><strong>Count:</strong> {side.get("count", 0)}</p>',
        '</div>',
    ]

    png = side.get("_png")
    if png and Path(png).exists():
        lines.append('<div class="image-block">')
        lines.append(f'<p class="image-title">{html.escape(label)} Visualization</p>')
        lines.append(
            f'<img src="{_img_data_uri(png)}" alt="{html.escape(label)}" '
            'style="max-width:600px; width:100%;">')
        lines.append('</div>')

    # Items table
    rows = "\n".join(
        '<tr>'
        f'<td style="text-align:left;">{html.escape(it.get("refdes") or "")}</td>'
        f'<td>{it.get("area_mm2", 0):.4f}</td>'
        '</tr>'
        for it in items
    ) or '<tr><td colspan="2" style="color:#888;">(none)</td></tr>'
    lines.append(
        '<table class="data-table" style="max-width:420px;">'
        '<thead><tr><th>RefDes</th><th>Area (mm&sup2;)</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )

    lines.append('</div></section>')
    return "\n".join(lines)


def _build_footer() -> str:
    return (
        '<footer class="footer">\n'
        '  <a href="#" class="back-to-top">&#8593; Back to Top</a>\n'
        '  <p>Generated by ODB++ Interposer Analysis System</p>\n'
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
