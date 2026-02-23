"""
CKL-001: Capacitor–Connector Opposite-Side Horizontal Alignment Check
Verifies that top-side capacitors do not have bottom-side connectors
at nearly the same Y-coordinate (which could cause assembly interference).
"""

from typing import List
from checklist.rule_base import RuleBase, CheckResult
from models import ODBModel


class CapacitorConnectorOppositeRule(RuleBase):
    rule_id   = 'CKL-001'
    rule_name = 'Capacitor-Connector Opposite-Side Horizontal Alignment'
    description = (
        'Checks that TOP-side capacitors and BOTTOM-side connectors are not '
        'horizontally aligned (same Y within tolerance), which may cause '
        'mechanical interference or assembly issues.'
    )

    CAP_PREFIX  = ['C']          # Capacitor reference designator prefixes
    CON_PREFIX  = ['J', 'CN', 'P', 'CON']  # Connector reference designator prefixes
    TOLERANCE_Y = 0.5            # Y-coordinate proximity tolerance (same units as model)

    def __init__(self, tolerance_y: float = 0.5):
        self.TOLERANCE_Y = tolerance_y

    def check(self, model: ODBModel) -> CheckResult:
        caps = self._get_comps_by_prefix(model, self.CAP_PREFIX, side='TOP')
        cons = self._get_comps_by_prefix(model, self.CON_PREFIX, side='BOTTOM')

        if not caps:
            return self._skip('No top-side capacitors found')
        if not cons:
            return self._skip('No bottom-side connectors found')

        fails: List[str] = []
        for cap in caps:
            for con in cons:
                dy = abs(cap.y - con.y)
                if dy <= self.TOLERANCE_Y:
                    fails.append(
                        f'{cap.refdes} (y={cap.y:.3f}) vs '
                        f'{con.refdes} (y={con.y:.3f}): dy={dy:.3f}'
                    )

        if fails:
            return self._fail(
                f'{len(fails)} alignment violation(s) found (tolerance={self.TOLERANCE_Y})',
                fails,
            )
        return self._pass(
            f'No alignment violations. '
            f'Checked {len(caps)} capacitor(s) vs {len(cons)} connector(s).'
        )
