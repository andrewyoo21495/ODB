####################################################################################
# 1) symbol_parser.py

## $SYMBOL 섹션을 정규표현식으로 파싱하고, 각 OUTLINE 레코드의 숫자 파라미터들을 추출합니다. 
# 다양한 OUTLINE 타입 지원(RC, CR, OB, OC, OS, SQ, CT, etc.).
####################################################################################

# symbol_parser.py
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional

"""
Symbol parser for ODB++ layer 'features' $SYMBOL sections.

It parses sections like:
$SYMBOL 1102
OUTLINE RC 0 0 0.1574803
ROTATABLE
ENDSYMBOL

OUTLINE grammar is flexible: numeric tokens (including negatives and decimals) are captured.
"""

@dataclass
class SymbolOutline:
    type: str                 # e.g., 'RC', 'CR', 'OB', 'OC', 'OS', 'SQ', 'CT'
    params: List[float]       # numeric parameters parsed (float)

@dataclass
class Symbol:
    sid: int
    outlines: List[SymbolOutline] = field(default_factory=list)
    rotatable: bool = False
    attrs: Dict[str, str] = field(default_factory=dict)  # any textual attrs

# Regex patterns
_sym_start_re = re.compile(r"^\$SYMBOL\s+(\d+)\s*$", re.IGNORECASE)
_sym_end_re = re.compile(r"^\s*ENDSYMBOL\s*$", re.IGNORECASE)
_outline_re = re.compile(r"^OUTLINE\s+([A-Z]+)\s+(.+)$", re.IGNORECASE)
_rotatable_re = re.compile(r"^\s*ROTATABLE\s*$", re.IGNORECASE)
_attr_re = re.compile(r"^([A-Z][A-Z0-9_]*)\s+(.+)$", re.IGNORECASE)
_number_re = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")  # floats with optional exp

def _parse_numbers_from_string(s: str):
    nums = _number_re.findall(s)
    return [float(n) for n in nums]

def parse_symbols(lines: List[str]) -> Dict[int, Symbol]:
    """
    Parse all $SYMBOL ... ENDSYMBOL blocks in given list of lines.
    Returns dict: symbol_id -> Symbol
    """
    symbols: Dict[int, Symbol] = {}
    current: Optional[Symbol] = None
    for raw in lines:
        line = raw.rstrip('\n')
        mstart = _sym_start_re.match(line)
        if mstart:
            sid = int(mstart.group(1))
            current = Symbol(sid)
            symbols[sid] = current
            continue

        if current is not None:
            # end?
            if _sym_end_re.match(line):
                current = None
                continue

            # rotatable?
            if _rotatable_re.match(line):
                current.rotatable = True
                continue

            # outline?
            mo = _outline_re.match(line)
            if mo:
                kind = mo.group(1).upper()
                rest = mo.group(2)
                nums = _parse_numbers_from_string(rest)
                current.outlines.append(SymbolOutline(kind, nums))
                continue

            # generic attribute (KEY value...)
            ma = _attr_re.match(line)
            if ma:
                key = ma.group(1).upper()
                val = ma.group(2).strip()
                current.attrs[key] = val
                continue
    return symbols

# quick test if run as script
if __name__ == "__main__":
    sample = [
        "$SYMBOL 1102",
        "OUTLINE RC 0 0 0.1574803",
        "OUTLINE OB 0.0 0.0 0.6 0.25",
        "ROTATABLE",
        "ENDSYMBOL",
        "$SYMBOL 200",
        "OUTLINE CR 0 0 0.5",
        "ENDSYMBOL"
    ]
    syms = parse_symbols(sample)
    print("Parsed symbols:", syms.keys())
    for sid, s in syms.items():
        print("SID", sid, "rotatable", s.rotatable, "outlines", [(o.type,o.params) for o in s.outlines])
