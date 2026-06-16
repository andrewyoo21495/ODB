"""Checklist evaluation engine."""

from __future__ import annotations

import importlib
import pkgutil
from typing import Callable

from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult

ProgressFn = Callable[[float, str], None]


# Rule registry
_REGISTERED_RULES: list[type[ChecklistRule]] = []
_RULES_DISCOVERED = False


def register_rule(rule_cls: type[ChecklistRule]) -> type[ChecklistRule]:
    """Decorator to register a checklist rule class."""
    _REGISTERED_RULES.append(rule_cls)
    return rule_cls


def get_registered_rules() -> list[type[ChecklistRule]]:
    """Get all registered rule classes."""
    return list(_REGISTERED_RULES)


def discover_rules() -> list[type[ChecklistRule]]:
    """Import every ``ckl_*`` module in ``src.checklist.rules`` so that their
    ``@register_rule`` decorators run.

    Replaces the previous manual import list in ``main.py``: adding a new rule
    file no longer requires touching any import statement.  Idempotent — repeat
    calls are cheap no-ops.  Returns the registered rule classes.
    """
    global _RULES_DISCOVERED
    if not _RULES_DISCOVERED:
        import src.checklist.rules as rules_pkg
        for name in sorted(m.name for m in pkgutil.iter_modules(rules_pkg.__path__)):
            if name.startswith("ckl_"):
                importlib.import_module(f"{rules_pkg.__name__}.{name}")
        _RULES_DISCOVERED = True
    return get_registered_rules()


def run_checklist(job_data: dict,
                  rules: list[ChecklistRule] = None,
                  progress: ProgressFn | None = None) -> list[RuleResult]:
    """Run all checklist rules against parsed ODB++ data.

    Args:
        job_data: dict of parsed data (components, eda, profile, etc.)
        rules: Specific rules to run. If None, runs all registered rules.
        progress: optional callback ``(fraction, message)`` invoked after each
            rule, where ``fraction`` runs 0.0→1.0. Used to drive a UI progress bar.

    Returns:
        List of RuleResult objects
    """
    if rules is None:
        rules = [cls() for cls in _REGISTERED_RULES]

    results = []
    total = len(rules) or 1
    for i, rule in enumerate(rules):
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
        if progress is not None:
            progress((i + 1) / total, f"{rule.rule_id} ({i + 1}/{total})")

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
