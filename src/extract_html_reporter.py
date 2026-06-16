"""Self-contained HTML report generator for the parts-extraction feature.

Mirrors the look of the copper / checklist / interposer reports by reusing the
shared CSS from :mod:`src.copper_html_reporter` (gradient header banner +
stats-bar + summary data-table + collapsible TOP/BOTTOM sections).
"""

from __future__ import annotations

import base64
import html
import mimetypes
from datetime import datetime
from pathlib import Path

from src.copper_html_reporter import _CSS

# Columns shown in the per-side parts table (key -> header label).
_TABLE_COLUMNS: list[tuple[str, str]] = [
    ("refdes", "RefDes"),
    ("part_name", "Part"),
    ("category", "Category"),
    ("x", "X"),
    ("y", "Y"),
    ("rotation", "Rot"),
    ("mirror", "Mirror"),
    ("device_type", "Device Type"),
    ("type", "Type"),
]


def generate_extract_html_report(
    output_path: str | Path,
    *,
    odb_filename: str,
    parts: list[dict],
    by_category: dict[str, int],
    top_png: Path | None,
    bot_png: Path | None,
) -> None:
    """Write a self-contained extraction report to *output_path*.

    Args:
        output_path: target ``.html`` path.
        odb_filename: original ODB++ filename for display.
        parts: list of part dicts (see ``extract_service._part_dict``).
        by_category: category -> count summary.
        top_png / bot_png: per-side overview images (embedded as base64).
    """
    output_path = Path(output_path)
    display_name = odb_filename or "Parts Extraction Report"

    top_parts = [p for p in parts if p.get("side") == "top"]
    bot_parts = [p for p in parts if p.get("side") == "bottom"]

    parts_doc = [
        _build_head(display_name),
        _build_header_banner(display_name),
        _build_stats_bar(parts, top_parts, bot_parts, by_category),
        '<div class="page-layout"><div class="main-content">',
        _build_summary_table(by_category, len(parts)),
        _build_side_section("TOP", top_parts, top_png),
        _build_side_section("BOTTOM", bot_parts, bot_png),
        '</div></div>',
        _build_footer(),
        _build_script(),
        '</body></html>',
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(parts_doc), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Section builders
# --------------------------------------------------------------------------- #
def _build_head(title: str) -> str:
    safe = html.escape(title)
    return (
        '<!DOCTYPE html>\n<html lang="ko">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>Parts Extraction Report - {safe}</title>\n'
        f'<style>\n{_CSS}\n</style>\n</head>\n<body>'
    )


def _build_header_banner(display_name: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        '<div class="header">\n'
        '  <h1>Parts Extraction Report</h1>\n'
        '  <div class="header-meta">\n'
        f'    <span>Job: {html.escape(display_name)}</span>\n'
        f'    <span>Generated: {now}</span>\n'
        '  </div>\n</div>'
    )


def _build_stats_bar(parts: list[dict], top_parts: list[dict],
                     bot_parts: list[dict], by_category: dict[str, int]) -> str:
    return (
        '<div class="stats-bar">\n'
        f'  <div class="stat"><div class="stat-value">{len(parts)}</div>'
        '<div class="stat-label">Total Parts</div></div>\n'
        f'  <div class="stat"><div class="stat-value">{len(top_parts)}</div>'
        '<div class="stat-label">Top</div></div>\n'
        f'  <div class="stat"><div class="stat-value">{len(bot_parts)}</div>'
        '<div class="stat-label">Bottom</div></div>\n'
        f'  <div class="stat"><div class="stat-value">{len(by_category)}</div>'
        '<div class="stat-label">Categories</div></div>\n'
        '</div>'
    )


def _build_summary_table(by_category: dict[str, int], total: int) -> str:
    lines = [
        '<section id="summary"><h2>Category Summary</h2>',
        '<table class="data-table"><thead><tr>',
        '<th>Category</th><th>Count</th>',
        '</tr></thead><tbody>',
    ]
    for cat, n in sorted(by_category.items()):
        lines.append(
            f'<tr><td style="text-align:left;">{html.escape(str(cat))}</td>'
            f'<td>{n}</td></tr>'
        )
    lines.append(
        f'<tr style="font-weight:700;"><td style="text-align:left;">TOTAL</td>'
        f'<td>{total}</td></tr>'
    )
    lines.append('</tbody></table></section>')
    return "\n".join(lines)


def _build_side_section(side: str, parts: list[dict], png: Path | None) -> str:
    anchor = f"side-{side.lower()}"
    lines = [
        f'<section id="{anchor}" class="layer-section">',
        '<div class="layer-section-header" '
        "onclick=\"this.parentElement.classList.toggle('collapsed')\">",
        f'  <span class="layer-name">{html.escape(side)}</span>',
        f'  <span class="layer-ratio">{len(parts)} parts</span>',
        '  <span class="toggle-icon">&#9654;</span>',
        '</div>',
        '<div class="layer-content">',
    ]

    data_uri = _img_data_uri(png) if png else None
    if data_uri:
        lines.append('<div class="image-block">')
        lines.append(f'<p class="image-title">{html.escape(side)} Overview</p>')
        lines.append(
            f'<img src="{data_uri}" alt="{html.escape(side)}" '
            f'style="max-width:600px; width:100%;">')
        lines.append('</div>')

    if parts:
        header_cells = "".join(f"<th>{html.escape(lbl)}</th>"
                               for _, lbl in _TABLE_COLUMNS)
        lines.append('<table class="data-table"><thead><tr>')
        lines.append(header_cells)
        lines.append('</tr></thead><tbody>')
        for p in parts:
            cells = "".join(
                f'<td>{html.escape(str(p.get(key, "")))}</td>'
                for key, _ in _TABLE_COLUMNS
            )
            lines.append(f"<tr>{cells}</tr>")
        lines.append('</tbody></table>')
    else:
        lines.append('<p class="muted" style="padding:8px 0;">No parts.</p>')

    lines.append('</div></section>')
    return "\n".join(lines)


def _build_footer() -> str:
    return (
        '<footer class="footer">\n'
        '  <a href="#" class="back-to-top">&#8593; Back to Top</a>\n'
        '  <p>Generated by ODB++ Parts Extraction System</p>\n'
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


def _img_data_uri(path: Path) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    mime = mimetypes.guess_type(str(p))[0] or "image/png"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"
