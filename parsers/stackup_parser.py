"""
Stackup Parser
Parses matrix/stackup.xml for layer physical properties (thickness, material, etc.).
"""

import os
from typing import Dict, Any, Optional

try:
    import xml.etree.ElementTree as ET
except ImportError:
    ET = None  # type: ignore


class StackupParser:
    """Parses the ODB++ stackup.xml file for layer physical properties."""

    def parse(self, stackup_xml_path: str) -> Dict[str, Dict[str, Any]]:
        """
        Parse stackup.xml and return a dict mapping layer names to their
        physical properties (thickness, material, conductivity, etc.).

        Returns:
            {layer_name: {'thickness': float, 'material': str, ...}}
        """
        if ET is None:
            return {}
        if not os.path.isfile(stackup_xml_path):
            return {}

        try:
            tree = ET.parse(stackup_xml_path)
            root = tree.getroot()
        except ET.ParseError:
            return {}

        result: Dict[str, Dict[str, Any]] = {}

        # Try common XML structures for ODB++ stackup files
        for layer_el in root.iter():
            tag = layer_el.tag.split('}')[-1].lower()  # Strip namespace
            if tag in ('layer', 'stackup_layer', 'dielectric', 'conductor'):
                name = (
                    layer_el.get('name')
                    or layer_el.get('layer_name')
                    or layer_el.get('id')
                )
                if name:
                    props: Dict[str, Any] = {}
                    for attr_name, val in layer_el.attrib.items():
                        clean_key = attr_name.split('}')[-1].lower()
                        props[clean_key] = val
                    # Also capture child text/value elements
                    for child in layer_el:
                        child_tag = child.tag.split('}')[-1].lower()
                        if child.text and child.text.strip():
                            props[child_tag] = child.text.strip()
                    result[name] = props

        return result
