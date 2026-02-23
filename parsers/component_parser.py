"""
Component Parser
Parses ODB++ components files into Component and Pin objects.
"""

import re
from typing import List, Optional
from models import Component, Pin


class ComponentParser:
    """Parses an ODB++ components file."""

    def parse(self, file_path: str) -> List[Component]:
        """Parse the components file and return a list of Component objects."""
        lines = self._read_lines(file_path)
        return self._parse_records(lines)

    @staticmethod
    def _read_lines(path: str) -> List[str]:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.readlines()

    def _parse_records(self, lines: List[str]) -> List[Component]:
        components: List[Component] = []
        current: Optional[Component] = None
        attr_name_table = {}
        attr_str_table = {}

        for raw in lines:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue

            # Attribute tables
            if line.startswith('@'):
                m = re.match(r'^@(\d+)\s+(\S+)', line)
                if m:
                    attr_name_table[int(m.group(1))] = m.group(2)
                continue
            if line.startswith('&'):
                m = re.match(r'^&(\d+)\s+(.*)', line)
                if m:
                    attr_str_table[int(m.group(1))] = m.group(2).strip()
                continue

            main = line.split(';')[0].rstrip()
            tokens = main.split()
            if not tokens:
                continue

            rec_type = tokens[0].upper()

            if rec_type == 'CMP':
                current = self._parse_cmp(tokens)
                if current is not None:
                    components.append(current)
            elif rec_type in ('TOP', 'BOT'):
                pin = self._parse_pin(tokens)
                if pin is not None and current is not None:
                    current.pins.append(pin)
            elif rec_type == 'PRP':
                # Property record: PRP <name> <value>
                if current is not None and len(tokens) >= 3:
                    prop_name = tokens[1].upper()
                    prop_val = ' '.join(tokens[2:]).strip("'\"")
                    if prop_name in ('PN', 'PART_NUMBER'):
                        current.part_number = prop_val
                    elif prop_name in ('VALUE', 'VAL'):
                        current.value = prop_val
                    else:
                        current.attributes[prop_name] = prop_val

        return components

    @staticmethod
    def _parse_cmp(tokens: List[str]) -> Optional[Component]:
        # CMP <idx> <x> <y> <rot> <mirror> <refdes> <pkg_ref>
        if len(tokens) < 8:
            return None
        try:
            idx = int(tokens[1])
            x = float(tokens[2])
            y = float(tokens[3])
            rot = float(tokens[4])
            mirror_str = tokens[5].upper()
            mirror = mirror_str == 'Y'
            refdes = tokens[6]
            pkg_ref = tokens[7]
            return Component(
                index=idx,
                refdes=refdes,
                x=x, y=y,
                rotation=rot,
                mirror=mirror,
                package_ref=pkg_ref,
            )
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _parse_pin(tokens: List[str]) -> Optional[Pin]:
        # TOP/BOT <pin_idx> <x> <y> <rot> <mirror> <net_idx> <subnet_idx> <pin_num>
        if len(tokens) < 9:
            return None
        try:
            # pin_idx = tokens[1] (ignored, ordinal)
            x = float(tokens[2])
            y = float(tokens[3])
            rot = float(tokens[4])
            # tokens[5] = mirror (Y/N) — pin mirror
            net_idx = int(tokens[6])
            subnet_idx = int(tokens[7])
            pin_num = tokens[8]
            return Pin(
                pin_num=pin_num,
                x=x, y=y,
                rotation=rot,
                net_index=net_idx,
                subnet_index=subnet_idx,
            )
        except (ValueError, IndexError):
            return None
