"""Standard symbol name resolver.

Parses standard symbol names (e.g., 'r120', 'rect20x60', 'donut_r78.74x27.559')
and generates geometric parameters for rendering.
"""

from __future__ import annotations

import math
import re
from typing import Optional

from src.models import StandardSymbol


# Number pattern helper
_N = r"(\d+\.?\d*)"
_INT = r"(\d+)"

# Symbol name patterns (order matters - more specific patterns first)
_PATTERNS = [
    # Thermals - rounded/cornered variants (most specific first)
    (rf"^rc_ths{_N}x{_N}x{_N}x{_INT}x{_N}x{_N}xr{_N}(?:x{_INT})?$", "rc_ths_round"),
    (rf"^rc_tho{_N}x{_N}x{_N}x{_INT}x{_N}x{_N}$", "rc_tho"),
    (rf"^rc_ths{_N}x{_N}x{_N}x{_INT}x{_N}x{_N}$", "rc_ths"),
    (rf"^o_ths{_N}x{_N}x{_N}x{_INT}x{_N}x{_N}$", "o_ths"),
    (rf"^oblong_ths{_N}x{_N}x{_N}x{_INT}x{_N}x{_N}x([rs])$", "oblong_ths"),
    (rf"^sr_ths{_N}x{_N}x{_N}x{_INT}x{_N}$", "sr_ths"),
    (rf"^s_tho{_N}x{_N}x{_N}x{_INT}x{_N}$", "s_tho"),
    (rf"^s_thr{_N}x{_N}x{_N}x{_INT}x{_N}$", "s_thr"),
    (rf"^s_ths{_N}x{_N}x{_N}x{_INT}x{_N}xr{_N}(?:x{_INT})?$", "s_ths_round"),
    (rf"^s_ths{_N}x{_N}x{_N}x{_INT}x{_N}$", "s_ths"),
    (rf"^ths{_N}x{_N}x{_N}x{_INT}x{_N}$", "ths"),
    (rf"^thr{_N}x{_N}x{_N}x{_INT}x{_N}$", "thr"),

    # Donuts - rounded variants first
    (rf"^donut_rc{_N}x{_N}x{_N}xr{_N}(?:x{_INT})?$", "donut_rc_round"),
    (rf"^donut_rc{_N}x{_N}x{_N}$", "donut_rc"),
    (rf"^donut_o{_N}x{_N}x{_N}$", "donut_o"),
    (rf"^donut_sr{_N}x{_N}$", "donut_sr"),
    (rf"^donut_s{_N}x{_N}xr{_N}(?:x{_INT})?$", "donut_s_round"),
    (rf"^donut_s{_N}x{_N}$", "donut_s"),
    (rf"^donut_r{_N}x{_N}$", "donut_r"),

    # Rectangles with corner modifications
    (rf"^rect{_N}x{_N}xr{_N}(?:x{_INT})?$", "rect_round"),
    (rf"^rect{_N}x{_N}xc{_N}(?:x{_INT})?$", "rect_chamfer"),

    # Stencil design symbols (complex, must come before basic shapes)
    (rf"^dpack{_N}x{_N}x{_N}x{_N}x{_INT}x{_INT}(?:x{_N})?$", "dpack"),
    (rf"^dogbone{_N}x{_N}x{_N}x{_N}x{_N}x([rs])(?:x{_N})?$", "dogbone"),
    (rf"^cross{_N}x{_N}x{_N}x{_N}x{_N}x{_N}x([rs])(?:{_N})?$", "cross"),
    (rf"^radhplate{_N}x{_N}x{_N}(?:x{_N})?$", "radhplate"),
    (rf"^fhplate{_N}x{_N}x{_N}x{_N}(?:x{_N}x{_N})?$", "fhplate"),
    (rf"^rhplate{_N}x{_N}x{_N}(?:x{_N}x{_N})?$", "rhplate"),
    (rf"^hplate{_N}x{_N}x{_N}(?:x{_N}x{_N})?$", "hplate"),
    (rf"^dshape{_N}x{_N}x{_N}(?:x{_N})?$", "dshape"),

    # Basic shapes
    (rf"^oval_h{_N}x{_N}$", "half_oval"),
    (rf"^oct{_N}x{_N}x{_N}$", "octagon"),
    (rf"^hex_l{_N}x{_N}x{_N}$", "hex_l"),
    (rf"^hex_s{_N}x{_N}x{_N}$", "hex_s"),
    (rf"^tri{_N}x{_N}$", "triangle"),
    (rf"^di{_N}x{_N}$", "diamond"),
    (rf"^el{_N}x{_N}$", "ellipse"),
    (rf"^oval{_N}x{_N}$", "oval"),
    (rf"^rect{_N}x{_N}$", "rect"),
    (rf"^bfr{_N}$", "butterfly"),
    (rf"^bfs{_N}$", "sq_butterfly"),
    (rf"^r{_N}$", "round"),
    (rf"^s{_N}$", "square"),

    # Special symbols
    (rf"^moire{_N}x{_N}x{_INT}x{_N}x{_N}x{_N}$", "moire"),
    (rf"^hole{_N}x(\w+)x{_N}x{_N}$", "hole"),
    (rf"^null{_INT}$", "null"),
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

    elif sym_type == "donut_s_round":
        od = float(groups[0])
        id_ = float(groups[1])
        rad = float(groups[2])
        corners = groups[3] if groups[3] else "1234"
        params = {"outer_size": od, "inner_size": id_,
                  "corner_radius": rad, "corners": corners}
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

    elif sym_type == "donut_rc_round":
        ow = float(groups[0])
        oh = float(groups[1])
        lw = float(groups[2])
        rad = float(groups[3])
        corners = groups[4] if groups[4] else "1234"
        params = {"outer_width": ow, "outer_height": oh, "line_width": lw,
                  "corner_radius": rad, "corners": corners}
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

    elif sym_type == "s_ths_round":
        os_ = float(groups[0])
        is_ = float(groups[1])
        angle = float(groups[2])
        spokes = int(groups[3])
        gap = float(groups[4])
        rad = float(groups[5])
        corners = groups[6] if groups[6] else "1234"
        params = {"outer_size": os_, "inner_size": is_,
                  "angle": angle, "num_spokes": spokes, "gap": gap,
                  "corner_radius": rad, "corners": corners}
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

    elif sym_type == "rc_ths_round":
        ow = float(groups[0])
        oh = float(groups[1])
        angle = float(groups[2])
        spokes = int(groups[3])
        gap = float(groups[4])
        lw = float(groups[5])
        rad = float(groups[6])
        corners = groups[7] if groups[7] else "1234"
        params = {"width": ow, "height": oh, "angle": angle,
                  "num_spokes": spokes, "gap": gap, "line_width": lw,
                  "corner_radius": rad, "corners": corners}
        w, h = ow, oh

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

    elif sym_type == "oblong_ths":
        ow = float(groups[0])
        oh = float(groups[1])
        angle = float(groups[2])
        spokes = int(groups[3])
        gap = float(groups[4])
        lw = float(groups[5])
        style = groups[6]  # 'r' or 's'
        params = {"outer_width": ow, "outer_height": oh, "angle": angle,
                  "num_spokes": spokes, "gap": gap, "line_width": lw,
                  "style": style}
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
        rw_val = float(groups[0])
        rg_val = float(groups[1])
        nr = int(groups[2])
        lw_val = float(groups[3])
        ll = float(groups[4])
        la = float(groups[5])
        params = {
            "ring_width": rw_val,
            "ring_gap": rg_val,
            "num_rings": nr,
            "line_width": lw_val,
            "line_length": ll,
            "line_angle": la,
        }
        total = 2 * nr * (rw_val + rg_val)
        w = h = max(total, ll)

    elif sym_type == "hole":
        d = float(groups[0])
        params = {"diameter": d, "plating": groups[1],
                  "tolerance_plus": float(groups[2]),
                  "tolerance_minus": float(groups[3])}
        w = h = d

    elif sym_type == "null":
        params = {"ext": int(groups[0])}

    # Stencil design symbols
    elif sym_type == "hplate":
        w = float(groups[0])
        h = float(groups[1])
        c = float(groups[2])
        params = {"width": w, "height": h, "cut_size": c}
        if groups[3] is not None:
            params["radius_acute"] = float(groups[3])
            params["radius_obtuse"] = float(groups[4])

    elif sym_type == "rhplate":
        w = float(groups[0])
        h = float(groups[1])
        c = float(groups[2])
        params = {"width": w, "height": h, "cut_size": c}
        if groups[3] is not None:
            params["radius_acute"] = float(groups[3])
            params["radius_obtuse"] = float(groups[4])

    elif sym_type == "fhplate":
        w = float(groups[0])
        h = float(groups[1])
        vc = float(groups[2])
        hc = float(groups[3])
        params = {"width": w, "height": h, "vert_cut": vc, "horiz_cut": hc}
        if groups[4] is not None:
            params["radius_acute"] = float(groups[4])
            params["radius_obtuse"] = float(groups[5])

    elif sym_type == "radhplate":
        w = float(groups[0])
        h = float(groups[1])
        ms = float(groups[2])
        params = {"width": w, "height": h, "middle_size": ms}
        if groups[3] is not None:
            params["radius_acute"] = float(groups[3])

    elif sym_type == "dshape":
        w = float(groups[0])
        h = float(groups[1])
        r = float(groups[2])
        params = {"width": w, "height": h, "relief": r}
        if groups[3] is not None:
            params["radius_acute"] = float(groups[3])

    elif sym_type == "cross":
        w = float(groups[0])
        h = float(groups[1])
        hs = float(groups[2])
        vs = float(groups[3])
        hc = float(groups[4])
        vc = float(groups[5])
        style = groups[6]  # 'r' or 's'
        params = {"width": w, "height": h,
                  "horiz_line_width": hs, "vert_line_width": vs,
                  "horiz_cross_point": hc, "vert_cross_point": vc,
                  "style": style}
        if groups[7] is not None:
            params["corner_radius"] = float(groups[7])

    elif sym_type == "dogbone":
        w = float(groups[0])
        h = float(groups[1])
        hs = float(groups[2])
        vs = float(groups[3])
        hc = float(groups[4])
        style = groups[5]  # 'r' or 's'
        params = {"width": w, "height": h,
                  "horiz_line_width": hs, "vert_line_width": vs,
                  "horiz_cross_point": hc, "style": style}
        if groups[6] is not None:
            params["corner_radius"] = float(groups[6])

    elif sym_type == "dpack":
        w = float(groups[0])
        h = float(groups[1])
        hg = float(groups[2])
        vg = float(groups[3])
        hn = int(groups[4])
        vn = int(groups[5])
        params = {"width": w, "height": h,
                  "horiz_gap": hg, "vert_gap": vg,
                  "num_rows": hn, "num_cols": vn}
        if groups[6] is not None:
            params["corner_radius"] = float(groups[6])

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
