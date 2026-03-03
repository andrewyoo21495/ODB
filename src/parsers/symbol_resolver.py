"""Standard symbol name resolver.

Parses standard symbol names (e.g., 'r120', 'rect20x60', 'donut_r78.74x27.559')
and generates geometric parameters for rendering.
"""

from __future__ import annotations

import math
import re
from typing import Optional

from src.models import StandardSymbol


# Symbol name patterns (order matters - more specific patterns first)
_PATTERNS = [
    # Thermals
    (r"^rc_tho(\d+\.?\d*)x(\d+\.?\d*)x(\d+\.?\d*)x(\d+)x(\d+\.?\d*)x(\d+\.?\d*)$", "rc_tho"),
    (r"^rc_ths(\d+\.?\d*)x(\d+\.?\d*)x(\d+\.?\d*)x(\d+)x(\d+\.?\d*)x(\d+\.?\d*)$", "rc_ths"),
    (r"^o_ths(\d+\.?\d*)x(\d+\.?\d*)x(\d+\.?\d*)x(\d+)x(\d+\.?\d*)x(\d+\.?\d*)$", "o_ths"),
    (r"^sr_ths(\d+\.?\d*)x(\d+\.?\d*)x(\d+\.?\d*)x(\d+)x(\d+\.?\d*)$", "sr_ths"),
    (r"^s_tho(\d+\.?\d*)x(\d+\.?\d*)x(\d+\.?\d*)x(\d+)x(\d+\.?\d*)$", "s_tho"),
    (r"^s_thr(\d+\.?\d*)x(\d+\.?\d*)x(\d+\.?\d*)x(\d+)x(\d+\.?\d*)$", "s_thr"),
    (r"^s_ths(\d+\.?\d*)x(\d+\.?\d*)x(\d+\.?\d*)x(\d+)x(\d+\.?\d*)$", "s_ths"),
    (r"^ths(\d+\.?\d*)x(\d+\.?\d*)x(\d+\.?\d*)x(\d+)x(\d+\.?\d*)$", "ths"),
    (r"^thr(\d+\.?\d*)x(\d+\.?\d*)x(\d+\.?\d*)x(\d+)x(\d+\.?\d*)$", "thr"),

    # Donuts
    (r"^donut_rc(\d+\.?\d*)x(\d+\.?\d*)x(\d+\.?\d*)$", "donut_rc"),
    (r"^donut_o(\d+\.?\d*)x(\d+\.?\d*)x(\d+\.?\d*)$", "donut_o"),
    (r"^donut_sr(\d+\.?\d*)x(\d+\.?\d*)$", "donut_sr"),
    (r"^donut_s(\d+\.?\d*)x(\d+\.?\d*)$", "donut_s"),
    (r"^donut_r(\d+\.?\d*)x(\d+\.?\d*)$", "donut_r"),

    # Rectangles with corner modifications
    (r"^rect(\d+\.?\d*)x(\d+\.?\d*)xr(\d+\.?\d*)(?:x(\d+))?$", "rect_round"),
    (r"^rect(\d+\.?\d*)x(\d+\.?\d*)xc(\d+\.?\d*)(?:x(\d+))?$", "rect_chamfer"),

    # Basic shapes
    (r"^oval_h(\d+\.?\d*)x(\d+\.?\d*)$", "half_oval"),
    (r"^oct(\d+\.?\d*)x(\d+\.?\d*)x(\d+\.?\d*)$", "octagon"),
    (r"^hex_l(\d+\.?\d*)x(\d+\.?\d*)x(\d+\.?\d*)$", "hex_l"),
    (r"^hex_s(\d+\.?\d*)x(\d+\.?\d*)x(\d+\.?\d*)$", "hex_s"),
    (r"^tri(\d+\.?\d*)x(\d+\.?\d*)$", "triangle"),
    (r"^di(\d+\.?\d*)x(\d+\.?\d*)$", "diamond"),
    (r"^el(\d+\.?\d*)x(\d+\.?\d*)$", "ellipse"),
    (r"^oval(\d+\.?\d*)x(\d+\.?\d*)$", "oval"),
    (r"^rect(\d+\.?\d*)x(\d+\.?\d*)$", "rect"),
    (r"^bfr(\d+\.?\d*)$", "butterfly"),
    (r"^bfs(\d+\.?\d*)$", "sq_butterfly"),
    (r"^r(\d+\.?\d*)$", "round"),
    (r"^s(\d+\.?\d*)$", "square"),

    # Special symbols
    (r"^moire(\d+\.?\d*)x(\d+\.?\d*)x(\d+)x(\d+\.?\d*)x(\d+\.?\d*)x(\d+\.?\d*)$", "moire"),
    (r"^hole(\d+\.?\d*)x(\w+)x(\d+\.?\d*)x(\d+\.?\d*)$", "hole"),
    (r"^null(\d+)$", "null"),
]

# Compile patterns once
_COMPILED_PATTERNS = [(re.compile(p), t) for p, t in _PATTERNS]


def resolve_symbol(name: str) -> StandardSymbol:
    """Parse a standard symbol name and return its geometric parameters.

    Args:
        name: Symbol name string (e.g., 'r120', 'rect20x60')

    Returns:
        StandardSymbol with type and parameters.
        Returns type='user_defined' if no standard pattern matches.
    """
    for pattern, sym_type in _COMPILED_PATTERNS:
        match = pattern.match(name)
        if match:
            return _build_symbol(name, sym_type, match)

    # No standard pattern matched - assume user-defined symbol
    return StandardSymbol(name=name, type="user_defined")


def _build_symbol(name: str, sym_type: str, match: re.Match) -> StandardSymbol:
    """Build a StandardSymbol from a regex match."""
    groups = match.groups()
    params = {}
    w = 0.0
    h = 0.0

    if sym_type == "round":
        d = float(groups[0])
        params = {"diameter": d}
        w = h = d

    elif sym_type == "square":
        s = float(groups[0])
        params = {"side": s}
        w = h = s

    elif sym_type in ("rect", "rect_round", "rect_chamfer"):
        w = float(groups[0])
        h = float(groups[1])
        params = {"width": w, "height": h}
        if sym_type == "rect_round":
            params["corner_radius"] = float(groups[2])
            params["corners"] = groups[3] if groups[3] else "1234"
        elif sym_type == "rect_chamfer":
            params["corner_size"] = float(groups[2])
            params["corners"] = groups[3] if groups[3] else "1234"

    elif sym_type == "oval":
        w = float(groups[0])
        h = float(groups[1])
        params = {"width": w, "height": h}

    elif sym_type == "diamond":
        w = float(groups[0])
        h = float(groups[1])
        params = {"width": w, "height": h}

    elif sym_type == "octagon":
        w = float(groups[0])
        h = float(groups[1])
        r = float(groups[2])
        params = {"width": w, "height": h, "corner_size": r}

    elif sym_type in ("hex_l", "hex_s"):
        w = float(groups[0])
        h = float(groups[1])
        r = float(groups[2])
        params = {"width": w, "height": h, "corner_size": r}

    elif sym_type == "triangle":
        base = float(groups[0])
        h = float(groups[1])
        w = base
        params = {"base": base, "height": h}

    elif sym_type == "ellipse":
        w = float(groups[0])
        h = float(groups[1])
        params = {"width": w, "height": h}

    elif sym_type == "half_oval":
        w = float(groups[0])
        h = float(groups[1])
        params = {"width": w, "height": h}

    elif sym_type == "donut_r":
        od = float(groups[0])
        id_ = float(groups[1])
        params = {"outer_diameter": od, "inner_diameter": id_}
        w = h = od

    elif sym_type == "donut_s":
        od = float(groups[0])
        id_ = float(groups[1])
        params = {"outer_size": od, "inner_size": id_}
        w = h = od

    elif sym_type == "donut_sr":
        od = float(groups[0])
        id_ = float(groups[1])
        params = {"outer_size": od, "inner_diameter": id_}
        w = h = od

    elif sym_type == "donut_rc":
        ow = float(groups[0])
        oh = float(groups[1])
        lw = float(groups[2])
        params = {"outer_width": ow, "outer_height": oh, "line_width": lw}
        w, h = ow, oh

    elif sym_type == "donut_o":
        ow = float(groups[0])
        oh = float(groups[1])
        lw = float(groups[2])
        params = {"outer_width": ow, "outer_height": oh, "line_width": lw}
        w, h = ow, oh

    elif sym_type in ("thr", "ths"):
        od = float(groups[0])
        id_ = float(groups[1])
        angle = float(groups[2])
        spokes = int(groups[3])
        gap = float(groups[4])
        params = {"outer_diameter": od, "inner_diameter": id_,
                  "angle": angle, "num_spokes": spokes, "gap": gap}
        w = h = od

    elif sym_type in ("s_ths", "s_tho", "s_thr"):
        os_ = float(groups[0])
        is_ = float(groups[1])
        angle = float(groups[2])
        spokes = int(groups[3])
        gap = float(groups[4])
        params = {"outer_size": os_, "inner_size": is_,
                  "angle": angle, "num_spokes": spokes, "gap": gap}
        w = h = os_

    elif sym_type == "sr_ths":
        os_ = float(groups[0])
        id_ = float(groups[1])
        angle = float(groups[2])
        spokes = int(groups[3])
        gap = float(groups[4])
        params = {"outer_size": os_, "inner_diameter": id_,
                  "angle": angle, "num_spokes": spokes, "gap": gap}
        w = h = os_

    elif sym_type in ("rc_ths", "rc_tho"):
        rw = float(groups[0])
        rh = float(groups[1])
        angle = float(groups[2])
        spokes = int(groups[3])
        gap = float(groups[4])
        air_gap = float(groups[5])
        params = {"width": rw, "height": rh, "angle": angle,
                  "num_spokes": spokes, "gap": gap, "air_gap": air_gap}
        w, h = rw, rh

    elif sym_type == "o_ths":
        ow = float(groups[0])
        oh = float(groups[1])
        angle = float(groups[2])
        spokes = int(groups[3])
        gap = float(groups[4])
        lw = float(groups[5])
        params = {"outer_width": ow, "outer_height": oh, "angle": angle,
                  "num_spokes": spokes, "gap": gap, "line_width": lw}
        w, h = ow, oh

    elif sym_type == "butterfly":
        d = float(groups[0])
        params = {"diameter": d}
        w = h = d

    elif sym_type == "sq_butterfly":
        s = float(groups[0])
        params = {"side": s}
        w = h = s

    elif sym_type == "moire":
        params = {
            "ring_width": float(groups[0]),
            "ring_gap": float(groups[1]),
            "num_rings": int(groups[2]),
            "line_width": float(groups[3]),
            "line_length": float(groups[4]),
            "line_angle": float(groups[5]),
        }

    elif sym_type == "hole":
        d = float(groups[0])
        params = {"diameter": d, "plating": groups[1],
                  "tolerance_plus": float(groups[2]),
                  "tolerance_minus": float(groups[3])}
        w = h = d

    elif sym_type == "null":
        params = {"ext": int(groups[0])}

    return StandardSymbol(name=name, type=sym_type, params=params, width=w, height=h)


def get_symbol_size(name: str, units: str = "INCH") -> tuple[float, float]:
    """Get the physical size of a symbol in the file's units.

    Symbol dimensions are in mils (imperial) or microns (metric).
    This function converts to inches or mm based on the units parameter.

    Returns (width, height) in the file's coordinate units.
    """
    sym = resolve_symbol(name)
    w = sym.width
    h = sym.height

    if units == "INCH":
        # Symbol params are in mils, convert to inches
        w /= 1000.0
        h /= 1000.0
    else:
        # Symbol params are in microns, convert to mm
        w /= 1000.0
        h /= 1000.0

    return w, h


def get_line_width(name: str, units: str = "INCH") -> float:
    """Get the line width for a symbol used as a trace aperture.

    For round symbols (r<d>), returns the diameter converted to file units.
    For other shapes, returns the width.
    """
    sym = resolve_symbol(name)

    if sym.type == "round":
        d = sym.params.get("diameter", 0.0)
    elif sym.type == "square":
        d = sym.params.get("side", 0.0)
    else:
        d = sym.width

    if units == "INCH":
        return d / 1000.0  # mils to inches
    else:
        return d / 1000.0  # microns to mm
