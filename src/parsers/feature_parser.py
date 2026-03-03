"""Parser for layer feature files - the core geometry parser.

Handles L (line), P (pad), A (arc), T (text), B (barcode), S (surface) records.
"""

from __future__ import annotations

from pathlib import Path

from src.models import (
    ArcRecord, BarcodeRecord, Contour, FeaturePolarity, LayerFeatures,
    LineRecord, PadRecord, SurfaceRecord, TextRecord,
)
from src.parsers.base_parser import (
    parse_attr_lookup, parse_attributes, parse_contour, parse_orient,
    parse_symbol_table, parse_units, read_file, split_record_and_attrs,
)


def parse_features(path: Path) -> LayerFeatures:
    """Parse a layer features file.

    Handles the full feature format including symbol table,
    attribute lookup tables, and all feature record types.
    """
    lines = read_file(path)
    layer = LayerFeatures()
    layer.units = parse_units(lines)

    # Parse header fields
    for line in lines:
        if line.startswith("ID="):
            try:
                layer.id = int(line.split("=", 1)[1])
            except ValueError:
                pass
        elif line.startswith("F "):
            try:
                layer.feature_count = int(line.split()[1])
            except (ValueError, IndexError):
                pass

    # Parse symbol table, attribute lookups
    layer.symbols = parse_symbol_table(lines)
    layer.attr_names, layer.attr_texts = parse_attr_lookup(lines)

    # Parse feature records
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue

        first_char = line[0]

        if first_char == "L":
            record = _parse_line_record(line, layer.attr_names, layer.attr_texts)
            if record:
                layer.features.append(record)
            i += 1

        elif first_char == "P":
            # Make sure it's a pad record, not a keyword like "POLARITY"
            if len(line) > 1 and line[1] == " ":
                record = _parse_pad_record(line, layer.attr_names, layer.attr_texts)
                if record:
                    layer.features.append(record)
            i += 1

        elif first_char == "A":
            if len(line) > 1 and line[1] == " ":
                record = _parse_arc_record(line, layer.attr_names, layer.attr_texts)
                if record:
                    layer.features.append(record)
            i += 1

        elif first_char == "T":
            if len(line) > 1 and line[1] == " ":
                record = _parse_text_record(line, layer.attr_names, layer.attr_texts)
                if record:
                    layer.features.append(record)
            i += 1

        elif first_char == "B":
            if len(line) > 1 and line[1] == " ":
                record = _parse_barcode_record(line, layer.attr_names, layer.attr_texts)
                if record:
                    layer.features.append(record)
            i += 1

        elif first_char == "S":
            if len(line) > 1 and line[1] == " ":
                record, i = _parse_surface_record(lines, i, layer.attr_names, layer.attr_texts)
                if record:
                    layer.features.append(record)
            else:
                i += 1
        else:
            i += 1

    return layer


def _parse_line_record(line: str, attr_names: dict, attr_texts: dict) -> LineRecord | None:
    """Parse: L <xs> <ys> <xe> <ye> <sym_num> <polarity> <dcode>;attrs;ID=uid"""
    try:
        main_part, attr_suffix = split_record_and_attrs(line)
        parts = main_part.split()
        if len(parts) < 7:
            return None

        attributes, uid = parse_attributes(attr_suffix, attr_names, attr_texts)

        return LineRecord(
            xs=float(parts[1]),
            ys=float(parts[2]),
            xe=float(parts[3]),
            ye=float(parts[4]),
            symbol_idx=int(parts[5]),
            polarity=FeaturePolarity(parts[6]),
            dcode=int(parts[7]) if len(parts) > 7 else 0,
            attributes=attributes,
            id=uid,
        )
    except (ValueError, IndexError):
        return None


def _parse_pad_record(line: str, attr_names: dict, attr_texts: dict) -> PadRecord | None:
    """Parse: P <x> <y> <apt_def> <polarity> <dcode> <orient_def>;attrs;ID=uid

    apt_def is either <sym_num> or -1 <sym_num> <resize_factor>
    orient_def is 0-7 or 8/9 <angle>
    """
    try:
        main_part, attr_suffix = split_record_and_attrs(line)
        parts = main_part.split()
        if len(parts) < 6:
            return None

        x = float(parts[1])
        y = float(parts[2])

        # Parse aperture definition
        idx = 3
        resize_factor = None
        if parts[idx] == "-1":
            # Resized symbol: -1 <sym_num> <resize_factor>
            sym_idx = int(parts[idx + 1])
            resize_factor = float(parts[idx + 2])
            idx += 3
        else:
            sym_idx = int(parts[idx])
            idx += 1

        polarity = FeaturePolarity(parts[idx])
        idx += 1
        dcode = int(parts[idx])
        idx += 1

        # Parse orientation
        rotation, mirror = parse_orient(parts, idx)

        attributes, uid = parse_attributes(attr_suffix, attr_names, attr_texts)

        return PadRecord(
            x=x, y=y,
            symbol_idx=sym_idx,
            polarity=polarity,
            dcode=dcode,
            rotation=rotation,
            mirror=mirror,
            resize_factor=resize_factor,
            attributes=attributes,
            id=uid,
        )
    except (ValueError, IndexError):
        return None


def _parse_arc_record(line: str, attr_names: dict, attr_texts: dict) -> ArcRecord | None:
    """Parse: A <xs> <ys> <xe> <ye> <xc> <yc> <sym_num> <pol> <dcode> <cw>;attrs;ID=uid"""
    try:
        main_part, attr_suffix = split_record_and_attrs(line)
        parts = main_part.split()
        if len(parts) < 10:
            return None

        attributes, uid = parse_attributes(attr_suffix, attr_names, attr_texts)

        return ArcRecord(
            xs=float(parts[1]),
            ys=float(parts[2]),
            xe=float(parts[3]),
            ye=float(parts[4]),
            xc=float(parts[5]),
            yc=float(parts[6]),
            symbol_idx=int(parts[7]),
            polarity=FeaturePolarity(parts[8]),
            dcode=int(parts[9]),
            clockwise=parts[10] == "Y" if len(parts) > 10 else True,
            attributes=attributes,
            id=uid,
        )
    except (ValueError, IndexError):
        return None


def _parse_text_record(line: str, attr_names: dict, attr_texts: dict) -> TextRecord | None:
    """Parse: T <x> <y> <font> <pol> <orient> <xsize> <ysize> <wf> <text> <ver>;attrs;ID=uid"""
    try:
        main_part, attr_suffix = split_record_and_attrs(line)

        # Text field is quoted - need special handling
        # Find the quoted text string
        quote_start = main_part.find("'")
        if quote_start == -1:
            return None
        quote_end = main_part.find("'", quote_start + 1)
        if quote_end == -1:
            return None

        text = main_part[quote_start + 1:quote_end]

        # Parse fields before the quoted text
        before_text = main_part[:quote_start].strip()
        parts_before = before_text.split()

        # Parse fields after the quoted text
        after_text = main_part[quote_end + 1:].strip()
        parts_after = after_text.split() if after_text else []

        if len(parts_before) < 5:
            return None

        x = float(parts_before[1])
        y = float(parts_before[2])
        font = parts_before[3]
        polarity = FeaturePolarity(parts_before[4])

        # Parse orientation
        orient_idx = 5
        rotation, mirror = parse_orient(parts_before, orient_idx)
        orient_consumed = 2 if int(parts_before[orient_idx]) >= 8 else 1
        param_idx = orient_idx + orient_consumed

        xsize = float(parts_before[param_idx]) if param_idx < len(parts_before) else 0.0
        ysize = float(parts_before[param_idx + 1]) if param_idx + 1 < len(parts_before) else 0.0
        width_factor = float(parts_before[param_idx + 2]) if param_idx + 2 < len(parts_before) else 1.0

        version = int(parts_after[0]) if parts_after else 0

        attributes, uid = parse_attributes(attr_suffix, attr_names, attr_texts)

        return TextRecord(
            x=x, y=y,
            font=font,
            polarity=polarity,
            rotation=rotation,
            mirror=mirror,
            xsize=xsize,
            ysize=ysize,
            width_factor=width_factor,
            text=text,
            version=version,
            attributes=attributes,
            id=uid,
        )
    except (ValueError, IndexError):
        return None


def _parse_barcode_record(line: str, attr_names: dict, attr_texts: dict) -> BarcodeRecord | None:
    """Parse barcode record. These are rare - basic implementation."""
    try:
        main_part, attr_suffix = split_record_and_attrs(line)

        # Find quoted text
        quote_start = main_part.find("'")
        text = ""
        if quote_start != -1:
            quote_end = main_part.find("'", quote_start + 1)
            if quote_end != -1:
                text = main_part[quote_start + 1:quote_end]

        parts = main_part.split()
        attributes, uid = parse_attributes(attr_suffix, attr_names, attr_texts)

        return BarcodeRecord(
            x=float(parts[1]) if len(parts) > 1 else 0.0,
            y=float(parts[2]) if len(parts) > 2 else 0.0,
            barcode=parts[3] if len(parts) > 3 else "",
            font=parts[4] if len(parts) > 4 else "",
            polarity=FeaturePolarity(parts[5]) if len(parts) > 5 else FeaturePolarity.P,
            text=text,
            attributes=attributes,
            id=uid,
        )
    except (ValueError, IndexError):
        return None


def _parse_surface_record(lines: list[str], start_idx: int,
                          attr_names: dict, attr_texts: dict) -> tuple[SurfaceRecord | None, int]:
    """Parse: S <polarity> <dcode>;attrs;ID=uid followed by OB/OS/OC/OE blocks ending with SE."""
    try:
        line = lines[start_idx]
        main_part, attr_suffix = split_record_and_attrs(line)
        parts = main_part.split()

        polarity = FeaturePolarity(parts[1]) if len(parts) > 1 else FeaturePolarity.P
        dcode = int(parts[2]) if len(parts) > 2 else 0
        attributes, uid = parse_attributes(attr_suffix, attr_names, attr_texts)

        contours = []
        i = start_idx + 1

        while i < len(lines):
            line = lines[i].strip()

            if line == "SE":
                return SurfaceRecord(
                    polarity=polarity,
                    dcode=dcode,
                    contours=contours,
                    attributes=attributes,
                    id=uid,
                ), i + 1

            if line.startswith("OB"):
                contour, i = parse_contour(lines, i)
                contours.append(contour)
            else:
                i += 1

        return SurfaceRecord(
            polarity=polarity,
            dcode=dcode,
            contours=contours,
            attributes=attributes,
            id=uid,
        ), i

    except (ValueError, IndexError):
        return None, start_idx + 1
