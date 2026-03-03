"""Parser for eda/data files containing packages, nets, and connectivity."""

from __future__ import annotations

from pathlib import Path

from src.models import (
    BBox, Contour, EdaData, FeatureIdRef, Net, Package, Pin, PinOutline,
    Point, Subnet,
)
from src.parsers.base_parser import (
    parse_attr_lookup, parse_attributes, parse_contour, parse_units,
    read_file, split_record_and_attrs,
)


def parse_eda_data(path: Path) -> EdaData:
    """Parse the eda/data file.

    Contains net definitions, package definitions, pin definitions,
    and feature-to-net connectivity (FID records).
    """
    lines = read_file(path)
    eda = EdaData()
    eda.units = parse_units(lines)

    # Parse attribute lookups
    attr_names, attr_texts = parse_attr_lookup(lines)

    # State tracking
    current_net = None
    current_subnet = None
    current_pkg = None
    current_pin = None
    net_index = 0
    pkg_index = 0

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith("HDR "):
            eda.source = line[4:].strip()
            i += 1
            continue

        if line.startswith("LYR "):
            eda.layer_names = line[4:].strip().split()
            i += 1
            continue

        if line.startswith("PRP ") and current_net is None and current_pkg is None:
            # Board-level property
            name, value = _parse_prp(line)
            if name:
                eda.properties[name] = value
            i += 1
            continue

        if line.startswith("NET "):
            # Save previous net
            _finalize_subnet(current_net, current_subnet)
            _finalize_pin(current_pkg, current_pin)
            if current_net is not None:
                eda.nets.append(current_net)
            _finalize_package(eda, current_pkg)

            current_net = _parse_net_record(line, net_index, attr_names, attr_texts)
            current_subnet = None
            current_pkg = None
            current_pin = None
            net_index += 1
            i += 1
            continue

        if line.startswith("SNT "):
            _finalize_subnet(current_net, current_subnet)
            current_subnet = _parse_subnet_record(line)
            i += 1
            continue

        if line.startswith("FID "):
            fid = _parse_fid_record(line)
            if fid and current_subnet:
                current_subnet.feature_ids.append(fid)
            i += 1
            continue

        if line.startswith("PKG "):
            # Save previous net/subnet
            _finalize_subnet(current_net, current_subnet)
            if current_net is not None:
                eda.nets.append(current_net)
                current_net = None
                current_subnet = None

            _finalize_pin(current_pkg, current_pin)
            _finalize_package(eda, current_pkg)

            current_pkg = _parse_pkg_record(line, attr_names, attr_texts)
            current_pin = None
            pkg_index += 1
            i += 1
            continue

        if line.startswith("PIN "):
            _finalize_pin(current_pkg, current_pin)
            current_pin = _parse_pin_record(line)
            i += 1
            continue

        # Outline records for packages/pins
        if line.startswith(("RC ", "CR ", "SQ ", "CT ")):
            outline = _parse_simple_outline(line)
            if outline:
                if current_pin:
                    current_pin.outlines.append(outline)
                elif current_pkg:
                    current_pkg.outlines.append(outline)
            i += 1
            continue

        if line.startswith("OB "):
            # Contour outline for package/pin
            contour, i = parse_contour(lines, i)
            outline = PinOutline(type="CONTOUR", contour=contour)
            if current_pin:
                current_pin.outlines.append(outline)
            elif current_pkg:
                current_pkg.outlines.append(outline)
            continue

        if line.startswith("PRP "):
            name, value = _parse_prp(line)
            if name and current_net is not None:
                current_net.attributes[name] = value
            i += 1
            continue

        if line.startswith("FGR "):
            # Feature group record - skip
            i += 1
            continue

        i += 1

    # Finalize last records
    _finalize_subnet(current_net, current_subnet)
    if current_net is not None:
        eda.nets.append(current_net)
    _finalize_pin(current_pkg, current_pin)
    _finalize_package(eda, current_pkg)

    return eda


def _parse_net_record(line: str, index: int,
                      attr_names: dict, attr_texts: dict) -> Net:
    """Parse: NET <net_name>;attrs;ID=uid"""
    main_part, attr_suffix = split_record_and_attrs(line)
    parts = main_part.split()
    name = parts[1] if len(parts) > 1 else ""

    attributes, uid = parse_attributes(attr_suffix, attr_names, attr_texts)

    return Net(name=name, index=index, attributes=attributes, id=uid)


def _parse_subnet_record(line: str) -> Subnet:
    """Parse: SNT <type> [type-specific fields]"""
    parts = line.split()
    subnet_type = parts[1] if len(parts) > 1 else "TRC"

    subnet = Subnet(type=subnet_type)

    if subnet_type == "TOP" and len(parts) >= 5:
        subnet.side = parts[2]      # T or B
        subnet.comp_num = int(parts[3])
        subnet.toep_num = int(parts[4])
    elif subnet_type == "PLN" and len(parts) >= 5:
        subnet.fill_type = parts[2]
        subnet.cutout_type = parts[3]
        subnet.fill_size = float(parts[4])

    return subnet


def _parse_fid_record(line: str) -> FeatureIdRef | None:
    """Parse: FID <type> <layer_num> <feature_num>"""
    parts = line.split()
    if len(parts) < 4:
        return None
    try:
        return FeatureIdRef(
            type=parts[1],
            layer_idx=int(parts[2]),
            feature_idx=int(parts[3]),
        )
    except ValueError:
        return None


def _parse_pkg_record(line: str, attr_names: dict, attr_texts: dict) -> Package:
    """Parse: PKG <name> <pitch> <xmin> <ymin> <xmax> <ymax>;attrs;ID=uid"""
    main_part, attr_suffix = split_record_and_attrs(line)
    parts = main_part.split()

    name = parts[1] if len(parts) > 1 else ""
    pitch = float(parts[2]) if len(parts) > 2 else 0.0

    bbox = None
    if len(parts) >= 7:
        bbox = BBox(
            xmin=float(parts[3]),
            ymin=float(parts[4]),
            xmax=float(parts[5]),
            ymax=float(parts[6]),
        )

    attributes, uid = parse_attributes(attr_suffix, attr_names, attr_texts)

    return Package(name=name, pitch=pitch, bbox=bbox, attributes=attributes, id=uid)


def _parse_pin_record(line: str) -> Pin:
    """Parse: PIN <name> <type> <xc> <yc> <fhs> <etype> <mtype> [ID=uid]"""
    main_part, attr_suffix = split_record_and_attrs(line)
    parts = main_part.split()

    _, uid = parse_attributes(attr_suffix)

    return Pin(
        name=parts[1] if len(parts) > 1 else "",
        type=parts[2] if len(parts) > 2 else "TH",
        center=Point(
            x=float(parts[3]) if len(parts) > 3 else 0.0,
            y=float(parts[4]) if len(parts) > 4 else 0.0,
        ),
        finished_hole_size=float(parts[5]) if len(parts) > 5 else 0.0,
        electrical_type=parts[6] if len(parts) > 6 else "U",
        mount_type=parts[7] if len(parts) > 7 else "U",
        id=uid,
    )


def _parse_simple_outline(line: str) -> PinOutline | None:
    """Parse simple outline records: RC, CR, SQ, CT."""
    parts = line.split()
    if len(parts) < 2:
        return None

    outline_type = parts[0]
    params = {}

    if outline_type == "RC" and len(parts) >= 5:
        params = {"llx": float(parts[1]), "lly": float(parts[2]),
                  "width": float(parts[3]), "height": float(parts[4])}
    elif outline_type == "CR" and len(parts) >= 4:
        params = {"xc": float(parts[1]), "yc": float(parts[2]),
                  "radius": float(parts[3])}
    elif outline_type == "SQ" and len(parts) >= 4:
        params = {"xc": float(parts[1]), "yc": float(parts[2]),
                  "half_side": float(parts[3])}
    elif outline_type == "CT" and len(parts) >= 4:
        params = {"xc": float(parts[1]), "yc": float(parts[2]),
                  "radius": float(parts[3])}

    return PinOutline(type=outline_type, params=params)


def _parse_prp(line: str) -> tuple[str, str]:
    """Parse: PRP <name> '<value>'"""
    after_prp = line[4:].strip()
    quote_start = after_prp.find("'")
    if quote_start == -1:
        parts = after_prp.split(None, 1)
        return (parts[0], parts[1]) if len(parts) == 2 else (after_prp, "")

    name = after_prp[:quote_start].strip()
    quote_end = after_prp.find("'", quote_start + 1)
    if quote_end == -1:
        value = after_prp[quote_start + 1:]
    else:
        value = after_prp[quote_start + 1:quote_end]
    return name, value


def _finalize_subnet(net: Net | None, subnet: Subnet | None):
    if net is not None and subnet is not None:
        net.subnets.append(subnet)


def _finalize_pin(pkg: Package | None, pin: Pin | None):
    if pkg is not None and pin is not None:
        pkg.pins.append(pin)


def _finalize_package(eda: EdaData, pkg: Package | None):
    if pkg is not None:
        eda.packages.append(pkg)
