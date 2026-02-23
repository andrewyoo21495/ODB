"""
Features Parser
Parses ODB++ features files into Pad, Line, Arc, Surface, and TextFeature objects.
"""

import re
from typing import List, Dict, Tuple, Optional
from models import Pad, Line, Arc, Surface, TextFeature, Layer, LayerData


def decode_orient(tokens: List[str], start_idx: int) -> Tuple[float, bool, int]:
    """
    Decode the orient_def field from a list of tokens starting at start_idx.
    Returns (angle_degrees, mirror, tokens_consumed).
    """
    if start_idx >= len(tokens):
        return 0.0, False, 0

    try:
        mode = int(tokens[start_idx])
    except (ValueError, IndexError):
        return 0.0, False, 0

    if mode <= 7:
        angles = [0, 90, 180, 270, 0, 90, 180, 270]
        mirror = mode >= 4
        return float(angles[mode]), mirror, 1
    else:
        # New-style: mode 8 (no mirror) or 9 (mirror) + angle
        mirror = (mode == 9)
        angle = 0.0
        consumed = 1
        if start_idx + 1 < len(tokens):
            try:
                angle = float(tokens[start_idx + 1])
                consumed = 2
            except ValueError:
                pass
        return angle, mirror, consumed


class FeaturesParser:
    """Parses a features file for a single ODB++ layer."""

    def parse(self, file_path: str, layer: Layer, symbol_table: Optional[Dict[int, str]] = None) -> LayerData:
        """
        Parse the features file and return a LayerData object.

        Args:
            file_path: Path to the features file.
            layer: The Layer object this data belongs to.
            symbol_table: Optional pre-built symbol table (overrides file's own table).
        """
        ld = LayerData(layer=layer)
        self._symbol_table: Dict[int, str] = {}
        self._attr_name_table: Dict[int, str] = {}
        self._attr_str_table: Dict[int, str] = {}
        self.units = 'INCH'

        lines = self._read_lines(file_path)
        self._parse_header(lines)

        if symbol_table is not None:
            self._symbol_table.update(symbol_table)

        self._parse_records(lines, ld)
        return ld

    @property
    def symbol_table(self) -> Dict[int, str]:
        return self._symbol_table

    # ------------------------------------------------------------------
    # File reading
    # ------------------------------------------------------------------

    @staticmethod
    def _read_lines(path: str) -> List[str]:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.readlines()

    # ------------------------------------------------------------------
    # Header parsing
    # ------------------------------------------------------------------

    def _parse_header(self, lines: List[str]) -> None:
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue

            if line.upper().startswith('UNITS='):
                self.units = line.split('=', 1)[1].strip().upper()
            elif line.startswith('$'):
                self._parse_symbol_entry(line)
            elif line.startswith('@'):
                self._parse_attr_name_entry(line)
            elif line.startswith('&'):
                self._parse_attr_str_entry(line)

    def _parse_symbol_entry(self, line: str) -> None:
        # $<idx> <name> [M]
        m = re.match(r'^\$(\d+)\s+(\S+)', line)
        if m:
            self._symbol_table[int(m.group(1))] = m.group(2)

    def _parse_attr_name_entry(self, line: str) -> None:
        # @<idx> <name>
        m = re.match(r'^@(\d+)\s+(\S+)', line)
        if m:
            self._attr_name_table[int(m.group(1))] = m.group(2)

    def _parse_attr_str_entry(self, line: str) -> None:
        # &<idx> <string>
        m = re.match(r'^&(\d+)\s+(.*)', line)
        if m:
            self._attr_str_table[int(m.group(1))] = m.group(2).strip()

    # ------------------------------------------------------------------
    # Record parsing
    # ------------------------------------------------------------------

    def _parse_records(self, lines: List[str], ld: LayerData) -> None:
        current_surface: Optional[Surface] = None
        current_outline: Optional[List[Tuple[float, float]]] = None
        outline_type: str = 'I'  # I = island, H = hole

        for raw in lines:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if line[0] in ('$', '@', '&') or '=' in line[:20]:
                continue  # Skip header entries and KEY=VALUE lines

            # Strip attribute suffixes (everything from first ';' onward)
            main_part = line.split(';')[0].rstrip()
            if not main_part:
                continue

            tokens = main_part.split()
            if not tokens:
                continue

            rec_type = tokens[0].upper()

            if rec_type == 'P':
                pad = self._parse_pad(tokens)
                if pad:
                    ld.pads.append(pad)
            elif rec_type == 'L':
                ln = self._parse_line(tokens)
                if ln:
                    ld.lines.append(ln)
            elif rec_type == 'A':
                arc = self._parse_arc(tokens)
                if arc:
                    ld.arcs.append(arc)
            elif rec_type == 'S':
                current_surface = self._parse_surface_start(tokens)
                current_outline = None
            elif rec_type == 'SE':
                if current_surface is not None:
                    if current_outline is not None:
                        current_surface.islands.append(current_outline)
                        current_outline = None
                    ld.surfaces.append(current_surface)
                    current_surface = None
            elif rec_type == 'OB':
                # Outline begin: close previous outline if any
                if current_outline is not None and current_surface is not None:
                    current_surface.islands.append(current_outline)
                outline_type = 'I'
                if len(tokens) >= 4:
                    outline_type = tokens[3].upper()
                elif len(tokens) >= 3 and tokens[2].upper() in ('I', 'H'):
                    outline_type = tokens[2].upper()
                current_outline = []
                if len(tokens) >= 3:
                    try:
                        x, y = float(tokens[1]), float(tokens[2])
                        current_outline.append((x, y))
                    except (ValueError, IndexError):
                        pass
            elif rec_type == 'OC':
                # Outline corner/coordinate
                if current_outline is not None and len(tokens) >= 3:
                    try:
                        x, y = float(tokens[1]), float(tokens[2])
                        current_outline.append((x, y))
                    except ValueError:
                        pass
            elif rec_type == 'OS':
                # Outline segment end — close current outline
                if current_outline is not None and current_surface is not None:
                    current_surface.islands.append(current_outline)
                    current_outline = None
            elif rec_type == 'T':
                txt = self._parse_text(raw)
                if txt:
                    ld.texts.append(txt)

    # ------------------------------------------------------------------
    # Record type parsers
    # ------------------------------------------------------------------

    def _resolve_symbol(self, idx_str: str) -> str:
        try:
            idx = int(idx_str)
            return self._symbol_table.get(idx, f'r{idx}')
        except ValueError:
            return idx_str

    def _parse_pad(self, tokens: List[str]) -> Optional[Pad]:
        # P x y sym_num pol [dcode] orient_def [orient_angle]
        if len(tokens) < 5:
            return None
        try:
            x = float(tokens[1])
            y = float(tokens[2])
            sym_name = self._resolve_symbol(tokens[3])
            pol = tokens[4].upper()

            # Tokens after pol: may be [dcode] orient [orient_angle]
            orient_start = 5
            # If token[5] is an integer that could be a dcode (not 8/9 mode)
            # and there's enough tokens, try to detect dcode
            rotation = 0.0
            mirror = False
            if orient_start < len(tokens):
                angle, mirror, consumed = decode_orient(tokens, orient_start)
                if consumed == 0 and orient_start + 1 < len(tokens):
                    # Skip one token (dcode) and retry
                    angle, mirror, consumed = decode_orient(tokens, orient_start + 1)
                rotation = angle

            return Pad(x=x, y=y, symbol_name=sym_name, polarity=pol,
                       rotation=rotation, mirror=mirror)
        except (ValueError, IndexError):
            return None

    def _parse_line(self, tokens: List[str]) -> Optional[Line]:
        # L xs ys xe ye sym_num pol [dcode]
        if len(tokens) < 7:
            return None
        try:
            x1, y1 = float(tokens[1]), float(tokens[2])
            x2, y2 = float(tokens[3]), float(tokens[4])
            sym_name = self._resolve_symbol(tokens[5])
            pol = tokens[6].upper()
            return Line(x1=x1, y1=y1, x2=x2, y2=y2,
                        symbol_name=sym_name, polarity=pol)
        except (ValueError, IndexError):
            return None

    def _parse_arc(self, tokens: List[str]) -> Optional[Arc]:
        # A xs ys xe ye xc yc sym pol [dcode] cw
        if len(tokens) < 10:
            return None
        try:
            xs, ys = float(tokens[1]), float(tokens[2])
            xe, ye = float(tokens[3]), float(tokens[4])
            xc, yc = float(tokens[5]), float(tokens[6])
            sym_name = self._resolve_symbol(tokens[7])
            pol = tokens[8].upper()
            # cw can be at index 9 or 10 (if dcode is at 9)
            cw_token = 'N'
            for tok in tokens[9:]:
                if tok.upper() in ('Y', 'N', 'CW', 'CCW'):
                    cw_token = tok.upper()
                    break
            clockwise = cw_token in ('Y', 'CW')
            return Arc(xs=xs, ys=ys, xe=xe, ye=ye, xc=xc, yc=yc,
                       symbol_name=sym_name, polarity=pol, clockwise=clockwise)
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _parse_surface_start(tokens: List[str]) -> Surface:
        pol = tokens[1].upper() if len(tokens) > 1 else 'P'
        return Surface(polarity=pol)

    def _parse_text(self, raw: str) -> Optional[TextFeature]:
        # T x y font pol orient xsize ysize width 'text content here'
        # Extract quoted text first
        m = re.search(r"'(.*?)'", raw)
        text_content = m.group(1) if m else ''
        main = raw.split(';')[0]
        # Remove quoted part for token parsing
        main_no_quote = re.sub(r"'.*?'", '', main)
        tokens = main_no_quote.split()
        if len(tokens) < 9:
            return None
        try:
            x, y = float(tokens[1]), float(tokens[2])
            font = tokens[3]
            pol = tokens[4].upper()
            orient_angle, mirror, _ = decode_orient(tokens, 5)
            xsize = float(tokens[6])
            ysize = float(tokens[7])
            width = float(tokens[8])
            return TextFeature(x=x, y=y, font=font, polarity=pol,
                                rotation=orient_angle, xsize=xsize,
                                ysize=ysize, width=width, text=text_content)
        except (ValueError, IndexError):
            return None
