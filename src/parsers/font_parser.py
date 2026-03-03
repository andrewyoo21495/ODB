"""Parser for fonts/standard stroke font file."""

from __future__ import annotations

from pathlib import Path

from src.models import FontChar, FontStroke, StrokeFont
from src.parsers.base_parser import read_file


def parse_font(path: Path) -> StrokeFont:
    """Parse the standard stroke font file.

    Format:
        XSIZE <float>
        YSIZE <float>
        OFFSET <float>
        CHAR <c>
        LINE <x1> <y1> <x2> <y2> <polarity> <shape> <width>
        ECHAR
    """
    lines = read_file(path)
    font = StrokeFont()
    current_char = None

    for line in lines:
        parts = line.split()
        if not parts:
            continue

        if parts[0] == "XSIZE":
            font.xsize = float(parts[1])
        elif parts[0] == "YSIZE":
            font.ysize = float(parts[1])
        elif parts[0] == "OFFSET":
            font.offset = float(parts[1])
        elif parts[0] == "CHAR":
            char_val = line[5:].strip() if len(line) > 5 else ""
            # Handle special cases: space character
            if not char_val:
                char_val = " "
            current_char = FontChar(char=char_val)
        elif parts[0] == "LINE" and current_char is not None:
            stroke = FontStroke(
                x1=float(parts[1]),
                y1=float(parts[2]),
                x2=float(parts[3]),
                y2=float(parts[4]),
                polarity=parts[5] if len(parts) > 5 else "P",
                shape=parts[6] if len(parts) > 6 else "R",
                width=float(parts[7]) if len(parts) > 7 else 0.012,
            )
            current_char.strokes.append(stroke)
        elif parts[0] == "ECHAR" and current_char is not None:
            font.characters[current_char.char] = current_char
            current_char = None

    return font
