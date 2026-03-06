"""Parser for step header files."""

from __future__ import annotations

from pathlib import Path

from src.models import StepHeader, StepRepeat
from src.parsers.base_parser import read_file


def parse_stephdr(path: Path) -> StepHeader:
    """Parse the stephdr file."""
    lines = read_file(path)
    header = StepHeader()
    step_repeats = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith("UNITS="):
            val = line.split("=", 1)[1].strip().upper()
            header.units = "MM" if val in ("MM", "M") else "INCH"
        elif line.startswith("U "):
            parts = line.split()
            if len(parts) >= 2:
                token = parts[1].upper()
                if token == "I":
                    header.units = "INCH"
                elif token in ("M", "MM"):
                    header.units = "MM"
        elif line.startswith("X_DATUM="):
            header.x_datum = float(line.split("=", 1)[1])
        elif line.startswith("Y_DATUM="):
            header.y_datum = float(line.split("=", 1)[1])
        elif line.startswith("X_ORIGIN="):
            header.x_origin = float(line.split("=", 1)[1])
        elif line.startswith("Y_ORIGIN="):
            header.y_origin = float(line.split("=", 1)[1])
        elif line.startswith("TOP_ACTIVE="):
            header.top_active = float(line.split("=", 1)[1])
        elif line.startswith("BOTTOM_ACTIVE="):
            header.bottom_active = float(line.split("=", 1)[1])
        elif line.startswith("RIGHT_ACTIVE="):
            header.right_active = float(line.split("=", 1)[1])
        elif line.startswith("LEFT_ACTIVE="):
            header.left_active = float(line.split("=", 1)[1])
        elif line.startswith("AFFECTING_BOM="):
            header.affecting_bom = line.split("=", 1)[1]
        elif line.startswith("AFFECTING_BOM_CHANGED="):
            header.affecting_bom_changed = int(line.split("=", 1)[1])
        elif line.startswith("ID="):
            header.id = int(line.split("=", 1)[1])
        elif line == "STEP-REPEAT {" or (line.startswith("STEP-REPEAT") and "{" in line):
            sr, i = _parse_step_repeat(lines, i)
            step_repeats.append(sr)
            continue

        i += 1

    header.step_repeats = step_repeats
    return header


def _parse_step_repeat(lines: list[str], start_idx: int) -> tuple[StepRepeat, int]:
    """Parse a STEP-REPEAT { ... } block."""
    sr = StepRepeat()
    i = start_idx + 1

    while i < len(lines):
        line = lines[i].strip()
        if line == "}":
            return sr, i + 1

        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            if key == "NAME":
                sr.name = value
            elif key == "X":
                sr.x = float(value)
            elif key == "Y":
                sr.y = float(value)
            elif key == "DX":
                sr.dx = float(value)
            elif key == "DY":
                sr.dy = float(value)
            elif key == "NX":
                sr.nx = int(value)
            elif key == "NY":
                sr.ny = int(value)
            elif key == "ANGLE":
                sr.angle = float(value)
            elif key == "FLIP":
                sr.flip = value.upper() == "YES"
            elif key == "MIRROR":
                sr.mirror = value.upper() == "YES"

        i += 1

    return sr, i
