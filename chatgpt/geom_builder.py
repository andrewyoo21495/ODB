####################################################################################
## 2) geom_builder.py

## Symbol outlines → Shapely geometry(Polygon/Point)로 변환. 
# 또한 P 레코드(패드 feature)의 파라미터를 읽어 Symbol을 적용하고 rotate/translate 합니다. 
# 다양한 outline types (RC, CR, OB, OC, OS, SQ, CT)에 대해 기본 변환을 제공합니다. 
# (여기서 OB/OC/OS는 약식으로 처리하지만 주요 파라미터를 반영하도록 구현되어 있습니다.)
####################################################################################

# geom_builder.py
from typing import Optional, Dict, Tuple
from shapely.geometry import Polygon, Point, LineString
from shapely.affinity import rotate, translate
from symbol_parser import Symbol, SymbolOutline
import math

"""
Convert Symbol outlines to Shapely geometries.

Supported outlines (common):
 - RC: rectangle given (x_ll y_ll width height) OR (x y w h) depending on symbol
 - CR: circle (cx cy radius)
 - OB: oblong (cx cy length width) -> approximated as rectangle with rounded ends -> approximated with rectangle for performance
 - OC: oblong by center? (cx cy major minor) treat similar to OB
 - OS: oblong using start/end? (approx with rectangle)
 - SQ: square (x y size) or (cx cy size) -> approximated as rect
 - CT: complex/tool? (attempt fallback to box)
If a symbol has multiple outlines, uses the first for basic shape. Extend as needed.
"""

def outline_to_geometry(out: SymbolOutline) -> Optional[Polygon]:
    t = out.type.upper()
    p = out.params
    if t == 'RC':
        # Common representations: [x y w h] or [x_ll y_ll r] (some specs vary)
        if len(p) >= 4:
            x, y, w, h = p[0], p[1], p[2], p[3]
            return Polygon([(x,y),(x+w,y),(x+w,y+h),(x,y+h)])
        elif len(p) == 3:
            x, y, r = p
            # fallback to square of size 2r
            return Polygon([(x-r,y-r),(x+r,y-r),(x+r,y+r),(x-r,y+r)])
    if t == 'CR':
        if len(p) >= 3:
            cx, cy, r = p[0], p[1], p[2]
            return Point(cx,cy).buffer(r)
    if t in ('OB','OC','OS'):
        # Many formats; common: center x,y then major length and minor width
        if len(p) >= 4:
            cx, cy, major, minor = p[0], p[1], p[2], p[3]
            # approximate oblong by rectangle aligned on center
            return Polygon([(cx-major/2, cy-minor/2), (cx+major/2, cy-minor/2),
                            (cx+major/2, cy+minor/2), (cx-major/2, cy+minor/2)])
        elif len(p) >= 3:
            cx, cy, r = p[0], p[1], p[2]
            return Point(cx,cy).buffer(r)
    if t == 'SQ':
        if len(p) >= 3:
            x, y, s = p[0], p[1], p[2]
            return Polygon([(x,y),(x+s,y),(x+s,y+s),(x,y+s)])
    if t == 'CT':
        # CT might be center + tool radius; attempt circle
        if len(p) >= 3:
            cx, cy, r = p[0], p[1], p[2]
            return Point(cx,cy).buffer(r)
    # Fallback: if outline has numbers, create small square around first two nums
    if len(p) >= 2:
        x, y = p[0], p[1]
        return Polygon([(x-0.01,y-0.01),(x+0.01,y-0.01),(x+0.01,y+0.01),(x-0.01,y+0.01)])
    return None

def symbol_to_geometry(sym: Symbol, prefer_outline_index: int = 0):
    """
    Returns a shapely geometry for the symbol (first outline by default).
    """
    if not sym or not sym.outlines:
        return None
    outline = sym.outlines[prefer_outline_index]
    geom = outline_to_geometry(outline)
    return geom

def apply_transform(geom, cx: float, cy: float, orient_deg: float, mirror: bool = False):
    """
    Rotate geometry by orient_deg around origin (0,0), then translate to (cx,cy).
    If mirror True, mirror across X axis before rotation (simple approach).
    """
    if geom is None:
        return None
    g = geom
    if mirror:
        # mirror across X axis: scale y by -1 around origin
        from shapely.affinity import scale
        g = scale(g, xfact=1.0, yfact=-1.0, origin=(0,0))
    if orient_deg and abs(orient_deg) > 1e-9:
        g = rotate(g, orient_deg, origin=(0,0), use_radians=False)
    if (cx != 0.0) or (cy != 0.0):
        g = translate(g, cx, cy)
    return g

def pad_feature_to_polygon(feat, layer_symbols: Dict[int, Symbol], default_orient: float = 0.0):
    """
    Convert a LayerFeature of type 'P' (pad) to a shapely polygon.
    feat.params expected format is flexible; common patterns:
    P <x> <y> <symbolIndex> [polarity] [dcode] [orient] ...
    We'll robustly parse numeric tokens.
    """
    params = feat.params
    # Guard: expect at least x y symbolid
    if len(params) < 3:
        # Not enough tokens
        return None
    try:
        cx = float(params[0])
        cy = float(params[1])
    except Exception:
        return None

    # symbol id might be integer token; some files include quotes or special chars - try int parse on token
    sym_id = None
    for token in params[2:6]:  # scan next few tokens for integer
        try:
            sym_id = int(token)
            break
        except Exception:
            continue
    if sym_id is None:
        # maybe symbol index encoded differently (e.g. symbol=123); find numbers
        import re
        num_re = re.compile(r"-?\d+")
        for token in params[2:]:
            mo = num_re.search(token)
            if mo:
                try:
                    sym_id = int(mo.group(0)); break
                except:
                    pass
    if sym_id is None:
        return None

    # orient: sometimes at param index 5 or 'orient=xx' appear
    orient = default_orient
    for token in params[2:]:
        if token.upper().startswith('ORIENT') or token.upper().startswith('ROT'):
            # try to extract number
            import re
            mm = re.search(r"[-+]?\d*\.?\d+", token)
            if mm:
                orient = float(mm.group(0)); break
    # fallback: if there is a numeric token after sym id, treat as orient if >180 or so it's probably not
    # but we'll not rely on that.

    sym = layer_symbols.get(sym_id)
    if sym is None:
        return None

    base_geom = symbol_to_geometry(sym)
    if base_geom is None:
        return None

    # Many symbols are defined at origin (center/ll depending). We assume symbol coords are relative to origin.
    # Use apply_transform to rotate and translate to pad center.
    poly = apply_transform(base_geom, cx, cy, orient, mirror=False)
    return poly
