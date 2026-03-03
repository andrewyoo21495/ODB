"""Checklist evaluation engine."""

from __future__ import annotations

from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


# Rule registry
_REGISTERED_RULES: list[type[ChecklistRule]] = []


def register_rule(rule_cls: type[ChecklistRule]) -> type[ChecklistRule]:
    """Decorator to register a checklist rule class."""
    _REGISTERED_RULES.append(rule_cls)
    return rule_cls


def get_registered_rules() -> list[type[ChecklistRule]]:
    """Get all registered rule classes."""
    return list(_REGISTERED_RULES)


def run_checklist(job_data: dict,
                  rules: list[ChecklistRule] = None) -> list[RuleResult]:
    """Run all checklist rules against parsed ODB++ data.

    Args:
        job_data: dict of parsed data (components, eda, profile, etc.)
        rules: Specific rules to run. If None, runs all registered rules.

    Returns:
        List of RuleResult objects
    """
    if rules is None:
        rules = [cls() for cls in _REGISTERED_RULES]

    results = []
    for rule in rules:
        try:
            result = rule.evaluate(job_data)
            results.append(result)
        except Exception as e:
            results.append(RuleResult(
                rule_id=rule.rule_id,
                description=rule.description,
                category=rule.category,
                passed=False,
                message=f"Rule evaluation error: {e}",
            ))

    return results


def load_rules(rule_ids: list[str] = None) -> list[ChecklistRule]:
    """Load and instantiate rules, optionally filtered by ID.

    Args:
        rule_ids: List of rule IDs to load. If None, loads all.

    Returns:
        List of instantiated rule objects
    """
    all_rules = [cls() for cls in _REGISTERED_RULES]

    if rule_ids is None:
        return all_rules

    return [r for r in all_rules if r.rule_id in rule_ids]
