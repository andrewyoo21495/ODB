"""Component size utilities.

Provides:
- get_component_size   — numeric size code (LLWW metric)
- size_at_least        — threshold comparison
- filter_by_size       — filter component list by size
"""

from __future__ import annotations

from typing import Sequence

from src.models import Component, Package


def _size_from_properties(comp: Component) -> int | None:
    """Read a numeric size code from comp's properties dict.

    Looks for a SIZE key (case-insensitive) and returns the value parsed as
    an int.  Returns None when no usable SIZE property is present.
    """
    props = getattr(comp, "properties", None) or {}
    if not props:
        return None
    for key, value in props.items():
        if isinstance(key, str) and key.strip().upper() == "SIZE":
            if value is None:
                continue
            sv = str(value).strip()
            if sv.isdigit():
                return int(sv)
            try:
                return int(round(float(sv)))
            except (TypeError, ValueError):
                continue
    return None


def get_component_size(comp: Component,
                       size_maps: list[dict[str, int]] | None = None,
                       packages: list[Package] | None = None) -> int:
    """Return the numeric size code for comp.

    Resolution order:
        1. comp.properties["SIZE"] (case-insensitive)
        2. Lookup comp.part_name in the provided size_maps
        3. Parse from package bbox dimensions (metric LLWW code)
        4. Return 0 if unknown
    """
    sz = _size_from_properties(comp)
    if sz is not None:
        return sz

    part = comp.part_name or ""

    if size_maps:
        for sm in size_maps:
            if part in sm:
                return sm[part]

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
                   ) -> list[tuple[Component, int]]:
    """Return (component, size) pairs for components with size >= threshold."""
    result: list[tuple[Component, int]] = []
    for comp in components:
        sz = get_component_size(comp, size_maps, packages)
        if sz >= threshold:
            result.append((comp, sz))
    return result
