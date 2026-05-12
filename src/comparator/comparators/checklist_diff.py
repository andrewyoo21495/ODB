"""Checklist diff comparator: compares checklist PASS/FAIL results between
two ODB++ revisions to identify FIXED, REGRESSED, and persistent issues."""

from __future__ import annotations

import re

from src.comparator.base import (
    ChecklistChange, ChecklistTransition, ComparatorBase, ComparisonResult,
    SheetConfig,
)
from src.comparator.engine import register_comparator


def _import_all_rules():
    """Import all checklist rule modules to trigger @register_rule.

    This mirrors the import block in cmd_check() in main.py.
    """
    import src.checklist.rules.ckl_01_001  # noqa: F401
    import src.checklist.rules.ckl_01_002  # noqa: F401
    import src.checklist.rules.ckl_01_003  # noqa: F401
    import src.checklist.rules.ckl_01_004  # noqa: F401
    import src.checklist.rules.ckl_01_005  # noqa: F401
    import src.checklist.rules.ckl_01_006  # noqa: F401
    import src.checklist.rules.ckl_01_007  # noqa: F401
    import src.checklist.rules.ckl_02_001  # noqa: F401
    import src.checklist.rules.ckl_02_002  # noqa: F401
    import src.checklist.rules.ckl_02_003  # noqa: F401
    import src.checklist.rules.ckl_02_004  # noqa: F401
    import src.checklist.rules.ckl_02_005  # noqa: F401
    import src.checklist.rules.ckl_02_006  # noqa: F401
    import src.checklist.rules.ckl_02_007  # noqa: F401
    import src.checklist.rules.ckl_02_008  # noqa: F401
    import src.checklist.rules.ckl_02_009  # noqa: F401
    import src.checklist.rules.ckl_02_010  # noqa: F401
    import src.checklist.rules.ckl_02_011  # noqa: F401
    import src.checklist.rules.ckl_02_012  # noqa: F401
    import src.checklist.rules.ckl_03_001  # noqa: F401
    import src.checklist.rules.ckl_03_002  # noqa: F401
    import src.checklist.rules.ckl_03_004  # noqa: F401
    import src.checklist.rules.ckl_03_011  # noqa: F401
    import src.checklist.rules.ckl_03_005  # noqa: F401
    import src.checklist.rules.ckl_03_012  # noqa: F401
    import src.checklist.rules.ckl_03_013  # noqa: F401
    import src.checklist.rules.ckl_03_015  # noqa: F401
    import src.checklist.rules.ckl_03_016  # noqa: F401
    import src.checklist.rules.ckl_03_008  # noqa: F401
    import src.checklist.rules.ckl_03_009  # noqa: F401


def _rule_sort_key(rule_id: str) -> tuple:
    """Natural sort by numeric parts of a rule ID (e.g. CKL-01-002)."""
    nums = re.findall(r"\d+", rule_id)
    return tuple(int(n) for n in nums)


# Sort priority for transitions: actionable items first
_TRANSITION_ORDER = {
    ChecklistTransition.REGRESSED: 0,
    ChecklistTransition.FIXED: 1,
    ChecklistTransition.STILL_FAIL: 2,
    ChecklistTransition.NEW_RULE: 3,
    ChecklistTransition.REMOVED_RULE: 4,
    ChecklistTransition.STILL_PASS: 5,
}

_CKL_COLUMNS = [
    "Rule ID", "Category", "Description",
    "Old Status", "New Status", "Transition",
    "Old Message", "New Message",
    "Old Affected #", "New Affected #",
]


@register_comparator
class ChecklistDiffComparator(ComparatorBase):
    """Compare checklist results between two revisions."""

    comparator_id = "CKL-DIFF"
    title = "Checklist Changes"

    def compare(self, old_data: dict, new_data: dict) -> ComparisonResult:
        # Ensure rules are registered
        _import_all_rules()

        from src.checklist.engine import run_checklist

        print("  Running checklist on old revision...")
        old_results = run_checklist(old_data)
        print("  Running checklist on new revision...")
        new_results = run_checklist(new_data)

        old_map = {r.rule_id: r for r in old_results}
        new_map = {r.rule_id: r for r in new_results}

        all_ids = sorted(set(old_map.keys()) | set(new_map.keys()),
                         key=_rule_sort_key)

        changes: list[ChecklistChange] = []
        for rule_id in all_ids:
            old_r = old_map.get(rule_id)
            new_r = new_map.get(rule_id)

            if old_r and not new_r:
                transition = ChecklistTransition.REMOVED_RULE
            elif new_r and not old_r:
                transition = ChecklistTransition.NEW_RULE
            elif old_r.passed and new_r.passed:
                transition = ChecklistTransition.STILL_PASS
            elif not old_r.passed and new_r.passed:
                transition = ChecklistTransition.FIXED
            elif old_r.passed and not new_r.passed:
                transition = ChecklistTransition.REGRESSED
            else:
                transition = ChecklistTransition.STILL_FAIL

            changes.append(ChecklistChange(
                rule_id=rule_id,
                description=(new_r or old_r).description,
                category=(new_r or old_r).category,
                transition=transition,
                old_status="PASS" if (old_r and old_r.passed) else (
                    "FAIL" if old_r else None),
                new_status="PASS" if (new_r and new_r.passed) else (
                    "FAIL" if new_r else None),
                old_message=old_r.message if old_r else "",
                new_message=new_r.message if new_r else "",
                old_affected_count=len(old_r.affected_components) if old_r else 0,
                new_affected_count=len(new_r.affected_components) if new_r else 0,
            ))

        # Build rows sorted by transition priority
        sorted_changes = sorted(
            changes,
            key=lambda c: (
                _TRANSITION_ORDER.get(c.transition, 99),
                _rule_sort_key(c.rule_id),
            ),
        )

        rows: list[dict] = []
        for ch in sorted_changes:
            rows.append({
                "Rule ID": ch.rule_id,
                "Category": ch.category,
                "Description": ch.description,
                "Old Status": ch.old_status or "--",
                "New Status": ch.new_status or "--",
                "Transition": ch.transition.value,
                "Old Message": ch.old_message,
                "New Message": ch.new_message,
                "Old Affected #": ch.old_affected_count,
                "New Affected #": ch.new_affected_count,
            })

        # Transition counts for overview
        counts: dict[str, int] = {}
        for ch in changes:
            key = ch.transition.value
            counts[key] = counts.get(key, 0) + 1

        fixed = counts.get("FIXED", 0)
        regressed = counts.get("REGRESSED", 0)
        still_fail = counts.get("STILL_FAIL", 0)
        still_pass = counts.get("STILL_PASS", 0)

        summary = (
            f"Fixed: {fixed}, Regressed: {regressed}, "
            f"Still Failing: {still_fail}, Still Passing: {still_pass}"
        )

        sheets = [
            SheetConfig(
                sheet_name="Checklist Diff",
                title="Checklist Result Comparison",
                columns=list(_CKL_COLUMNS),
                rows=rows,
                stats=counts,
            ),
        ]

        return ComparisonResult(
            comparator_id=self.comparator_id,
            title=self.title,
            summary=summary,
            sheet_configs=sheets,
        )
