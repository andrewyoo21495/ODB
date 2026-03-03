"""Base class for all checklist rules."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import RuleResult


class ChecklistRule(ABC):
    """Abstract base class for design checklist rules.

    Subclasses must implement:
        - rule_id: Unique identifier (e.g., "CKL-001")
        - description: Human-readable description
        - category: Category string (e.g., "placement", "spacing", "alignment")
        - evaluate(job_data): Run the check and return a RuleResult
    """

    rule_id: str = ""
    description: str = ""
    category: str = ""

    @abstractmethod
    def evaluate(self, job_data: dict) -> RuleResult:
        """Evaluate this rule against the parsed ODB++ data.

        Args:
            job_data: dict containing parsed data:
                - 'components_top': list[Component]
                - 'components_bot': list[Component]
                - 'eda_data': EdaData
                - 'profile': Profile
                - 'matrix_layers': list[MatrixLayer]
                - 'layer_features': dict[str, LayerFeatures]
                - 'job_info': JobInfo

        Returns:
            RuleResult with pass/fail status and details
        """
        raise NotImplementedError
