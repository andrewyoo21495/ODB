"""
Rule Registry
Manages rule registration and batch execution of checklist rules.
"""

from typing import List, TYPE_CHECKING
from .rule_base import RuleBase, CheckResult, CheckStatus

if TYPE_CHECKING:
    from models import ODBModel


class RuleRegistry:
    """Registers rules and runs them in batch against an ODBModel."""

    def __init__(self):
        self._rules: List[RuleBase] = []

    def register(self, rule: RuleBase) -> 'RuleRegistry':
        """Register a rule. Returns self for chaining."""
        self._rules.append(rule)
        return self

    def register_all(self, rules: List[RuleBase]) -> 'RuleRegistry':
        """Register multiple rules at once."""
        for rule in rules:
            self._rules.append(rule)
        return self

    def run_all(self, model: 'ODBModel', verbose: bool = False) -> List[CheckResult]:
        """
        Run all registered rules against the model.

        Args:
            model: The ODBModel to check.
            verbose: Print each result to stdout if True.

        Returns:
            List of CheckResult objects in registration order.
        """
        results = []
        for rule in self._rules:
            try:
                result = rule.check(model)
            except Exception as exc:
                result = CheckResult(
                    rule_id=rule.rule_id,
                    rule_name=rule.rule_name,
                    status=CheckStatus.FAIL,
                    message=f'Rule raised an exception: {exc}',
                )
            results.append(result)
            if verbose:
                print(result)
        return results

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    @staticmethod
    def summary(results: List[CheckResult]) -> dict:
        """Return a summary dict with counts by status."""
        counts = {s.value: 0 for s in CheckStatus}
        for r in results:
            counts[r.status.value] += 1
        return counts
