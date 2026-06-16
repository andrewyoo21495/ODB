"""Self-contained HTML report generator for revision comparison.

Visual style mirrors the checklist HTML report (gradient header banner, stat
bar, summary table, colored status cells).  Renders a list of
:class:`ComparisonResult` (each with ``sheet_configs``) generically: an overview
table plus, per comparator, its sheets (stats + table + base64 images).  Row
coloring follows the "Change" / "Transition" column.
"""

from __future__ import annotations

import base64
import html
from pathlib import Path

from src.comparator.base import ComparisonResult, SheetConfig

# Map a Change / Transition value to (row-accent class, cell status class).
_VALUE_CLASS = {
    "ADDED": "pass",
    "REMOVED": "fail",
    "RELOCATED": "warn",
    "MODIFIED": "warn",
    "FIXED": "pass",
    "REGRESSED": "fail",
    "STILL_FAIL": "fail",
    "NEW_RULE": "nc",
    "REMOVED_RULE": "warn",
    "STILL_PASS": "pass",
}

_CSS = """
:root {
  --bg:#f8f9fa; --card-bg:#fff; --border:#dee2e6; --text:#212529; --muted:#6c757d;
  --primary:#0d6efd; --pass:#198754; --fail:#dc3545; --warn:#e67e00; --nc:#1F4E79;
  --pass-bg:#C6EFCE; --fail-bg:#FFC7CE; --warn-bg:#FFE0B2; --nc-bg:#BDD7EE;
  --header-blue:#4472C4;
}
* { box-sizing:border-box; }
body { margin:0; font-family:'Malgun Gothic','Segoe UI',system-ui,-apple-system,sans-serif;
  background:var(--bg); color:var(--text); }
.header { background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);
  color:#fff; padding:26px 32px; text-align:center; }
.header h1 { font-size:1.7rem; font-weight:700; margin:0 0 6px; }
.header-meta { font-size:0.95rem; opacity:0.85; display:flex; justify-content:center;
  gap:24px; flex-wrap:wrap; }
.stat-bar { display:flex; gap:36px; justify-content:center; padding:16px;
  background:#fff; border-bottom:1px solid var(--border); flex-wrap:wrap; }
.stat-value { font-size:1.6rem; font-weight:700; color:var(--primary); text-align:center; }
.stat-label { font-size:0.78rem; color:var(--muted); text-transform:uppercase;
  letter-spacing:.5px; text-align:center; }
.wrap { max-width:1100px; margin:0 auto; padding:24px 32px; }
h2 { font-size:1.15rem; margin:28px 0 4px; padding-bottom:6px;
  border-bottom:2px solid var(--header-blue); }
h2 .muted { color:var(--muted); font-weight:400; font-size:0.85rem; }
h3 { font-size:0.95rem; margin:16px 0 6px; }
.summary { color:var(--muted); margin:4px 0 10px; }
.badge { display:inline-block; background:#eef2ff; border:1px solid #d6e0ff;
  border-radius:10px; padding:1px 9px; margin:2px; font-size:0.82rem; }
table { width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--border);
  font-size:0.86rem; margin:6px 0 14px; }
th { background:var(--header-blue); color:#fff; padding:8px 10px; text-align:center; }
td { padding:6px 10px; border:1px solid var(--border); }
.muted-note { color:var(--muted); padding:8px 0; }
.row-pass td:first-child { border-left:3px solid var(--pass); }
.row-fail td:first-child { border-left:3px solid var(--fail); }
.row-warn td:first-child { border-left:3px solid var(--warn); }
.row-nc   td:first-child { border-left:3px solid var(--nc); }
.cell-pass { background:var(--pass-bg); color:var(--pass); font-weight:700; text-align:center; }
.cell-fail { background:var(--fail-bg); color:var(--fail); font-weight:700; text-align:center; }
.cell-warn { background:var(--warn-bg); color:var(--warn); font-weight:700; text-align:center; }
.cell-nc   { background:var(--nc-bg);   color:var(--nc);   font-weight:700; text-align:center; }
figure { margin:8px 0; } img { max-width:560px; border:1px solid var(--border); border-radius:6px; }
"""


def _img_data_uri(path: Path) -> str:
    b64 = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _color_column(columns: list[str]) -> str | None:
    if "Change" in columns:
        return "Change"
    if "Transition" in columns:
        return "Transition"
    return None


def _render_sheet(cfg: SheetConfig) -> str:
    parts: list[str] = [f"<h3>{html.escape(cfg.title or cfg.sheet_name)}</h3>"]

    if cfg.stats:
        badges = " ".join(
            f'<span class="badge">{html.escape(str(k))}: {html.escape(str(v))}</span>'
            for k, v in cfg.stats.items()
        )
        parts.append(f"<p>{badges}</p>")

    if cfg.columns and cfg.rows:
        color_col = _color_column(cfg.columns)
        head = "".join(f"<th>{html.escape(c)}</th>" for c in cfg.columns)
        body_rows = []
        for row in cfg.rows:
            cls = _VALUE_CLASS.get(str(row.get(color_col, ""))) if color_col else None
            row_cls = f' class="row-{cls}"' if cls else ""
            cells = []
            for c in cfg.columns:
                val = html.escape(str(row.get(c, "")))
                if c == color_col and cls:
                    cells.append(f'<td class="cell-{cls}">{val}</td>')
                else:
                    cells.append(f"<td>{val}</td>")
            body_rows.append(f"<tr{row_cls}>{''.join(cells)}</tr>")
        parts.append(
            f"<table><thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody></table>"
        )
    else:
        parts.append('<p class="muted-note">No changes detected.</p>')

    for img in cfg.images or []:
        try:
            uri = _img_data_uri(img["path"])
        except Exception:
            continue
        title = html.escape(str(img.get("title", "")))
        parts.append(f'<figure><figcaption>{title}</figcaption><img src="{uri}"></figure>')

    return "<section>" + "\n".join(parts) + "</section>"


def _render_result(result: ComparisonResult) -> str:
    sheets = "\n".join(_render_sheet(s) for s in result.sheet_configs)
    return (
        f"<h2>{html.escape(result.title)} "
        f'<span class="muted">[{html.escape(result.comparator_id)}]</span></h2>'
        f'<p class="summary">{html.escape(result.summary)}</p>'
        f"{sheets}"
    )


def generate_comparison_html_report(results: list[ComparisonResult],
                                    output_path: Path, *,
                                    old_job_name: str, new_job_name: str) -> Path:
    """Write a self-contained HTML comparison report; return its path."""
    output_path = Path(output_path)

    overview_rows = "\n".join(
        f"<tr><td>{html.escape(r.comparator_id)}</td>"
        f"<td>{html.escape(r.title)}</td>"
        f"<td>{html.escape(r.summary)}</td></tr>"
        for r in results
    )
    body = "\n".join(_render_result(r) for r in results)

    doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>Comparison — {html.escape(old_job_name)} vs {html.escape(new_job_name)}</title>
<style>{_CSS}</style></head><body>
<div class="header">
  <h1>Revision Comparison</h1>
  <div class="header-meta">
    <span>OLD: {html.escape(old_job_name)}</span>
    <span>→</span>
    <span>NEW: {html.escape(new_job_name)}</span>
  </div>
</div>
<div class="stat-bar">
  <div><div class="stat-value">{len(results)}</div><div class="stat-label">Comparators</div></div>
</div>
<div class="wrap">
  <h2>Overview</h2>
  <table><thead><tr><th>Comparator</th><th>Title</th><th>Summary</th></tr></thead>
  <tbody>{overview_rows}</tbody></table>
  {body}
</div>
</body></html>"""
    output_path.write_text(doc, encoding="utf-8")
    return output_path
