"""Checklist service: run the design-rule checklist and write reports.

Interface-independent core of the "ECAD Checklist" hub feature.  Rules are
discovered automatically (no manual import list), so adding a rule file under
``src/checklist/rules/`` is all that is required.
"""

from __future__ import annotations

from pathlib import Path

from src.checklist.engine import ProgressFn, discover_rules, load_rules, run_checklist
from src.models import RuleResult


def evaluate(job_data: dict, rule_ids: list[str] | None = None,
             progress: ProgressFn | None = None) -> list[RuleResult]:
    """Discover and run checklist rules against parsed job data.

    Args:
        job_data: parsed job dict (from ``data_service.load_job``).
        rule_ids: optional subset of rule IDs to run; ``None`` runs all.
        progress: optional ``(fraction, message)`` callback for UI progress.

    Returns:
        One :class:`RuleResult` per rule that was run.
    """
    discover_rules()
    rules = load_rules(rule_ids)
    return run_checklist(job_data, rules, progress=progress)


def write_report(results: list[RuleResult], *, html_path: Path,
                 odb_filename: str, job_name: str,
                 components_top: list, components_bot: list,
                 references_dir: Path) -> Path:
    """Write the HTML checklist report and return its path.

    Only HTML is produced — Excel reporting has been retired (the ``reporter.py``
    Excel module is kept dormant).  ``_cleanup_images`` removes the temp rule
    images from disk after the HTML reporter has base64-encoded them.
    """
    from src.checklist.html_reporter import generate_html_report
    from src.checklist.reporter import _cleanup_images

    generate_html_report(
        results, html_path,
        odb_filename=odb_filename,
        job_name=job_name,
        components_top=components_top,
        components_bot=components_bot,
        references_dir=references_dir,
    )
    _cleanup_images(results)
    return html_path
