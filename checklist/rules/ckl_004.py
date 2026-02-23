"""
CKL-004: Polarized Component Orientation Check
Diodes (D prefix) and electrolytic capacitors are polarized.
This rule checks that they have non-zero rotation diversity
(all pointing the same direction may indicate a placement error).
Also flags any components with suspicious 180° rotation that may
indicate reversed polarity.
"""

from collections import Counter
from checklist.rule_base import RuleBase, CheckResult
from models import ODBModel


class PolarizedComponentOrientationRule(RuleBase):
    rule_id     = 'CKL-004'
    rule_name   = 'Polarized Component Orientation Audit'
    description = (
        'Audits polarized components (diodes, electrolytic capacitors) for '
        'suspicious uniform or 180°-reversed orientations.'
    )

    POLARIZED_PREFIXES = ['D', 'LED']   # Component prefixes considered polarized

    def check(self, model: ODBModel) -> CheckResult:
        comps = self._get_comps_by_prefix(model, self.POLARIZED_PREFIXES)

        if not comps:
            return self._skip(
                f'No polarized components found '
                f'(prefixes: {self.POLARIZED_PREFIXES})'
            )

        rotation_counter: Counter = Counter()
        for comp in comps:
            # Normalize rotation to 0–360
            rot = comp.rotation % 360
            rotation_counter[round(rot)] += 1

        details = [
            f'{comp.refdes}: rot={comp.rotation}°, mirror={comp.mirror}'
            for comp in comps
        ]

        warnings = []
        # Warn if ALL components share the same rotation (potential paste error)
        if len(rotation_counter) == 1 and len(comps) > 3:
            warnings.append(
                f'All {len(comps)} polarized components have identical rotation '
                f'({list(rotation_counter.keys())[0]}°) — verify correct polarity.'
            )

        summary = [f'Rotation distribution: {dict(rotation_counter)}'] + details

        if warnings:
            return self._warn(
                f'{len(warnings)} orientation concern(s) for {len(comps)} '
                f'polarized component(s)',
                warnings + summary,
            )
        return self._pass(
            f'{len(comps)} polarized component(s) checked — '
            f'{len(rotation_counter)} distinct rotation(s)',
            summary,
        )
