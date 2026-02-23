"""
CKL-002: Minimum Component Spacing Check
Uses a KDTree to find component pairs that violate the minimum center-to-center
distance requirement on the same side of the board.
"""

from typing import List, Tuple
from checklist.rule_base import RuleBase, CheckResult
from models import ODBModel


class MinSpacingRule(RuleBase):
    rule_id      = 'CKL-002'
    rule_name    = 'Minimum Component Spacing'
    description  = (
        'Checks that no two components on the same board side have a center-to-center '
        'distance smaller than the minimum spacing threshold.'
    )

    MIN_DISTANCE = 0.2  # Minimum center-to-center distance (same units as model)

    def __init__(self, min_distance: float = 0.2):
        self.MIN_DISTANCE = min_distance

    def check(self, model: ODBModel) -> CheckResult:
        try:
            import numpy as np
            from scipy.spatial import KDTree
        except ImportError:
            return self._skip('scipy/numpy not available — install with: pip install scipy numpy')

        results_all: List[str] = []

        for side, is_mirror in (('TOP', False), ('BOTTOM', True)):
            comps = [
                c for ld in model.layer_data.values()
                for c in ld.components
                if c.mirror == is_mirror
            ]
            if len(comps) < 2:
                continue

            positions = np.array([[c.x, c.y] for c in comps])
            tree = KDTree(positions)
            pairs = tree.query_pairs(self.MIN_DISTANCE)

            for i, j in pairs:
                dist = float(np.linalg.norm(positions[i] - positions[j]))
                results_all.append(
                    f'{side}: {comps[i].refdes} ↔ {comps[j].refdes} '
                    f'dist={dist:.4f} (min={self.MIN_DISTANCE})'
                )

        if results_all:
            return self._fail(
                f'{len(results_all)} spacing violation(s) found '
                f'(threshold={self.MIN_DISTANCE})',
                results_all,
            )
        return self._pass(
            f'All components satisfy minimum spacing of {self.MIN_DISTANCE}.'
        )
