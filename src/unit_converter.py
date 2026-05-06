"""Unit normalization helpers shared across the ODB++ processing pipeline.

All coordinate data in the system is normalized to MM after loading.
These functions perform in-place scaling of parsed data structures.
"""

from __future__ import annotations

from src.models import (
    ArcRecord, ArcSegment, BarcodeRecord, LineRecord,
    LineSegment, PadRecord, SurfaceRecord, TextRecord,
)

INCH_TO_MM: float = 25.4


def unit_scale(from_units: str, to_units: str) -> float:
    """Return the multiplier to convert from_units coordinates to to_units."""
    if from_units == to_units:
        return 1.0
    if from_units == "INCH" and to_units == "MM":
        return 25.4
    if from_units == "MM" and to_units == "INCH":
        return 1.0 / 25.4
    return 1.0


def scale_components(comps: list, factor: float) -> None:
    """Scale component board coordinates (x, y and toeprint positions) in place."""
    for comp in comps:
        comp.x *= factor
        comp.y *= factor
        for tp in comp.toeprints:
            tp.x *= factor
            tp.y *= factor


def scale_outline_params(outline, factor: float) -> None:
    """Scale a PinOutline's coordinate parameters in place."""
    p = outline.params
    if outline.type == "RC":
        for k in ("llx", "lly", "width", "height"):
            if k in p:
                p[k] *= factor
    elif outline.type in ("CR", "CT"):
        for k in ("xc", "yc", "radius"):
            if k in p:
                p[k] *= factor
    elif outline.type == "SQ":
        for k in ("xc", "yc", "half_side"):
            if k in p:
                p[k] *= factor
    elif outline.type == "CONTOUR" and outline.contour:
        c = outline.contour
        c.start.x *= factor
        c.start.y *= factor
        for seg in c.segments:
            if isinstance(seg, LineSegment):
                seg.end.x *= factor
                seg.end.y *= factor
            elif isinstance(seg, ArcSegment):
                seg.end.x *= factor
                seg.end.y *= factor
                seg.center.x *= factor
                seg.center.y *= factor


def scale_eda_data(eda, factor: float) -> None:
    """Scale EDA package coordinate data (bounding boxes, pin centres, outlines) in place."""
    for pkg in eda.packages:
        if pkg.bbox:
            pkg.bbox.xmin *= factor
            pkg.bbox.xmax *= factor
            pkg.bbox.ymin *= factor
            pkg.bbox.ymax *= factor
        pkg.pitch *= factor
        for pin in pkg.pins:
            pin.center.x *= factor
            pin.center.y *= factor
            pin.finished_hole_size *= factor
            for ol in pin.outlines:
                scale_outline_params(ol, factor)
        for ol in pkg.outlines:
            scale_outline_params(ol, factor)


def scale_profile(profile, factor: float) -> None:
    """Scale profile surface coordinates in place."""
    if not profile or not profile.surface:
        return
    for contour in profile.surface.contours:
        contour.start.x *= factor
        contour.start.y *= factor
        for seg in contour.segments:
            seg.end.x *= factor
            seg.end.y *= factor
            if isinstance(seg, ArcSegment):
                seg.center.x *= factor
                seg.center.y *= factor


def scale_layer_features(features, factor: float) -> None:
    """Scale all feature coordinates in place."""
    for feat in features.features:
        if isinstance(feat, LineRecord):
            feat.xs *= factor
            feat.ys *= factor
            feat.xe *= factor
            feat.ye *= factor
        elif isinstance(feat, PadRecord):
            feat.x *= factor
            feat.y *= factor
        elif isinstance(feat, ArcRecord):
            feat.xs *= factor
            feat.ys *= factor
            feat.xe *= factor
            feat.ye *= factor
            feat.xc *= factor
            feat.yc *= factor
        elif isinstance(feat, TextRecord):
            feat.x *= factor
            feat.y *= factor
            feat.xsize *= factor
            feat.ysize *= factor
        elif isinstance(feat, BarcodeRecord):
            feat.x *= factor
            feat.y *= factor
            feat.width *= factor
            feat.height *= factor
        elif isinstance(feat, SurfaceRecord):
            for contour in feat.contours:
                contour.start.x *= factor
                contour.start.y *= factor
                for seg in contour.segments:
                    seg.end.x *= factor
                    seg.end.y *= factor
                    if isinstance(seg, ArcSegment):
                        seg.center.x *= factor
                        seg.center.y *= factor


def scale_user_symbols(user_symbols: dict, factor: float) -> None:
    """Scale coordinates of all user-defined symbols in place.

    Handles every feature type the symbol renderer can consume (line, pad,
    arc, text, surface).  Skips symbols already in MM (units != "INCH").
    """
    for symbol in user_symbols.values():
        if symbol.units == "INCH":
            for feat in symbol.features:
                if isinstance(feat, LineRecord):
                    feat.xs *= factor
                    feat.ys *= factor
                    feat.xe *= factor
                    feat.ye *= factor
                elif isinstance(feat, PadRecord):
                    feat.x *= factor
                    feat.y *= factor
                elif isinstance(feat, ArcRecord):
                    feat.xs *= factor
                    feat.ys *= factor
                    feat.xe *= factor
                    feat.ye *= factor
                    feat.xc *= factor
                    feat.yc *= factor
                elif isinstance(feat, TextRecord):
                    feat.x *= factor
                    feat.y *= factor
                    feat.xsize *= factor
                    feat.ysize *= factor
                elif isinstance(feat, SurfaceRecord):
                    for contour in feat.contours:
                        contour.start.x *= factor
                        contour.start.y *= factor
                        for seg in contour.segments:
                            seg.end.x *= factor
                            seg.end.y *= factor
                            if isinstance(seg, ArcSegment):
                                seg.center.x *= factor
                                seg.center.y *= factor
            symbol.units = "MM"
