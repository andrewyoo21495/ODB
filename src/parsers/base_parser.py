"""Shared parsing utilities for ODB++ files.

Provides common functions for reading files, parsing structured text,
symbol tables, attribute lookups, and contour geometry.
"""

from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path
from typing import Optional, Union

from src.models import (
    ArcSegment, Contour, FeaturePolarity, LineSegment, Point, SymbolRef, Surface,
)


def read_file(path: Path) -> list[str]:
    """Read an ODB++ file, handling .Z compression and stripping comments."""
    if not path.exists():
        # Try with .Z extension
        z_path = path.with_suffix(path.suffix + ".Z") if path.suffix else Path(str(path) + ".Z")
        if z_path.exists():
            path = z_path
        else:
            raise FileNotFoundError(f"File not found: {path}")

    if str(path).endswith(".Z"):
        return _read_compressed(path)

    text = path.read_text(encoding="utf-8", errors="replace")
    return _filter_lines(text.splitlines())


def _read_compressed(path: Path) -> list[str]:
    """Read a UNIX .Z compressed file (LZW compression)."""
    raw = path.read_bytes()
    try:
        # Try standard zlib decompression first
        text = zlib.decompress(raw).decode("utf-8", errors="replace")
    except zlib.error:
        # UNIX compress (.Z) uses LZW - try ncompress-style decompression
        text = _decompress_unix_z(raw).decode("utf-8", errors="replace")
    return _filter_lines(text.splitlines())


def _decompress_unix_z(data: bytes) -> bytes:
    """Decompress UNIX .Z (LZW) compressed data.

    The .Z format starts with a 3-byte header:
    - bytes 0-1: magic number 0x1F 0x9D
    - byte 2: flags (max bits in bits 0-4, block mode in bit 7)
    """
    if len(data) < 3 or data[0] != 0x1F or data[1] != 0x9D:
        raise ValueError("Not a valid UNIX .Z compressed file")

    maxbits = data[2] & 0x1F
    block_mode = bool(data[2] & 0x80)

    if maxbits > 16:
        raise ValueError(f"Unsupported max bits: {maxbits}")

    # LZW decompression
    clear_code = 256 if block_mode else -1
    next_code = 257 if block_mode else 256

    # Initialize dictionary with single-byte entries
    dictionary = {i: bytes([i]) for i in range(256)}

    result = bytearray()
    bits_in_buffer = 0
    buffer = 0
    nbits = 9  # Start with 9-bit codes
    pos = 3    # Skip header

    prev_entry = b""
    first = True

    while pos < len(data) or bits_in_buffer >= nbits:
        # Read enough bytes into the buffer
        while bits_in_buffer < nbits and pos < len(data):
            buffer |= data[pos] << bits_in_buffer
            bits_in_buffer += 8
            pos += 1

        if bits_in_buffer < nbits:
            break

        code = buffer & ((1 << nbits) - 1)
        buffer >>= nbits
        bits_in_buffer -= nbits

        if block_mode and code == clear_code:
            # Reset dictionary
            next_code = 257
            nbits = 9
            dictionary = {i: bytes([i]) for i in range(256)}
            prev_entry = b""
            first = True
            continue

        if first:
            if code > 255:
                raise ValueError(f"Invalid first code: {code}")
            result.extend(dictionary[code])
            prev_entry = dictionary[code]
            first = False
            continue

        if code in dictionary:
            entry = dictionary[code]
        elif code == next_code:
            entry = prev_entry + prev_entry[:1]
        else:
            raise ValueError(f"Invalid LZW code: {code}, next_code: {next_code}")

        result.extend(entry)

        if next_code < (1 << maxbits):
            dictionary[next_code] = prev_entry + entry[:1]
            next_code += 1
            if next_code >= (1 << nbits) and nbits < maxbits:
                nbits += 1

        prev_entry = entry

    return bytes(result)


def _filter_lines(lines: list[str]) -> list[str]:
    """Strip comments and blank trailing whitespace."""
    result = []
    for line in lines:
        stripped = line.rstrip()
        if stripped and not stripped.startswith("#"):
            result.append(stripped)
    return result


def parse_units(lines: list[str]) -> str:
    """Extract UNITS=MM|INCH from lines."""
    for line in lines:
        if line.startswith("UNITS="):
            return line.split("=", 1)[1].strip()
    return "INCH"


def parse_structured_text(lines: list[str]) -> dict:
    """Parse structured text format: KEY=VALUE pairs and NAME { ... } blocks.

    Returns a dict where simple keys map to values, and block names
    map to lists of dicts (since blocks can repeat).
    """
    result = {}
    i = 0
    while i < len(lines):
        line = lines[i]

        # Check for block start: NAME {
        if i + 1 < len(lines) and lines[i + 1].strip() == "{":
            block_name = line.strip()
            block_data = {}
            i += 2  # Skip name and opening brace
            while i < len(lines) and lines[i].strip() != "}":
                kv_line = lines[i].strip()
                if "=" in kv_line:
                    key, _, value = kv_line.partition("=")
                    block_data[key.strip()] = value.strip()
                i += 1
            i += 1  # Skip closing brace
            result.setdefault(block_name, []).append(block_data)
            continue

        # Single-line block: NAME { KEY=VALUE ... }
        match = re.match(r"^(\w[\w-]*)\s*\{(.+)\}\s*$", line)
        if match:
            block_name = match.group(1)
            inner = match.group(2).strip()
            block_data = {}
            for part in re.split(r"\s+", inner):
                if "=" in part:
                    key, _, value = part.partition("=")
                    block_data[key.strip()] = value.strip()
            result.setdefault(block_name, []).append(block_data)
            i += 1
            continue

        # Simple KEY=VALUE
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()

        i += 1

    return result


def parse_key_value(lines: list[str]) -> dict[str, str]:
    """Parse simple KEY=VALUE lines, ignoring block structures."""
    result = {}
    for line in lines:
        if "=" in line and not line.strip().startswith(("@", "&", "$")):
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def parse_symbol_table(lines: list[str]) -> list[SymbolRef]:
    """Parse $N <symbol_name> [I|M] entries from lines."""
    symbols = []
    for line in lines:
        if not line.startswith("$"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            idx = int(parts[0][1:])  # Remove '$' prefix
        except ValueError:
            continue
        name = parts[1]
        unit_override = None
        if len(parts) >= 3 and parts[2] in ("I", "M"):
            unit_override = parts[2]
        symbols.append(SymbolRef(index=idx, name=name, unit_override=unit_override))
    return symbols


def parse_attr_lookup(lines: list[str]) -> tuple[dict[int, str], dict[int, str]]:
    """Parse @N <name> and &N <value> attribute lookup tables."""
    attr_names = {}
    attr_texts = {}
    for line in lines:
        if line.startswith("@"):
            parts = line.split(None, 1)
            if len(parts) == 2:
                try:
                    idx = int(parts[0][1:])
                    attr_names[idx] = parts[1]
                except ValueError:
                    pass
        elif line.startswith("&"):
            parts = line.split(None, 1)
            if len(parts) == 2:
                try:
                    idx = int(parts[0][1:])
                    attr_texts[idx] = parts[1]
                except ValueError:
                    pass
    return attr_names, attr_texts


def parse_attributes(attr_str: str, attr_names: dict[int, str] = None,
                     attr_texts: dict[int, str] = None) -> tuple[dict, Optional[int]]:
    """Parse ';attr_assignments;ID=uid' suffix from a record line.

    Returns (attributes_dict, uid_or_None).
    The attr_str is the portion of the line after the main fields,
    starting with ';'.
    """
    attributes = {}
    uid = None

    if not attr_str:
        return attributes, uid

    # Strip leading/trailing semicolons and split
    parts = attr_str.split(";")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith("ID="):
            try:
                uid = int(part[3:])
            except ValueError:
                pass
            continue

        # Parse attribute assignments: comma-separated
        for assignment in part.split(","):
            assignment = assignment.strip()
            if not assignment:
                continue
            if "=" in assignment:
                idx_str, _, val_str = assignment.partition("=")
                try:
                    idx = int(idx_str)
                    name = attr_names.get(idx, str(idx)) if attr_names else str(idx)
                    # Try to resolve text values
                    if attr_texts:
                        try:
                            text_idx = int(val_str)
                            if text_idx in attr_texts:
                                attributes[name] = attr_texts[text_idx]
                                continue
                        except ValueError:
                            pass
                    attributes[name] = val_str
                except ValueError:
                    pass
            else:
                # Boolean attribute (just index = true)
                try:
                    idx = int(assignment)
                    name = attr_names.get(idx, str(idx)) if attr_names else str(idx)
                    attributes[name] = True
                except ValueError:
                    pass

    return attributes, uid


def split_record_and_attrs(line: str) -> tuple[str, str]:
    """Split a feature record line into main fields and attribute suffix.

    Returns (main_fields, attr_suffix).
    The attr_suffix includes the leading semicolon.
    """
    # Find the first semicolon that separates fields from attributes
    idx = line.find(";")
    if idx == -1:
        return line, ""
    return line[:idx].rstrip(), line[idx:]


def parse_contour(lines: list[str], start_idx: int) -> tuple[Contour, int]:
    """Parse an OB...OE contour block.

    Args:
        lines: All lines of the file
        start_idx: Index of the OB line

    Returns:
        (Contour, next_line_index)
    """
    line = lines[start_idx]
    parts = line.split()
    # OB <x> <y> I|H
    x = float(parts[1])
    y = float(parts[2])
    is_island = parts[3] == "I"

    contour = Contour(is_island=is_island, start=Point(x, y))
    i = start_idx + 1

    while i < len(lines):
        line = lines[i]
        parts = line.split()

        if parts[0] == "OE":
            return contour, i + 1

        if parts[0] == "OS":
            # OS <x> <y>
            contour.segments.append(LineSegment(end=Point(float(parts[1]), float(parts[2]))))
        elif parts[0] == "OC":
            # OC <xe> <ye> <xc> <yc> Y|N
            contour.segments.append(ArcSegment(
                end=Point(float(parts[1]), float(parts[2])),
                center=Point(float(parts[3]), float(parts[4])),
                clockwise=parts[5] == "Y",
            ))

        i += 1

    return contour, i


def parse_surface(lines: list[str], start_idx: int,
                  attr_names: dict = None, attr_texts: dict = None) -> tuple[Surface, int]:
    """Parse an S...SE surface block.

    Args:
        lines: All lines of the file
        start_idx: Index of the S line

    Returns:
        (Surface, next_line_index)
    """
    line = lines[start_idx]
    main_part, attr_suffix = split_record_and_attrs(line)
    parts = main_part.split()

    # S <polarity> <dcode>
    polarity = FeaturePolarity(parts[1]) if len(parts) > 1 else FeaturePolarity.P
    attributes, uid = parse_attributes(attr_suffix, attr_names, attr_texts)

    surface = Surface(polarity=polarity, contours=[])
    i = start_idx + 1

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped == "SE":
            return surface, i + 1

        if stripped.startswith("OB"):
            contour, i = parse_contour(lines, i)
            surface.contours.append(contour)
        else:
            i += 1

    return surface, i


def parse_orient(parts: list[str], orient_start_idx: int) -> tuple[float, bool]:
    """Parse pad orientation from record fields.

    Orient values:
        0-3: 0/90/180/270 degrees, no mirror
        4-7: 0/90/180/270 degrees, mirrored
        8 <angle>: arbitrary angle, no mirror
        9 <angle>: arbitrary angle, mirrored

    Returns (rotation_degrees, is_mirrored).
    """
    orient_val = int(parts[orient_start_idx])

    if orient_val <= 3:
        return orient_val * 90.0, False
    elif orient_val <= 7:
        return (orient_val - 4) * 90.0, True
    elif orient_val == 8:
        angle = float(parts[orient_start_idx + 1])
        return angle, False
    elif orient_val == 9:
        angle = float(parts[orient_start_idx + 1])
        return angle, True
    else:
        return 0.0, False
