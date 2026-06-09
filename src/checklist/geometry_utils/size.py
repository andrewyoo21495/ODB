"""Component size utilities.

Provides:
- get_component_size   — numeric size code (LLWW metric)
- size_at_least        — threshold comparison
- filter_by_size       — filter component list by size
"""

from __future__ import annotations

from typing import Sequence

from src.models import Component, Package


def _size_from_description(comp: Component, desc_index: int) -> int | None:
    """Extract a numeric size code from the DESCRIPTION property.

    The DESCRIPTION field is a comma-separated string, e.g.
    ``"1.2nH,0.1Nh,0603,T0.3,0.1Ohm, ..."``.

    *desc_index* specifies the 0-based position of the size token within
    the comma-separated list.  For inductors this is typically ``2``
    (3rd field), for capacitors ``5`` (6th field).

    Returns None when no usable DESCRIPTION property is present or the
    token at the requested index is not a valid size code.
    """
    props = getattr(comp, "properties", None) or {}
    if not props:
        return None
    for key, value in props.items():
        if isinstance(key, str) and key.strip().upper() == "DESCRIPTION":
            if value is None:
                continue
            parts = [p.strip() for p in str(value).split(",")]
            if desc_index < 0 or desc_index >= len(parts):
                continue
            token = parts[desc_index]
            if token.isdigit():
                return int(token)
            try:
                return int(round(float(token)))
            except (TypeError, ValueError):
                continue
    return None


def get_component_size(comp: Component,
                       size_maps: list[dict[str, int]] | None = None,
                       packages: list[Package] | None = None,
                       desc_index: int | None = None) -> int:
    """Return the numeric size code for comp.

    Resolution order:
        1. comp.properties["DESCRIPTION"] — extract the comma-separated
           token at position *desc_index* (0-based).  Skipped when
           *desc_index* is ``None``.
        2. Lookup comp.part_name in the provided size_maps
        3. Parse from package bbox dimensions (metric LLWW code)
        4. Return 0 if unknown
    """
    if desc_index is not None:
        sz = _size_from_description(comp, desc_index)
        if sz is not None:
            return sz

    part = comp.part_name or ""

    if size_maps:
        for sm in size_maps:
            if part in sm:
                return sm[part]
            # Partial match: actual part_name may contain the reference
            # part_name as a substring (e.g. "2703-004127_PBK_L6000")
            for ref_pn, ref_sz in sm.items():
                if ref_pn and ref_pn in part:
                    return ref_sz

    if packages and 0 <= comp.pkg_ref < len(packages):
        pkg = packages[comp.pkg_ref]
        if pkg.bbox:
            w_mm = abs(pkg.bbox.xmax - pkg.bbox.xmin)
            h_mm = abs(pkg.bbox.ymax - pkg.bbox.ymin)
            l_code = int(round(max(w_mm, h_mm) * 10))
            w_code = int(round(min(w_mm, h_mm) * 10))
            return l_code * 100 + w_code

    return 0


def size_at_least(size_code: int, threshold: int = 2012) -> bool:
    """Return True if size_code >= threshold."""
    return size_code >= threshold


def filter_by_size(components: Sequence[Component],
                   threshold: int,
                   size_maps: list[dict[str, int]] | None = None,
                   packages: list[Package] | None = None,
                   desc_index: int | None = None,
                   ) -> list[tuple[Component, int]]:
    """Return (component, size) pairs for components with size >= threshold."""
    result: list[tuple[Component, int]] = []
    for comp in components:
        sz = get_component_size(comp, size_maps, packages, desc_index=desc_index)
        if sz >= threshold:
            result.append((comp, sz))
    return result
