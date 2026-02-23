"""
CKL-003: Component Count Check
Verifies that the board has a non-zero number of components and
reports the total count by reference prefix.
"""

from collections import Counter
from checklist.rule_base import RuleBase, CheckResult
from models import ODBModel


class ComponentCountRule(RuleBase):
    rule_id     = 'CKL-003'
    rule_name   = 'Component Count Verification'
    description = (
        'Counts all placed components and reports totals by reference prefix. '
        'Fails if no components are found.'
    )

    def check(self, model: ODBModel) -> CheckResult:
        all_comps = self._all_components(model)

        if not all_comps:
            return self._fail('No components found in the design')

        # Deduplicate by refdes (same component may appear in multiple layer data)
        seen = set()
        unique = []
        for comp in all_comps:
            if comp.refdes not in seen:
                seen.add(comp.refdes)
                unique.append(comp)

        # Count by prefix (first letter(s) of refdes)
        prefix_counter: Counter = Counter()
        for comp in unique:
            prefix = ''.join(c for c in comp.refdes if c.isalpha())
            prefix_counter[prefix] += 1

        summary_lines = [
            f'{prefix}: {count}' for prefix, count in sorted(prefix_counter.items())
        ]
        summary_lines.insert(0, f'Total unique components: {len(unique)}')

        top_count = sum(1 for c in unique if not c.mirror)
        bot_count = sum(1 for c in unique if c.mirror)
        summary_lines.append(f'Top-side: {top_count}, Bottom-side: {bot_count}')

        return self._pass(
            f'{len(unique)} component(s) found',
            summary_lines,
        )
