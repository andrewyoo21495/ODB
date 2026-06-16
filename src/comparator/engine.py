"""Comparison engine: registry and orchestration."""

from __future__ import annotations

import importlib
import pkgutil

from src.comparator.base import ComparatorBase, ComparisonResult


# Comparator registry
_REGISTERED_COMPARATORS: list[type[ComparatorBase]] = []
_COMPARATORS_DISCOVERED = False


def register_comparator(cls: type[ComparatorBase]) -> type[ComparatorBase]:
    """Decorator to register a comparator class."""
    _REGISTERED_COMPARATORS.append(cls)
    return cls


def get_registered_comparators() -> list[type[ComparatorBase]]:
    """Get all registered comparator classes."""
    return list(_REGISTERED_COMPARATORS)


def discover_comparators() -> list[type[ComparatorBase]]:
    """Import every module in ``src.comparator.comparators`` so that their
    ``@register_comparator`` decorators run.  Idempotent.  Returns the
    registered comparator classes.
    """
    global _COMPARATORS_DISCOVERED
    if not _COMPARATORS_DISCOVERED:
        import src.comparator.comparators as pkg
        for name in sorted(m.name for m in pkgutil.iter_modules(pkg.__path__)):
            importlib.import_module(f"{pkg.__name__}.{name}")
        _COMPARATORS_DISCOVERED = True
    return get_registered_comparators()


def run_comparison(old_data: dict, new_data: dict,
                   comparator_ids: list[str] = None) -> list[ComparisonResult]:
    """Run all (or selected) comparators and return results.

    Args:
        old_data: job data dict for old revision.
        new_data: job data dict for new revision.
        comparator_ids: optional filter; if None, runs all registered.

    Returns:
        List of ComparisonResult, one per comparator.
    """
    comparators = [cls() for cls in _REGISTERED_COMPARATORS]
    if comparator_ids:
        comparators = [c for c in comparators
                       if c.comparator_id in comparator_ids]

    results: list[ComparisonResult] = []
    for comp in comparators:
        try:
            result = comp.compare(old_data, new_data)
            results.append(result)
        except Exception as e:
            results.append(ComparisonResult(
                comparator_id=comp.comparator_id,
                title=comp.title,
                summary=f"Comparison error: {e}",
                sheet_configs=[],
            ))
    return results
