"""Compare service: diff two ODB++ revisions and write a report.

Interface-independent core of the "Revision Comparator" hub feature.
Comparators are discovered automatically (no manual import list).
"""

from __future__ import annotations

from pathlib import Path

from src.comparator.base import ComparisonResult
from src.comparator.engine import discover_comparators, run_comparison


def compare(old_data: dict, new_data: dict,
            comparator_ids: list[str] | None = None) -> list[ComparisonResult]:
    """Discover and run comparators against two parsed revisions.

    Args:
        old_data / new_data: parsed job dicts (from ``data_service.load_job``).
        comparator_ids: optional subset; ``None`` runs all registered.

    Returns:
        One :class:`ComparisonResult` per comparator.
    """
    discover_comparators()
    return run_comparison(old_data, new_data, comparator_ids)


def write_html_report(results: list[ComparisonResult], output_path: Path, *,
                      old_job_name: str, new_job_name: str) -> Path:
    """Write the HTML comparison report (checklist-style) and return its path."""
    from src.comparator.html_reporter import generate_comparison_html_report
    return generate_comparison_html_report(
        results, output_path,
        old_job_name=old_job_name,
        new_job_name=new_job_name,
    )


def write_report(results: list[ComparisonResult], output_path: Path, *,
                 old_job_name: str, new_job_name: str) -> Path:
    """Write the Excel comparison report and return its path.

    DORMANT: Excel reporting is retired; reports are HTML-only (see
    :func:`write_html_report`).  Kept for reuse only.
    """
    from src.comparator.reporter import generate_comparison_report
    generate_comparison_report(
        results, output_path,
        old_job_name=old_job_name,
        new_job_name=new_job_name,
    )
    return output_path
