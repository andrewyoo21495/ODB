"""
Rule Base
Abstract base class for all checklist rules.
Defines the common interface and result data structures.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from models import ODBModel


class CheckStatus(Enum):
    PASS    = 'PASS'
    FAIL    = 'FAIL'
    WARNING = 'WARNING'
    SKIP    = 'SKIP'      # Not applicable to this design


@dataclass
class CheckResult:
    rule_id:   str
    rule_name: str
    status:    CheckStatus
    message:   str
    details:   Optional[List] = field(default=None)

    def is_pass(self) -> bool:
        return self.status == CheckStatus.PASS

    def is_fail(self) -> bool:
        return self.status == CheckStatus.FAIL

    def __str__(self) -> str:
        return f"[{self.status.value}] {self.rule_id} — {self.rule_name}: {self.message}"


class RuleBase(ABC):
    """Abstract base class for all checklist rules."""

    rule_id:     str = ''
    rule_name:   str = ''
    description: str = ''

    @abstractmethod
    def check(self, model: 'ODBModel') -> CheckResult:
        """Execute the rule against the given ODBModel and return a CheckResult."""

    # ------------------------------------------------------------------
    # Convenience helpers for subclasses
    # ------------------------------------------------------------------

    def _pass(self, message: str = 'All checks passed') -> CheckResult:
        return CheckResult(self.rule_id, self.rule_name,
                           CheckStatus.PASS, message)

    def _fail(self, message: str, details: Optional[List] = None) -> CheckResult:
        return CheckResult(self.rule_id, self.rule_name,
                           CheckStatus.FAIL, message, details)

    def _warn(self, message: str, details: Optional[List] = None) -> CheckResult:
        return CheckResult(self.rule_id, self.rule_name,
                           CheckStatus.WARNING, message, details)

    def _skip(self, reason: str = 'Not applicable') -> CheckResult:
        return CheckResult(self.rule_id, self.rule_name,
                           CheckStatus.SKIP, reason)

    @staticmethod
    def _get_comps_by_prefix(model: 'ODBModel', prefixes: List[str],
                              side: Optional[str] = None):
        """
        Collect all components whose refdes starts with one of the given prefixes.
        Optionally filter by side ('TOP' or 'BOTTOM') based on component.mirror flag.
        """
        results = []
        for ld in model.layer_data.values():
            for comp in ld.components:
                # Side filter: mirror=True → BOTTOM, mirror=False → TOP
                if side == 'TOP' and comp.mirror:
                    continue
                if side == 'BOTTOM' and not comp.mirror:
                    continue
                ref = comp.refdes.upper()
                if any(ref.startswith(p.upper()) for p in prefixes):
                    results.append(comp)
        return results

    @staticmethod
    def _all_components(model: 'ODBModel', side: Optional[str] = None):
        """Return all components, optionally filtered by side."""
        results = []
        for ld in model.layer_data.values():
            for comp in ld.components:
                if side == 'TOP' and comp.mirror:
                    continue
                if side == 'BOTTOM' and not comp.mirror:
                    continue
                results.append(comp)
        return results
