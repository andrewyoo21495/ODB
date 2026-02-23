"""
EDA Parser
Parses the ODB++ eda/data file to extract net, package, and pin connectivity data.
"""

import re
from typing import Dict, List, Optional, Tuple
from models import Net, Pin


class EDAParser:
    """Parses the eda/data file containing NET, CMP, PKG, PIN, SNT records."""

    def parse(self, file_path: str) -> Tuple[Dict[str, Net], Dict[int, str]]:
        """
        Parse the EDA data file.

        Returns:
            (nets_by_name, net_idx_to_name)
            - nets_by_name: {net_name: Net}
            - net_idx_to_name: {net_index: net_name}
        """
        lines = self._read_lines(file_path)
        return self._parse_records(lines)

    @staticmethod
    def _read_lines(path: str) -> List[str]:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.readlines()

    def _parse_records(
        self, lines: List[str]
    ) -> Tuple[Dict[str, Net], Dict[int, str]]:
        nets_by_name: Dict[str, Net] = {}
        net_idx_to_name: Dict[int, str] = {}

        # Tracking state
        current_net: Optional[Net] = None
        net_index = 0
        pkg_table: Dict[str, dict] = {}      # pkg_name -> {pin_num: info}
        current_pkg_name: Optional[str] = None
        current_comp_net_map: Dict[str, int] = {}  # pin_num -> net_idx

        for raw in lines:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue

            main = line.split(';')[0].rstrip()
            tokens = main.split()
            if not tokens:
                continue

            rec_type = tokens[0].upper()

            if rec_type == 'NET':
                # NET <net_name>
                if len(tokens) >= 2:
                    name = tokens[1]
                    current_net = Net(index=net_index, name=name)
                    nets_by_name[name] = current_net
                    net_idx_to_name[net_index] = name
                    net_index += 1

            elif rec_type == 'SNT':
                # SNT <subnet_name> - subnet within current net (ignored for basic use)
                pass

            elif rec_type == 'PKG':
                # PKG <pkg_name> <num_pins> [<pkg_type>]
                if len(tokens) >= 2:
                    current_pkg_name = tokens[1]
                    pkg_table[current_pkg_name] = {}

            elif rec_type == 'PIN':
                # PIN <pin_num> <x> <y> [additional fields]
                if current_pkg_name is not None and len(tokens) >= 4:
                    try:
                        pin_num = tokens[1]
                        x = float(tokens[2])
                        y = float(tokens[3])
                        pkg_table[current_pkg_name][pin_num] = {'x': x, 'y': y}
                    except ValueError:
                        pass

            elif rec_type == 'CMP':
                # CMP <cmp_idx> <pkg_ref> <refdes> <net_idx_list...>
                # In EDA context, CMP record maps component pins to nets
                # Format varies; skip complex parsing for now
                pass

        return nets_by_name, net_idx_to_name

    def resolve_pin_nets(
        self,
        components,
        net_idx_to_name: Dict[int, str],
    ) -> None:
        """
        Post-process: assign net_name to each Pin based on net_idx_to_name map.
        Operates in-place on the given component list.
        """
        for comp in components:
            for pin in comp.pins:
                pin.net_name = net_idx_to_name.get(pin.net_index)
