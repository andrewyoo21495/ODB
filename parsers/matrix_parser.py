"""
Matrix Parser
Parses matrix/matrix file to extract layer definitions, type, and polarity.
"""

import re
from typing import List, Optional
from models import Layer


class MatrixParser:
    """Parses the ODB++ matrix/matrix file into a list of Layer objects."""

    # Layer type side hints (checked against layer names, case-insensitive)
    _TOP_HINTS = ('top', '_t_', '_t.', '-top', '+top', 'comp_top',
                  'smt_top', 'paste_top', 'mask_top')
    _BOT_HINTS = ('bot', 'bottom', '_b_', '_b.', '-bot', '+bot', 'comp_bot',
                  'smt_bot', 'paste_bot', 'mask_bot')

    def parse(self, file_path: str) -> List[Layer]:
        """Parse the matrix file and return a list of Layer objects."""
        lines = self._read_lines(file_path)
        col_blocks = self._split_into_col_blocks(lines)
        layers = [self._build_layer(blk) for blk in col_blocks]
        layers = [l for l in layers if l is not None]
        layers.sort(key=lambda l: l.index)
        self._assign_sides(layers)
        return layers

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_lines(path: str) -> List[str]:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.readlines()

    def _split_into_col_blocks(self, lines: List[str]) -> List[dict]:
        """Split the file into per-column dicts of key→value pairs."""
        blocks: List[dict] = []
        current: Optional[dict] = None

        for raw in lines:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue

            col_match = re.match(r'^COL\s+(\d+)', line, re.IGNORECASE)
            if col_match:
                if current is not None:
                    blocks.append(current)
                current = {'_col': int(col_match.group(1))}
                # Handle inline key=value on the same COL line
                rest = line[col_match.end():].strip()
                self._parse_kv_into(rest, current)
                continue

            if current is not None:
                self._parse_kv_into(line, current)

        if current is not None:
            blocks.append(current)

        return blocks

    @staticmethod
    def _parse_kv_into(text: str, target: dict) -> None:
        """Parse any KEY=VALUE pairs in text and add to target."""
        for m in re.finditer(r'(\w+)\s*=\s*(\S+)', text):
            target[m.group(1).upper()] = m.group(2)

    def _build_layer(self, blk: dict) -> Optional[Layer]:
        """Build a Layer from a parsed column block."""
        name = blk.get('LAYER') or blk.get('NAME')
        if not name:
            return None
        layer_type = blk.get('TYPE', 'SIGNAL')
        polarity = blk.get('POLARITY', 'POSITIVE')
        col = blk.get('_col', 0)
        return Layer(
            name=name,
            layer_type=layer_type,
            polarity=polarity,
            side='',          # Assigned later by _assign_sides
            index=col,
        )

    def _assign_sides(self, layers: List[Layer]) -> None:
        """Determine TOP/BOTTOM/INNER for each layer based on name and position."""
        if not layers:
            return

        # First pass: use name heuristics
        for layer in layers:
            name_lower = layer.name.lower()
            if any(h in name_lower for h in self._TOP_HINTS):
                layer.side = 'TOP'
            elif any(h in name_lower for h in self._BOT_HINTS):
                layer.side = 'BOTTOM'

        # Second pass: for layers without a side, use stack position
        signal_layers = [l for l in layers
                         if l.layer_type in ('SIGNAL', 'POWER', 'COMPONENT')
                         and not l.side]
        if signal_layers:
            signal_layers[0].side = 'TOP'
            signal_layers[-1].side = 'BOTTOM'
            for l in signal_layers[1:-1]:
                l.side = 'INNER'

        # Third pass: any remaining layers with no side
        for layer in layers:
            if not layer.side:
                if layer.layer_type == 'DRILL':
                    layer.side = 'INNER'
                else:
                    layer.side = 'INNER'
