"""Self-contained HTML report generator for component-volume analysis.

Mirrors the look of the copper / checklist / interposer reports (shared CSS,
gradient header banner, stats bar, summary table, collapsible per-side
sections) so all hub reports share one consistent UI.
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

# Neutral badge style — volume is an absolute quantity, so the copper
# traffic-light (green/yellow/red) thresholds do not apply here.
_BADGE_STYLE = "background:#D9E1F2;color:#2a4d8f;"


def _img_data_uri(path: Path) -> str:
    p = Path(path)
    mime = mimetypes.guess_type(str(p))[0] or "image/png"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def generate_volume_html_report(
    output_path: str | Path, *, odb_filename: str, sides: dict,
    grand_total: float,
) -> None:
    """Write the component-volume HTML report.

    Args:
        output_path: destination ``.html`` path.
        odb_filename: original ODB++ filename for display.
        sides: ``{"top": {...}, "bottom": {...}}`` where each side has
            ``count, total_volume_mm3, missing_height, items, _png``.
        grand_total: combined TOP + BOTTOM volume (mm^3).
    """
    output_path = Path(output_path)
    display_name = odb_filename or "Volume Report"

    parts = [
        _build_head(display_name),
        _build_header_banner(display_name),
        _build_stats_bar(sides, grand_total),
        '<div class="page-layout">',
        '<div class="main-content" style="margin:0 auto;">',
        _build_summary_table(sides, grand_total),
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
    print(f"HTML volume report saved: {output_path}")


def _build_head(title: str) -> str:
    safe_title = html.escape(title)
    return (
        '<!DOCTYPE html>\n'
        '<html lang="ko">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>Volume Report - {safe_title}</title>\n'
        f'<style>\n{_CSS}\n</style>\n'
        '</head>\n<body>'
    )


def _build_header_banner(display_name: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        '<div class="header">\n'
        '  <h1>Component Volume Analysis Report</h1>\n'
        '  <div class="header-meta">\n'
        f'    <span>Job: {html.escape(display_name)}</span>\n'
        f'    <span>Generated: {now}</span>\n'
        '  </div>\n'
        '</div>'
    )


def _build_stats_bar(sides: dict, grand_total: float) -> str:
    top = sides.get("top") or {}
    bot = sides.get("bottom") or {}
    total_count = top.get("count", 0) + bot.get("count", 0)
    return (
        '<div class="stats-bar">\n'
        f'  <div class="stat"><div class="stat-value">{grand_total:.2f}</div>'
        '<div class="stat-label">Total Volume (mm³)</div></div>\n'
        f'  <div class="stat"><div class="stat-value">{top.get("total_volume_mm3", 0):.2f}</div>'
        '<div class="stat-label">TOP Volume (mm³)</div></div>\n'
        f'  <div class="stat"><div class="stat-value">{bot.get("total_volume_mm3", 0):.2f}</div>'
        '<div class="stat-label">BOTTOM Volume (mm³)</div></div>\n'
        f'  <div class="stat"><div class="stat-value">{total_count}</div>'
        '<div class="stat-label">Total Components</div></div>\n'
        '</div>'
    )


def _build_summary_table(sides: dict, grand_total: float) -> str:
    lines = [
        '<section id="summary"><h2>Volume Summary</h2>',
        '<table class="data-table"><thead><tr>',
        '<th>Side</th><th>Components</th><th>Total Volume (mm&sup3;)</th>',
        '<th>Height Missing</th>',
        '</tr></thead><tbody>',
    ]
    for label, key in (("TOP", "top"), ("BOTTOM", "bottom")):
        s = sides.get(key) or {}
        lines.append(
            '<tr>'
            f'<td style="text-align:left;font-weight:600;">{label}</td>'
            f'<td>{s.get("count", 0)}</td>'
            f'<td>{s.get("total_volume_mm3", 0):.3f}</td>'
            f'<td>{s.get("missing_height", 0)}</td>'
            '</tr>'
        )
    lines.append(
        '<tr style="font-weight:700;background:#f0f4fb;">'
        '<td style="text-align:left;">TOTAL</td>'
        f'<td>{(sides.get("top") or {}).get("count", 0) + (sides.get("bottom") or {}).get("count", 0)}</td>'
        f'<td>{grand_total:.3f}</td>'
        '<td>&mdash;</td></tr>'
    )
    lines.append('</tbody></table></section>')
    return "\n".join(lines)


def _build_side_section(label: str, side: dict | None) -> str:
    side = side or {}
    anchor = f"side-{label.lower()}"
    total_str = f"{side.get('total_volume_mm3', 0):.3f} mm³"
    items = side.get("items", [])
    missing = side.get("missing_height", 0)

    lines = [
        f'<section id="{anchor}" class="layer-section">',
        '<div class="layer-section-header" '
        "onclick=\"this.parentElement.classList.toggle('collapsed')\">",
        f'  <span class="layer-name">{html.escape(label)}</span>',
        f'  <span class="layer-ratio">Total Volume: {total_str}</span>',
        f'  <span class="ratio-badge" style="{_BADGE_STYLE}">{side.get("count", 0)} comps</span>',
        '  <span class="toggle-icon">&#9654;</span>',
        '</div>',
        '<div class="layer-content">',
        '<div class="layer-meta">',
        f'<p><strong>Components:</strong> {side.get("count", 0)}</p>',
        f'<p><strong>Total Volume:</strong> {side.get("total_volume_mm3", 0):.3f} mm&sup3;</p>',
        f'<p><strong>Height Missing:</strong> {missing}</p>',
        '</div>',
    ]

    png = side.get("_png")
    if png and Path(png).exists():
        lines.append('<div class="image-block">')
        lines.append(f'<p class="image-title">{html.escape(label)} Volume Heat-map</p>')
        lines.append(
            f'<img src="{_img_data_uri(png)}" alt="{html.escape(label)}" '
            'style="max-width:600px; width:100%;">')
        lines.append('</div>')

    # Items table — sorted by volume desc (height-missing rows sink to bottom).
    def _sort_key(it: dict):
        v = it.get("volume_mm3")
        return (0, -v) if v is not None else (1, 0.0)

    rows = "\n".join(
        '<tr>'
        f'<td style="text-align:left;">{html.escape(it.get("refdes") or "")}</td>'
        f'<td>{it.get("area_mm2", 0):.4f}</td>'
        f'<td>{_fmt(it.get("height_mean_mm"))}</td>'
        f'<td>{_fmt(it.get("volume_mm3"))}</td>'
        '</tr>'
        for it in sorted(items, key=_sort_key)
    ) or '<tr><td colspan="4" style="color:#888;">(none)</td></tr>'
    lines.append(
        '<table class="data-table" style="max-width:560px;">'
        '<thead><tr><th>RefDes</th><th>Area (mm&sup2;)</th>'
        '<th>Mean Height (mm)</th><th>Volume (mm&sup3;)</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )

    lines.append('</div></section>')
    return "\n".join(lines)


def _fmt(v: float | None) -> str:
    return f"{v:.4f}" if v is not None else '<span style="color:#c0392b;">N/A</span>'


def _build_footer() -> str:
    return (
        '<footer class="footer">\n'
        '  <a href="#" class="back-to-top">&#8593; Back to Top</a>\n'
        '  <p>Generated by ODB++ Component Volume Analysis System</p>\n'
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
