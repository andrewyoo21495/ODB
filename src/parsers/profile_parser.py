"""Parser for profile files (board and layer outlines)."""

from __future__ import annotations

from pathlib import Path

from src.models import Profile
from src.parsers.base_parser import parse_surface, parse_units, read_file


def parse_profile(path: Path) -> Profile:
    """Parse a profile file containing a single surface (board/layer outline)."""
    lines = read_file(path)
    units = parse_units(lines)
    profile = Profile(units=units)

    # Find the surface (S ... SE block)
    for i, line in enumerate(lines):
        if line.strip().startswith("S "):
            surface, _ = parse_surface(lines, i)
            profile.surface = surface
            break

    return profile
