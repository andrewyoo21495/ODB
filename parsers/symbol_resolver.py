"""
Symbol Resolver
Converts ODB++ symbol names into geometry parameter dicts.
Handles standard built-in symbols and delegates user-defined symbols.
"""

import re
import os
from typing import Dict, Optional, Any


class SymbolResolver:
    """
    Resolves ODB++ symbol names to geometry dictionaries.

    Standard symbols are parsed via regex patterns.
    User-defined symbols (found under symbols/<name>/features) are parsed
    recursively and cached.
    """

    def __init__(self, symbols_dir: Optional[str] = None):
        """
        Args:
            symbols_dir: Path to the product model's 'symbols/' directory.
                         Required only for user-defined symbols.
        """
        self._symbols_dir = symbols_dir
        self._cache: Dict[str, Dict[str, Any]] = {}

    def resolve(self, name: str) -> Dict[str, Any]:
        """
        Resolve a symbol name to a geometry dict.

        Returns a dict with at minimum {'type': <str>} and shape-specific fields.
        """
        if name in self._cache:
            return self._cache[name]

        result = self._parse_standard(name)
        if result is None:
            result = self._load_user_defined(name)
        if result is None:
            result = {'type': 'unknown', 'name': name}

        self._cache[name] = result
        return result

    # ------------------------------------------------------------------
    # Standard symbol parsing
    # ------------------------------------------------------------------

    def _parse_standard(self, name: str) -> Optional[Dict[str, Any]]:
        """Try to parse name as a standard ODB++ symbol. Returns None if not matched."""
        n = name.lower()

        # Round: r<d>
        m = re.match(r'^r([\d.]+)$', n)
        if m:
            return {'type': 'circle', 'diameter': float(m.group(1))}

        # Square: sq<s>
        m = re.match(r'^sq([\d.]+)$', n)
        if m:
            s = float(m.group(1))
            return {'type': 'rect', 'w': s, 'h': s}

        # Rectangle: rect<w>x<h>
        m = re.match(r'^rect([\d.]+)x([\d.]+)$', n)
        if m:
            return {'type': 'rect', 'w': float(m.group(1)), 'h': float(m.group(2))}

        # Oval: oval<w>x<h>
        m = re.match(r'^oval([\d.]+)x([\d.]+)$', n)
        if m:
            return {'type': 'oval', 'w': float(m.group(1)), 'h': float(m.group(2))}

        # Diamond: di<w>x<h>
        m = re.match(r'^di([\d.]+)x([\d.]+)$', n)
        if m:
            return {'type': 'diamond', 'w': float(m.group(1)), 'h': float(m.group(2))}

        # Octagon: oct<w>x<h>x<cx>x<cy>
        m = re.match(r'^oct([\d.]+)x([\d.]+)x([\d.]+)x([\d.]+)$', n)
        if m:
            return {
                'type': 'octagon',
                'w': float(m.group(1)), 'h': float(m.group(2)),
                'cx': float(m.group(3)), 'cy': float(m.group(4)),
            }

        # Horizontal hexagon: hex_l<w>x<h>x<r>
        m = re.match(r'^hex_l([\d.]+)x([\d.]+)x([\d.]+)$', n)
        if m:
            return {
                'type': 'hexagon',
                'w': float(m.group(1)), 'h': float(m.group(2)),
                'r': float(m.group(3)),
            }

        # Round donut: donut_r<od>x<id>
        m = re.match(r'^donut_r([\d.]+)x([\d.]+)$', n)
        if m:
            return {
                'type': 'donut_round',
                'od': float(m.group(1)), 'id': float(m.group(2)),
            }

        # Rectangular donut: donut_s<od>x<id> or donut_sq<s>x<id>
        m = re.match(r'^donut_s(?:q)?([\d.]+)x([\d.]+)$', n)
        if m:
            return {
                'type': 'donut_rect',
                'od': float(m.group(1)), 'id': float(m.group(2)),
            }

        # Rectangular thermal: rc_tho or rect_tho ...
        m = re.match(r'^rc?_?tho([\d.]+)x([\d.]+).*', n)
        if m:
            return {
                'type': 'thermal_rect',
                'w': float(m.group(1)), 'h': float(m.group(2)),
            }

        # Round thermal: r_tho<od>x<id>
        m = re.match(r'^r_tho([\d.]+)x([\d.]+).*', n)
        if m:
            return {
                'type': 'thermal_round',
                'od': float(m.group(1)), 'id': float(m.group(2)),
            }

        # Oblong: oblong<w>x<h>
        m = re.match(r'^oblong([\d.]+)x([\d.]+)$', n)
        if m:
            return {'type': 'oval', 'w': float(m.group(1)), 'h': float(m.group(2))}

        # Rounded rectangle: rndrect<w>x<h>x<r>
        m = re.match(r'^rndrect([\d.]+)x([\d.]+)x([\d.]+)$', n)
        if m:
            return {
                'type': 'rndrect',
                'w': float(m.group(1)), 'h': float(m.group(2)),
                'r': float(m.group(3)),
            }

        return None

    # ------------------------------------------------------------------
    # User-defined symbol loading
    # ------------------------------------------------------------------

    def _load_user_defined(self, name: str) -> Optional[Dict[str, Any]]:
        if self._symbols_dir is None:
            return None
        # User-defined symbols live in symbols/<name>/features
        features_path = os.path.join(self._symbols_dir, name, 'features')
        if not os.path.isfile(features_path):
            return None
        # Return a reference; actual geometry is in the features file
        return {
            'type': 'user_defined',
            'name': name,
            'features_path': features_path,
        }

    # ------------------------------------------------------------------
    # Convenience: get a representative size for line width calculations
    # ------------------------------------------------------------------

    @staticmethod
    def get_line_width(sym_info: Dict[str, Any]) -> float:
        """Return a representative line width from a symbol geometry dict."""
        t = sym_info.get('type', '')
        if t == 'circle':
            return sym_info.get('diameter', 0.01)
        elif t in ('rect', 'rndrect'):
            return min(sym_info.get('w', 0.01), sym_info.get('h', 0.01))
        elif t == 'oval':
            return min(sym_info.get('w', 0.01), sym_info.get('h', 0.01))
        return sym_info.get('diameter', sym_info.get('w', 0.01))
