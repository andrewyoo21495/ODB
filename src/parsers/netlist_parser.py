"""Parser for netlists/cadnet/netlist files."""

from __future__ import annotations

from pathlib import Path

from src.models import Netlist, NetlistHeader
from src.parsers.base_parser import read_file


def parse_netlist(path: Path) -> Netlist:
    """Parse the cadnet netlist file.

    Format:
        H optimize <y|n> [staggered <y|n>]
        $<serial_num> <net_name>
    """
    lines = read_file(path)
    netlist = Netlist()

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("UNITS="):
            continue

        if stripped.startswith("H "):
            parts = stripped.split()
            for j in range(1, len(parts) - 1):
                if parts[j] == "optimize":
                    netlist.header.optimize = parts[j + 1].lower() == "y"
                elif parts[j] == "staggered":
                    netlist.header.staggered = parts[j + 1].lower() == "y"

        elif stripped.startswith("$"):
            parts = stripped.split(None, 1)
            if len(parts) == 2:
                try:
                    idx = int(parts[0][1:])
                    netlist.net_names[idx] = parts[1]
                except ValueError:
                    pass

    return netlist
