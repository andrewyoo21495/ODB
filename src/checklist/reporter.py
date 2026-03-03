"""Excel report generator for checklist results."""

from __future__ import annotations

import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.models import RuleResult


# Style constants
_HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
_PASS_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
_FAIL_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
_PASS_FONT = Font(color="006100", bold=True)
_FAIL_FONT = Font(color="9C0006", bold=True)
_THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)


def generate_report(results: list[RuleResult], output_path: str | Path,
                    job_name: str = ""):
    """Generate an Excel checklist report.

    Tabs are ordered: Summary, Details, then one tab per rule sorted
    numerically by rule ID (e.g. CKL-01-001, CKL-01-002, CKL-03-010).

    Args:
        results: List of RuleResult objects from the checklist engine
        output_path: Path to write the .xlsx file
        job_name: Job name for the report header
    """
    wb = Workbook()

    # Summary sheet (uses the default first sheet)
    _create_summary_sheet(wb, results, job_name)

    # Detail sheet (all rules in one table)
    _create_detail_sheet(wb, results)

    # Per-rule detail sheets, sorted by rule ID
    sorted_results = sorted(results, key=_rule_sort_key)
    for result in sorted_results:
        _create_rule_sheet(wb, result)

    # Save
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))
    print(f"Checklist report saved: {output_path}")


def _rule_sort_key(result: RuleResult) -> tuple:
    """Extract numeric parts from a rule ID for natural sorting.

    Handles formats like CKL-001, CKL-01-001, CKL-03-010, etc.
    """
    nums = re.findall(r"\d+", result.rule_id)
    return tuple(int(n) for n in nums)


def _create_summary_sheet(wb: Workbook, results: list[RuleResult], job_name: str):
    """Create the summary overview sheet."""
    ws = wb.active
    ws.title = "Summary"

    # Title
    ws.merge_cells("A1:F1")
    title_cell = ws["A1"]
    title_cell.value = f"ODB++ Design Checklist Report - {job_name}"
    title_cell.font = Font(bold=True, size=14)
    title_cell.alignment = Alignment(horizontal="center")

    # Stats
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    ws["A3"] = "Total Rules:"
    ws["B3"] = total
    ws["A4"] = "Passed:"
    ws["B4"] = passed
    ws["B4"].font = _PASS_FONT
    ws["A5"] = "Failed:"
    ws["B5"] = failed
    ws["B5"].font = _FAIL_FONT

    # Headers
    headers = ["Rule ID", "Category", "Description", "Status", "Message", "Affected Components"]
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=7, column=col, value=header)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.border = _THIN_BORDER
        cell.alignment = Alignment(horizontal="center")

    # Data rows
    for row_idx, result in enumerate(results, 8):
        ws.cell(row=row_idx, column=1, value=result.rule_id).border = _THIN_BORDER
        ws.cell(row=row_idx, column=2, value=result.category).border = _THIN_BORDER
        ws.cell(row=row_idx, column=3, value=result.description).border = _THIN_BORDER

        status_cell = ws.cell(row=row_idx, column=4, value="PASS" if result.passed else "FAIL")
        status_cell.fill = _PASS_FILL if result.passed else _FAIL_FILL
        status_cell.font = _PASS_FONT if result.passed else _FAIL_FONT
        status_cell.border = _THIN_BORDER
        status_cell.alignment = Alignment(horizontal="center")

        ws.cell(row=row_idx, column=5, value=result.message).border = _THIN_BORDER
        ws.cell(row=row_idx, column=6,
                value=", ".join(result.affected_components[:20])).border = _THIN_BORDER

    # Auto-fit column widths
    _auto_fit_columns(ws)


def _create_detail_sheet(wb: Workbook, results: list[RuleResult]):
    """Create a detail sheet with expanded rule information."""
    ws = wb.create_sheet("Details")

    headers = ["Rule ID", "Category", "Description", "Status",
               "Message", "Affected Components", "Details"]
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.border = _THIN_BORDER

    for row_idx, result in enumerate(results, 2):
        ws.cell(row=row_idx, column=1, value=result.rule_id).border = _THIN_BORDER
        ws.cell(row=row_idx, column=2, value=result.category).border = _THIN_BORDER
        ws.cell(row=row_idx, column=3, value=result.description).border = _THIN_BORDER

        status_cell = ws.cell(row=row_idx, column=4, value="PASS" if result.passed else "FAIL")
        status_cell.fill = _PASS_FILL if result.passed else _FAIL_FILL
        status_cell.font = _PASS_FONT if result.passed else _FAIL_FONT
        status_cell.border = _THIN_BORDER

        ws.cell(row=row_idx, column=5, value=result.message).border = _THIN_BORDER
        ws.cell(row=row_idx, column=6,
                value="\n".join(result.affected_components)).border = _THIN_BORDER
        ws.cell(row=row_idx, column=6).alignment = Alignment(wrap_text=True)

        # Details as formatted string
        if result.details:
            detail_str = "\n".join(f"{k}: {v}" for k, v in result.details.items())
            ws.cell(row=row_idx, column=7, value=detail_str).border = _THIN_BORDER
            ws.cell(row=row_idx, column=7).alignment = Alignment(wrap_text=True)

    _auto_fit_columns(ws)


def _create_rule_sheet(wb: Workbook, result: RuleResult):
    """Create a dedicated sheet for a single rule's detailed results.

    The tab name is the rule ID (e.g. "CKL-001").  The sheet contains
    a header block with rule metadata followed by a table of detail items.
    """
    ws = wb.create_sheet(result.rule_id)

    # -- Header block ----------------------------------------------------------
    ws["A1"] = "Rule ID:"
    ws["B1"] = result.rule_id
    ws["A1"].font = Font(bold=True)

    ws["A2"] = "Category:"
    ws["B2"] = result.category
    ws["A2"].font = Font(bold=True)

    ws["A3"] = "Description:"
    ws["B3"] = result.description
    ws["A3"].font = Font(bold=True)

    ws["A4"] = "Status:"
    status_cell = ws["B4"]
    status_cell.value = "PASS" if result.passed else "FAIL"
    status_cell.fill = _PASS_FILL if result.passed else _FAIL_FILL
    status_cell.font = _PASS_FONT if result.passed else _FAIL_FONT

    ws["A5"] = "Message:"
    ws["B5"] = result.message
    ws["A5"].font = Font(bold=True)

    # -- Affected components ---------------------------------------------------
    if result.affected_components:
        ws["A7"] = "Affected Components:"
        ws["A7"].font = Font(bold=True)
        for i, comp_name in enumerate(result.affected_components):
            cell = ws.cell(row=8 + i, column=1, value=comp_name)
            cell.border = _THIN_BORDER

    # -- Detail items ----------------------------------------------------------
    # Each key in result.details becomes its own table section.
    start_row = 8 + len(result.affected_components) + 2 if result.affected_components else 8

    for key, value in result.details.items():
        # Section header
        header_cell = ws.cell(row=start_row, column=1, value=key)
        header_cell.font = Font(bold=True, size=11)
        start_row += 1

        if isinstance(value, list):
            # Table header
            hdr_cell = ws.cell(row=start_row, column=1, value="#")
            hdr_cell.fill = _HEADER_FILL
            hdr_cell.font = _HEADER_FONT
            hdr_cell.border = _THIN_BORDER
            hdr_cell = ws.cell(row=start_row, column=2, value="Detail")
            hdr_cell.fill = _HEADER_FILL
            hdr_cell.font = _HEADER_FONT
            hdr_cell.border = _THIN_BORDER
            start_row += 1

            for idx, item in enumerate(value, 1):
                ws.cell(row=start_row, column=1, value=idx).border = _THIN_BORDER
                ws.cell(row=start_row, column=2, value=str(item)).border = _THIN_BORDER
                start_row += 1
        elif isinstance(value, dict):
            hdr_cell = ws.cell(row=start_row, column=1, value="Key")
            hdr_cell.fill = _HEADER_FILL
            hdr_cell.font = _HEADER_FONT
            hdr_cell.border = _THIN_BORDER
            hdr_cell = ws.cell(row=start_row, column=2, value="Value")
            hdr_cell.fill = _HEADER_FILL
            hdr_cell.font = _HEADER_FONT
            hdr_cell.border = _THIN_BORDER
            start_row += 1

            for k, v in value.items():
                ws.cell(row=start_row, column=1, value=str(k)).border = _THIN_BORDER
                ws.cell(row=start_row, column=2, value=str(v)).border = _THIN_BORDER
                start_row += 1
        else:
            ws.cell(row=start_row, column=1, value=str(value)).border = _THIN_BORDER
            start_row += 1

        start_row += 1  # blank row between sections

    _auto_fit_columns(ws)


def _auto_fit_columns(ws):
    """Auto-fit column widths based on content."""
    for col_idx in range(1, ws.max_column + 1):
        max_length = 0
        col_letter = get_column_letter(col_idx)
        for row in ws.iter_rows(min_col=col_idx, max_col=col_idx):
            for cell in row:
                if cell.value:
                    lines = str(cell.value).split("\n")
                    max_line = max(len(line) for line in lines)
                    max_length = max(max_length, max_line)
        ws.column_dimensions[col_letter].width = min(50, max(10, max_length + 2))
