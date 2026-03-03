"""Parser for matrix/stackup.xml files."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


def parse_stackup(path: Path) -> dict:
    """Parse the stackup XML file.

    Returns a dict with stackup data including materials,
    layer properties, and impedance specifications.
    Not all ODB++ files contain this file.
    """
    tree = ET.parse(path)
    root = tree.getroot()

    # Remove namespace prefixes for easier access
    ns = _get_namespace(root)

    result = {
        "eda_data": _parse_eda_section(root, ns),
        "supplier_data": _parse_supplier_section(root, ns),
    }

    return result


def _get_namespace(root: ET.Element) -> str:
    """Extract namespace from root element tag."""
    tag = root.tag
    if tag.startswith("{"):
        return tag[1:tag.index("}")]
    return ""


def _ns_tag(ns: str, tag: str) -> str:
    """Create namespaced tag string."""
    if ns:
        return f"{{{ns}}}{tag}"
    return tag


def _parse_eda_section(root: ET.Element, ns: str) -> Optional[dict]:
    """Parse the EdaData section."""
    eda = root.find(_ns_tag(ns, "EdaData"))
    if eda is None:
        # Try without namespace
        eda = root.find("EdaData")
    if eda is None:
        return None

    result = {}

    # Parse specs
    specs_elem = eda.find(_ns_tag(ns, "Specs")) or eda.find("Specs")
    if specs_elem is not None:
        result["specs"] = _parse_specs(specs_elem, ns)

    # Parse stackup
    stackup_elem = eda.find(_ns_tag(ns, "Stackup")) or eda.find("Stackup")
    if stackup_elem is not None:
        result["stackup"] = _parse_stackup_section(stackup_elem, ns)

    return result


def _parse_supplier_section(root: ET.Element, ns: str) -> Optional[dict]:
    """Parse the SupplierData section."""
    supplier = root.find(_ns_tag(ns, "SupplierData"))
    if supplier is None:
        supplier = root.find("SupplierData")
    if supplier is None:
        return None

    result = {}

    specs_elem = supplier.find(_ns_tag(ns, "Specs")) or supplier.find("Specs")
    if specs_elem is not None:
        result["specs"] = _parse_specs(specs_elem, ns)

    stackup_elem = supplier.find(_ns_tag(ns, "Stackup")) or supplier.find("Stackup")
    if stackup_elem is not None:
        result["stackup"] = _parse_stackup_section(stackup_elem, ns)

    return result


def _parse_specs(specs_elem: ET.Element, ns: str) -> list[dict]:
    """Parse Spec entries under Specs."""
    specs = []
    for spec in specs_elem:
        spec_data = {"attributes": dict(spec.attrib)}
        # Parse materials and impedance sub-elements
        for child in spec:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            spec_data[tag] = _element_to_dict(child)
        specs.append(spec_data)
    return specs


def _parse_stackup_section(stackup_elem: ET.Element, ns: str) -> dict:
    """Parse the Stackup section with groups and layers."""
    result = {"attributes": dict(stackup_elem.attrib), "groups": []}

    for group in stackup_elem:
        tag = group.tag.split("}")[-1] if "}" in group.tag else group.tag
        if tag == "Group":
            group_data = {"attributes": dict(group.attrib), "layers": []}
            for layer in group:
                layer_tag = layer.tag.split("}")[-1] if "}" in layer.tag else layer.tag
                if layer_tag == "Layer":
                    layer_data = {"attributes": dict(layer.attrib)}
                    for child in layer:
                        child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                        layer_data[child_tag] = _element_to_dict(child)
                    group_data["layers"].append(layer_data)
            result["groups"].append(group_data)

    return result


def _element_to_dict(elem: ET.Element) -> dict:
    """Recursively convert an XML element to a dict."""
    result = {"attributes": dict(elem.attrib)}
    for child in elem:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag in result:
            # Multiple children with same tag -> list
            if not isinstance(result[tag], list):
                result[tag] = [result[tag]]
            result[tag].append(_element_to_dict(child))
        else:
            result[tag] = _element_to_dict(child)
    if elem.text and elem.text.strip():
        result["text"] = elem.text.strip()
    return result
