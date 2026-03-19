"""Parser for component files (comp_+_top, comp_+_bot layers)."""

from __future__ import annotations

from pathlib import Path

from src.models import BomData, Component, Toeprint
from src.parsers.base_parser import (
    parse_attr_lookup, parse_attributes, parse_units, read_file,
    split_record_and_attrs,
)


def parse_components(path: Path) -> tuple[list[Component], str]:
    """Parse a components file.

    Format:
        UNITS=INCH
        @N <attr_name>
        &N <text_value>
        CMP <pkg_ref> <x> <y> <rot> <mirror> <comp_name> <part_name>;attrs;ID=uid
        PRP <name> '<value>'
        TOP <pin_num> <x> <y> <rot> <mirror> <net_num> <subnet_num> <toeprint_name>
        CPN <customer_part_number>
        PKG <package>
        IPN <internal_part_number>
        DSC <description>
        VPL_VND <vendor>
        VPL_MPN <mpn>
        VND <vendor>
        MPN <qualify_status> <chosen> <mpn>

    Returns:
        Tuple of (list of Component, units string e.g. "INCH" or "MM").
    """
    lines = read_file(path)
    attr_names, attr_texts = parse_attr_lookup(lines)

    units = "INCH"
    components = []
    current_comp = None
    current_bom = None
    in_bom_section = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("UNITS="):
            val = stripped[6:].strip().upper()
            units = "MM" if val in ("MM", "M") else "INCH"
            continue
        if stripped.startswith("U "):
            parts = stripped.split()
            if len(parts) >= 2:
                token = parts[1].upper()
                if token == "I":
                    units = "INCH"
                elif token in ("M", "MM"):
                    units = "MM"
            continue
        if stripped.startswith("@") or stripped.startswith("&"):
            continue
        if stripped.startswith("ID=") or stripped.startswith("F "):
            continue

        if stripped.startswith("CMP "):
            # Save previous component
            if current_comp is not None:
                if current_bom:
                    current_comp.bom_data = current_bom
                components.append(current_comp)

            current_comp = _parse_cmp_record(stripped, attr_names, attr_texts)
            current_comp.comp_index = len(components)
            current_bom = None
            in_bom_section = False

        elif stripped.startswith("PRP ") and current_comp is not None:
            name, value = _parse_prp_record(stripped)
            if name:
                current_comp.properties[name] = value

        elif stripped.startswith("TOP ") and current_comp is not None:
            toeprint = _parse_top_record(stripped)
            if toeprint:
                current_comp.toeprints.append(toeprint)

        elif stripped.startswith("CPN ") and current_comp is not None:
            in_bom_section = True
            if current_bom is None:
                current_bom = BomData()
            current_bom.cpn = stripped[4:].strip()

        elif stripped.startswith("PKG ") and current_comp is not None and in_bom_section:
            if current_bom is None:
                current_bom = BomData()
            current_bom.pkg = stripped[4:].strip()

        elif stripped.startswith("IPN ") and current_comp is not None:
            if current_bom is None:
                current_bom = BomData()
            current_bom.ipn = stripped[4:].strip()

        elif stripped.startswith("DSC ") and current_comp is not None:
            if current_bom is None:
                current_bom = BomData()
            current_bom.description = stripped[4:].strip()

        elif stripped.startswith("VND ") and current_comp is not None:
            if current_bom is None:
                current_bom = BomData()
            vendor = stripped[4:].strip()
            current_bom.vendors.append({"vendor": vendor, "mpns": []})

        elif stripped.startswith("MPN ") and current_comp is not None:
            if current_bom and current_bom.vendors:
                parts = stripped[4:].strip().split(None, 2)
                if len(parts) >= 3:
                    mpn_entry = {
                        "qualify_status": parts[0],
                        "chosen": parts[1] == "Y",
                        "mpn": parts[2],
                    }
                    current_bom.vendors[-1]["mpns"].append(mpn_entry)

        elif stripped.startswith("VPL_VND ") and current_comp is not None:
            current_comp.properties["VPL_VND"] = stripped[8:].strip()

        elif stripped.startswith("VPL_MPN ") and current_comp is not None:
            current_comp.properties["VPL_MPN"] = stripped[8:].strip()

    # Don't forget the last component
    if current_comp is not None:
        if current_bom:
            current_comp.bom_data = current_bom
        components.append(current_comp)

    return components, units


def _parse_cmp_record(line: str, attr_names: dict, attr_texts: dict) -> Component:
    """Parse: CMP <pkg_ref> <x> <y> <rot> <mirror> <comp_name> <part_name>;attrs;ID=uid"""
    main_part, attr_suffix = split_record_and_attrs(line)
    parts = main_part.split()

    attributes, uid = parse_attributes(attr_suffix, attr_names, attr_texts)

    return Component(
        pkg_ref=int(parts[1]),
        x=float(parts[2]),
        y=float(parts[3]),
        rotation=float(parts[4]),
        mirror=parts[5] == "M",
        comp_name=parts[6] if len(parts) > 6 else "",
        part_name=parts[7] if len(parts) > 7 else "",
        attributes=attributes,
        id=uid,
    )


def _parse_prp_record(line: str) -> tuple[str, str]:
    """Parse: PRP <name> '<value>' [n1 n2...]"""
    # Find the property name (between PRP and the quote)
    after_prp = line[4:].strip()
    quote_start = after_prp.find("'")

    if quote_start == -1:
        # No quoted value
        parts = after_prp.split(None, 1)
        return (parts[0], parts[1]) if len(parts) == 2 else (after_prp, "")

    name = after_prp[:quote_start].strip()
    quote_end = after_prp.find("'", quote_start + 1)
    if quote_end == -1:
        value = after_prp[quote_start + 1:]
    else:
        value = after_prp[quote_start + 1:quote_end]

    return name, value


def _parse_top_record(line: str) -> Toeprint | None:
    """Parse: TOP <pin_num> <x> <y> <rot> <mirror> <net_num> <subnet_num> <toeprint_name>"""
    try:
        parts = line.split()
        if len(parts) < 8:
            return None

        return Toeprint(
            pin_num=int(parts[1]),
            x=float(parts[2]),
            y=float(parts[3]),
            rotation=float(parts[4]),
            mirror=parts[5] == "M",
            net_num=int(parts[6]),
            subnet_num=int(parts[7]),
            name=parts[8] if len(parts) > 8 else "",
        )
    except (ValueError, IndexError):
        return None
