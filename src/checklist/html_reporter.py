"""Self-contained HTML report generator for checklist results."""

from __future__ import annotations

import base64
import html
import mimetypes
import re
from datetime import datetime
from pathlib import Path

from src.checklist.reporter import _load_csv_part_map, _count_usage
from src.models import RuleResult


# ---------------------------------------------------------------------------
# Sorting helper (same logic as reporter._rule_sort_key)
# ---------------------------------------------------------------------------

def _rule_sort_key(result: RuleResult) -> tuple:
    nums = re.findall(r"\d+", result.rule_id)
    return tuple(int(n) for n in nums)


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
  --pass: #198754;
  --fail: #dc3545;
  --nc: #1F4E79;
  --pass-bg: #C6EFCE;
  --fail-bg: #FFC7CE;
  --nc-bg: #BDD7EE;
  --header-blue: #4472C4;
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
.header-meta { font-size: 0.95rem; opacity: 0.8; display: flex; justify-content: center; gap: 28px; flex-wrap: wrap; }

/* Stats bar */
.stats-bar {
  display: flex; justify-content: center; gap: 40px; padding: 20px 32px;
  background: #fff; border-bottom: 1px solid var(--border); flex-wrap: wrap;
}
.stat { text-align: center; }
.stat-value { font-size: 1.7rem; font-weight: 700; color: var(--primary); }
.stat-label { font-size: 0.8rem; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; }
.pass-text { color: var(--pass); }
.fail-text { color: var(--fail); }

/* Layout: sidebar + main */
.page-layout { display: flex; max-width: 1400px; margin: 0 auto; padding: 24px 20px; gap: 28px; }
.main-content { flex: 1; min-width: 0; }

/* ToC sidebar */
.toc-sidebar {
  width: 260px; flex-shrink: 0;
  position: sticky; top: 16px; align-self: flex-start;
  max-height: calc(100vh - 32px); overflow-y: auto;
  background: #fff; border: 1px solid var(--border); border-radius: 10px;
  padding: 18px 16px; font-size: 0.85rem;
}
.toc-sidebar h3 { font-size: 1rem; margin-bottom: 10px; }
.toc-sidebar h4 { font-size: 0.88rem; color: var(--muted); margin: 12px 0 4px; }
.toc-sidebar ul { list-style: none; padding: 0; }
.toc-sidebar li { margin: 2px 0; }
.toc-sidebar a { color: var(--text); text-decoration: none; display: flex; align-items: center; gap: 6px; padding: 2px 4px; border-radius: 4px; }
.toc-sidebar a:hover { background: #e9ecef; }
.toc-controls { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; align-items: center; }
.toc-controls button {
  background: var(--header-blue); color: #fff; border: none; border-radius: 4px;
  padding: 3px 10px; font-size: 0.78rem; cursor: pointer;
}
.toc-controls button:hover { opacity: 0.85; }
.toc-controls label { font-size: 0.78rem; cursor: pointer; display: flex; align-items: center; gap: 4px; }

/* ToC badges */
.toc-badge {
  display: inline-block; font-size: 0.65rem; font-weight: 700; padding: 1px 5px;
  border-radius: 3px; min-width: 34px; text-align: center; flex-shrink: 0;
}
.toc-badge-pass { background: var(--pass-bg); color: var(--pass); }
.toc-badge-fail { background: var(--fail-bg); color: var(--fail); }

/* Section titles */
section > h2 {
  font-size: 1.25rem; font-weight: 700; margin: 32px 0 14px;
  padding-bottom: 6px; border-bottom: 2px solid var(--header-blue);
}

/* Summary table */
.summary-table {
  width: 100%; border-collapse: collapse; background: #fff;
  border: 1px solid var(--border); font-size: 0.88rem;
}
.summary-table th {
  background: var(--header-blue); color: #fff; padding: 9px 10px; text-align: center;
  font-weight: 600; border: 1px solid #3a6ab5;
}
.summary-table td { padding: 7px 10px; border: 1px solid var(--border); }
.summary-table a { color: var(--primary); text-decoration: none; }
.summary-table a:hover { text-decoration: underline; }
.row-pass td:first-child { border-left: 3px solid var(--pass); }
.row-fail td:first-child { border-left: 3px solid var(--fail); }

/* Status cells */
.status-pass { background: var(--pass-bg); color: var(--pass); font-weight: 700; text-align: center; }
.status-fail { background: var(--fail-bg); color: var(--fail); font-weight: 700; text-align: center; }
.status-nc   { background: var(--nc-bg);   color: var(--nc);   font-weight: 700; text-align: center; }

/* Managed parts */
.managed-subsection { background: #fff; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 14px; overflow: hidden; }
.managed-subsection h3 {
  margin: 0; padding: 10px 16px; background: var(--header-blue); color: #fff;
  font-size: 0.92rem; cursor: pointer; user-select: none; display: flex; align-items: center; justify-content: space-between;
}
.managed-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.managed-table th {
  background: #D9E1F2; padding: 7px 10px; text-align: center;
  font-weight: 600; border: 1px solid var(--border);
}
.managed-table td { padding: 5px 10px; border: 1px solid var(--border); }
td.center, th.center { text-align: center; }
.used-row { background: var(--pass-bg); }
.used-row td { color: var(--pass); }
.unused-row { background: #f2f2f2; }
.unused-row td { color: #a0a0a0; font-style: italic; }
.managed-subsection.collapsed .managed-table { display: none; }

/* Rule sections */
.rule-section {
  background: #fff; border: 1px solid var(--border); border-radius: 10px;
  margin-bottom: 16px; overflow: hidden;
}
.rule-section-header {
  display: flex; align-items: center; gap: 10px; padding: 12px 18px;
  cursor: pointer; user-select: none; background: #fdfdfd; flex-wrap: wrap;
}
.rule-section-header:hover { background: #f1f3f5; }
.rule-section-id { font-weight: 700; font-size: 0.95rem; white-space: nowrap; }
.rule-section-desc { flex: 1; font-size: 0.9rem; color: var(--muted); min-width: 200px; }
.status-badge {
  font-size: 0.75rem; font-weight: 700; padding: 3px 12px;
  border-radius: 4px; white-space: nowrap;
}
.status-badge.status-pass { background: var(--pass-bg); color: var(--pass); }
.status-badge.status-fail { background: var(--fail-bg); color: var(--fail); }
.toggle-icon { font-size: 0.7rem; color: var(--muted); transition: transform 0.2s; }
.rule-section:not(.collapsed) .toggle-icon { transform: rotate(90deg); }
.rule-section.collapsed .rule-content { display: none; }
.rule-content { padding: 0 18px 18px; }

/* Rule metadata */
.rule-meta { padding: 12px 0 8px; font-size: 0.88rem; }
.rule-meta p { margin: 3px 0; }

/* Detail tables */
.detail-table {
  width: 100%; border-collapse: collapse; font-size: 0.85rem;
  margin: 8px 0 14px; border: 1px solid var(--border);
}
.detail-table th {
  background: var(--header-blue); color: #fff; padding: 7px 10px;
  text-align: center; font-weight: 600; border: 1px solid #3a6ab5;
}
.detail-table td { padding: 5px 10px; border: 1px solid var(--border); }

/* Images */
.rule-images { padding-top: 10px; }
.image-block { margin-bottom: 16px; }
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
  .rule-section.collapsed .rule-content { display: block !important; }
  .rule-section { break-inside: avoid; border: 1px solid #ccc; }
  .managed-subsection.collapsed .managed-table { display: table !important; }
  .page-layout { display: block; }
  body { background: #fff; }
}
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_html_report(
    results: list[RuleResult],
    output_path: str | Path,
    job_name: str = "",
    components_top=None,
    components_bot=None,
    references_dir: str | Path = None,
) -> None:
    """Generate a self-contained HTML checklist report.

    Signature mirrors ``generate_report()`` from *reporter.py* for drop-in
    usage.  Does **not** call ``_cleanup_images()`` — the caller handles that.
    """
    sorted_results = sorted(results, key=_rule_sort_key)

    # Pre-encode all images before anything else
    image_cache = _build_image_cache(sorted_results)

    parts = [
        _build_doctype_and_head(job_name),
        _build_header_banner(job_name),
        _build_stats_bar(results),
        '<div class="page-layout">',
        _build_table_of_contents(sorted_results),
        '<div class="main-content">',
        _build_summary_table(sorted_results),
        _build_managed_parts_section(
            components_top or [], components_bot or [], references_dir),
        *[_build_rule_section(r, image_cache) for r in sorted_results],
        '</div>',   # close .main-content
        '</div>',   # close .page-layout
        _build_footer(),
        _build_script(),
        '</body></html>',
    ]

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(parts), encoding="utf-8")
    print(f"HTML checklist report saved: {output_path}")


# ---------------------------------------------------------------------------
# Image cache
# ---------------------------------------------------------------------------

def _build_image_cache(results: list[RuleResult]) -> dict[str, str]:
    """Read all referenced image files and encode them as base64 data URIs.

    Must be called **before** ``_cleanup_images()`` deletes the temp files.
    """
    cache: dict[str, str] = {}
    for r in results:
        for img_info in r.images:
            p = Path(img_info["path"])
            key = str(p)
            if key in cache or not p.exists():
                continue
            mime = mimetypes.guess_type(str(p))[0] or "image/png"
            b64 = base64.b64encode(p.read_bytes()).decode("ascii")
            cache[key] = f"data:{mime};base64,{b64}"
    return cache


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_doctype_and_head(job_name: str) -> str:
    safe_title = html.escape(job_name) if job_name else "Checklist Report"
    return (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>ODB++ Checklist Report - {safe_title}</title>\n'
        f'<style>\n{_CSS}\n</style>\n'
        '</head>\n<body>'
    )


def _build_header_banner(job_name: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        '<div class="header">\n'
        '  <h1>ODB++ Design Checklist Report</h1>\n'
        '  <div class="header-meta">\n'
        f'    <span>Job: {html.escape(job_name)}</span>\n'
        f'    <span>Generated: {now}</span>\n'
        '  </div>\n'
        '</div>'
    )


def _build_stats_bar(results: list[RuleResult]) -> str:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    rate = f"{100 * passed / total:.1f}%" if total else "N/A"
    return (
        '<div class="stats-bar">\n'
        f'  <div class="stat"><div class="stat-value">{total}</div>'
        '<div class="stat-label">Total Rules</div></div>\n'
        f'  <div class="stat"><div class="stat-value pass-text">{passed}</div>'
        '<div class="stat-label">Passed</div></div>\n'
        f'  <div class="stat"><div class="stat-value fail-text">{failed}</div>'
        '<div class="stat-label">Failed</div></div>\n'
        f'  <div class="stat"><div class="stat-value">{rate}</div>'
        '<div class="stat-label">Pass Rate</div></div>\n'
        '</div>'
    )


def _build_table_of_contents(sorted_results: list[RuleResult]) -> str:
    categories: dict[str, list[RuleResult]] = {}
    for r in sorted_results:
        categories.setdefault(r.category, []).append(r)

    lines = [
        '<nav class="toc-sidebar">',
        '<h3>Table of Contents</h3>',
        '<div class="toc-controls">',
        '  <button onclick="toggleAllSections(true)">Expand All</button>',
        '  <button onclick="toggleAllSections(false)">Collapse All</button>',
        '  <label><input type="checkbox" id="failures-only" '
        'onchange="toggleFailuresOnly()"> Failures only</label>',
        '</div>',
        '<a href="#summary" style="display:block;margin-bottom:4px;">Summary</a>',
        '<a href="#managed-parts" style="display:block;margin-bottom:8px;">Managed Parts</a>',
    ]
    for cat, cat_results in categories.items():
        lines.append(f'<h4>{html.escape(cat)}</h4><ul>')
        for r in cat_results:
            badge = "pass" if r.passed else "fail"
            lines.append(
                f'<li class="toc-{badge}">'
                f'<a href="#rule-{r.rule_id}">'
                f'<span class="toc-badge toc-badge-{badge}">'
                f'{"PASS" if r.passed else "FAIL"}</span> '
                f'{html.escape(r.rule_id)}</a></li>'
            )
        lines.append('</ul>')
    lines.append('</nav>')
    return "\n".join(lines)


def _build_summary_table(sorted_results: list[RuleResult]) -> str:
    lines = [
        '<section id="summary"><h2>Summary</h2>',
        '<table class="summary-table"><thead><tr>',
        '<th>Rule ID</th><th>Category</th><th>Description</th>',
        '<th>Status</th><th>Message</th><th>Affected Components</th>',
        '</tr></thead><tbody>',
    ]
    for r in sorted_results:
        status_cls = "pass" if r.passed else "fail"
        status_text = "PASS" if r.passed else "FAIL"
        comps = ", ".join(r.affected_components[:20])
        if len(r.affected_components) > 20:
            comps += f" (+{len(r.affected_components) - 20} more)"
        lines.append(
            f'<tr class="row-{status_cls}">'
            f'<td><a href="#rule-{r.rule_id}">{html.escape(r.rule_id)}</a></td>'
            f'<td>{html.escape(r.category)}</td>'
            f'<td>{html.escape(r.description)}</td>'
            f'<td class="status-{status_cls}">{status_text}</td>'
            f'<td>{html.escape(r.message)}</td>'
            f'<td>{html.escape(comps)}</td>'
            f'</tr>'
        )
    lines.append('</tbody></table></section>')
    return "\n".join(lines)


def _build_managed_parts_section(
    components_top: list, components_bot: list, references_dir,
) -> str:
    ref = Path(references_dir) if references_dir else None
    if not ref or not ref.is_dir():
        return ('<section id="managed-parts"><h2>Managed Parts</h2>'
                '<p>No managed-parts CSV files found.</p></section>')

    cap10_map = _load_csv_part_map(ref / "capacitors_10_list.csv")
    cap41_map = _load_csv_part_map(ref / "capacitors_41_list.csv")
    ind2s_map = _load_csv_part_map(ref / "inductors_2s_list.csv")

    sections_data = [
        (f"Capacitors 10-type ({len(cap10_map)} types)", cap10_map),
        (f"Capacitors 41-type ({len(cap41_map)} types)", cap41_map),
        (f"Inductors 2S ({len(ind2s_map)} types)", ind2s_map),
    ]

    lines = ['<section id="managed-parts">'
             '<h2>Managed Parts &mdash; Usage Frequency</h2>']
    for title, part_map in sections_data:
        if not part_map:
            continue
        usage = _count_usage(set(part_map.keys()), components_top, components_bot)
        sorted_parts = sorted(
            part_map.items(),
            key=lambda kv: (-usage[kv[0]]["total"], kv[0]),
        )
        lines.append('<div class="managed-subsection">')
        lines.append(
            '<h3 class="collapsible-header" '
            "onclick=\"this.parentElement.classList.toggle('collapsed')\">"
            f'{html.escape(title)} '
            '<span class="toggle-icon">&#9660;</span></h3>'
        )
        lines.append(
            '<table class="managed-table"><thead><tr>'
            '<th>part_name</th><th>size</th>'
            '<th class="center">TOP</th><th class="center">BOTTOM</th>'
            '<th class="center">Total</th>'
            '</tr></thead><tbody>'
        )
        for pn, sz in sorted_parts:
            cnt = usage[pn]
            row_cls = "used-row" if cnt["total"] > 0 else "unused-row"
            lines.append(
                f'<tr class="{row_cls}">'
                f'<td>{html.escape(pn)}</td><td>{html.escape(sz)}</td>'
                f'<td class="center">{cnt["top"]}</td>'
                f'<td class="center">{cnt["bottom"]}</td>'
                f'<td class="center">{cnt["total"]}</td></tr>'
            )
        lines.append('</tbody></table></div>')
    lines.append('</section>')
    return "\n".join(lines)


def _build_rule_section(
    result: RuleResult, image_cache: dict[str, str],
) -> str:
    status_cls = "pass" if result.passed else "fail"
    collapsed = " collapsed" if result.passed else ""
    if result.passed:
        status_text = "PASS"
    elif result.recommended:
        status_text = "FAIL (Recommended)"
    else:
        status_text = "FAIL"

    lines = [
        f'<section id="rule-{result.rule_id}" '
        f'class="rule-section{collapsed}" data-status="{status_cls}">',
        '<div class="rule-section-header" '
        "onclick=\"this.parentElement.classList.toggle('collapsed')\">",
        f'  <span class="rule-section-id">{html.escape(result.rule_id)}</span>',
        f'  <span class="rule-section-desc">{html.escape(result.description)}</span>',
        f'  <span class="status-badge status-{status_cls}">{status_text}</span>',
        '  <span class="toggle-icon">&#9654;</span>',
        '</div>',
        '<div class="rule-content">',
    ]

    # Metadata
    lines.append('<div class="rule-meta">')
    lines.append(
        f'<p><strong>Category:</strong> {html.escape(result.category)}</p>')
    lines.append(
        f'<p><strong>Message:</strong> {html.escape(result.message)}</p>')
    if result.affected_components:
        comps = ", ".join(result.affected_components)
        lines.append(
            f'<p><strong>Affected Components ({len(result.affected_components)}):</strong> '
            f'{html.escape(comps)}</p>')
    lines.append('</div>')

    # Detail tables
    lines.append(_render_details(result.details))

    # Images
    if result.images:
        lines.append('<div class="rule-images">')
        for img_info in result.images:
            data_uri = image_cache.get(str(img_info["path"]))
            if not data_uri:
                continue
            title = img_info.get("title", "")
            width = img_info.get("width", 500)
            lines.append('<div class="image-block">')
            if title:
                lines.append(
                    f'<p class="image-title">{html.escape(title)}</p>')
            lines.append(
                f'<img src="{data_uri}" alt="{html.escape(title)}" '
                f'style="max-width:{width}px; width:100%;">')
            lines.append('</div>')
        lines.append('</div>')

    lines.append('</div></section>')  # close .rule-content and .rule-section
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Detail rendering helpers
# ---------------------------------------------------------------------------

def _render_details(details: dict) -> str:
    if not details:
        return ""

    columns = details.get("columns")
    rows = details.get("rows")

    parts: list[str] = []

    # Tabular mode
    if isinstance(columns, list) and isinstance(rows, list):
        parts.append(_render_tabular_table(columns, rows))

        # Optional signal table (e.g. CKL-03-015)
        sig_columns = details.get("signal_columns")
        sig_rows = details.get("signal_rows")
        if isinstance(sig_columns, list) and isinstance(sig_rows, list) and sig_rows:
            parts.append(_render_tabular_table(sig_columns, sig_rows))
    else:
        # Legacy mode
        for key, value in details.items():
            if key in ("columns", "rows", "signal_columns", "signal_rows"):
                continue
            parts.append(f'<h4>{html.escape(str(key))}</h4>')
            if isinstance(value, list):
                parts.append(
                    '<table class="detail-table"><thead><tr>'
                    '<th>#</th><th>Detail</th></tr></thead><tbody>')
                for idx, item in enumerate(value, 1):
                    parts.append(
                        f'<tr><td>{idx}</td>'
                        f'<td>{html.escape(str(item))}</td></tr>')
                parts.append('</tbody></table>')
            elif isinstance(value, dict):
                parts.append(
                    '<table class="detail-table"><thead><tr>'
                    '<th>Key</th><th>Value</th></tr></thead><tbody>')
                for k, v in value.items():
                    parts.append(
                        f'<tr><td>{html.escape(str(k))}</td>'
                        f'<td>{html.escape(str(v))}</td></tr>')
                parts.append('</tbody></table>')
            else:
                parts.append(f'<p>{html.escape(str(value))}</p>')

    return "\n".join(parts)


def _render_tabular_table(columns: list[str], rows: list[dict]) -> str:
    lines = ['<table class="detail-table"><thead><tr>']
    for col in columns:
        lines.append(f'<th>{html.escape(col)}</th>')
    lines.append('</tr></thead><tbody>')
    for row_data in rows:
        lines.append('<tr>')
        for col in columns:
            value = row_data.get(col, "")
            cell_cls = ""
            if col.lower() == "status":
                val_upper = str(value).upper()
                if val_upper == "PASS":
                    cell_cls = ' class="status-pass"'
                elif val_upper == "FAIL":
                    cell_cls = ' class="status-fail"'
                elif val_upper == "NC":
                    cell_cls = ' class="status-nc"'
            lines.append(
                f'<td{cell_cls}>{html.escape(str(value))}</td>')
        lines.append('</tr>')
    lines.append('</tbody></table>')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Footer & script
# ---------------------------------------------------------------------------

def _build_footer() -> str:
    return (
        '<footer class="footer">\n'
        '  <a href="#" class="back-to-top">&#8593; Back to Top</a>\n'
        '  <p>Generated by ODB++ Design Checklist System</p>\n'
        '</footer>'
    )


def _build_script() -> str:
    return """\
<script>
function toggleAllSections(expand) {
  document.querySelectorAll('.rule-section').forEach(function(s) {
    if (expand) s.classList.remove('collapsed');
    else s.classList.add('collapsed');
  });
  document.querySelectorAll('.managed-subsection').forEach(function(s) {
    if (expand) s.classList.remove('collapsed');
    else s.classList.add('collapsed');
  });
}
function toggleFailuresOnly() {
  var checked = document.getElementById('failures-only').checked;
  document.querySelectorAll('.rule-section').forEach(function(s) {
    if (s.dataset.status === 'pass') {
      s.style.display = checked ? 'none' : '';
    }
  });
  document.querySelectorAll('.toc-pass').forEach(function(li) {
    li.style.display = checked ? 'none' : '';
  });
  document.querySelectorAll('.summary-table .row-pass').forEach(function(tr) {
    tr.style.display = checked ? 'none' : '';
  });
}
</script>"""
