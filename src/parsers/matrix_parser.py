"""Parser for the matrix/matrix file defining layer stackup."""

from __future__ import annotations

from pathlib import Path

from src.models import MatrixLayer, MatrixStep
from src.parsers.base_parser import read_file


def parse_matrix(path: Path) -> tuple[list[MatrixStep], list[MatrixLayer]]:
    """Parse the matrix file.

    Returns:
        (steps, layers) sorted by COL and ROW respectively.
    """
    lines = read_file(path)
    steps = []
    layers = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line == "STEP {" or line.startswith("STEP") and "{" in line:
            block, i = _parse_block(lines, i)
            step = MatrixStep(
                col=int(block.get("COL", 0)),
                name=block.get("NAME", "").lower(),
                id=int(block.get("ID", 0)),
            )
            steps.append(step)
            continue

        if line == "LAYER {" or line.startswith("LAYER") and "{" in line:
            block, i = _parse_block(lines, i)
            layer = MatrixLayer(
                row=int(block.get("ROW", 0)),
                name=block.get("NAME", "").lower(),
                context=block.get("CONTEXT", "BOARD"),
                type=block.get("TYPE", "SIGNAL"),
                polarity=block.get("POLARITY", "POSITIVE"),
                add_type=block.get("ADD_TYPE", ""),
                start_name=block.get("START_NAME", ""),
                end_name=block.get("END_NAME", ""),
                old_name=block.get("OLD_NAME", ""),
                color=block.get("COLOR", ""),
                id=int(block.get("ID", 0)),
                form=block.get("FORM", ""),
                dielectric_type=block.get("DIELECTRIC_TYPE", ""),
                dielectric_name=block.get("DIELECTRIC_NAME", ""),
                cu_top=block.get("CU_TOP", ""),
                cu_bottom=block.get("CU_BOTTOM", ""),
            )
            layers.append(layer)
            continue

        i += 1

    steps.sort(key=lambda s: s.col)
    layers.sort(key=lambda l: l.row)

    return steps, layers


def _parse_block(lines: list[str], start_idx: int) -> tuple[dict[str, str], int]:
    """Parse a STEP { ... } or LAYER { ... } block.

    Handles both multi-line and single-line block formats.
    """
    block = {}
    i = start_idx
    line = lines[i].strip()

    # Check if opening brace is on the same line
    if "{" in line:
        # Check if closing brace is also on this line (single-line block)
        if "}" in line:
            inner = line[line.index("{") + 1:line.index("}")].strip()
            for part in inner.split():
                if "=" in part:
                    key, _, value = part.partition("=")
                    block[key.strip()] = value.strip()
            return block, i + 1

        i += 1  # Move past the line with opening brace
    else:
        # Opening brace on next line
        i += 1
        if i < len(lines) and lines[i].strip() == "{":
            i += 1

    # Parse key=value pairs until closing brace
    while i < len(lines):
        line = lines[i].strip()
        if line == "}":
            return block, i + 1
        if "=" in line:
            key, _, value = line.partition("=")
            block[key.strip()] = value.strip()
        i += 1

    return block, i
