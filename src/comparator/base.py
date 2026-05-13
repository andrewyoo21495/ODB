"""Base class and data models for ODB++ revision comparison."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ChangeType(Enum):
    """Component-level change classification."""
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    RELOCATED = "RELOCATED"
    MODIFIED = "MODIFIED"
    UNCHANGED = "UNCHANGED"


class ChecklistTransition(Enum):
    """Checklist rule status transition between revisions."""
    FIXED = "FIXED"                # was FAIL, now PASS
    REGRESSED = "REGRESSED"        # was PASS, now FAIL
    STILL_FAIL = "STILL_FAIL"      # was FAIL, still FAIL
    STILL_PASS = "STILL_PASS"      # was PASS, still PASS
    NEW_RULE = "NEW_RULE"          # rule only in new revision
    REMOVED_RULE = "REMOVED_RULE"  # rule only in old revision


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ComponentChange:
    """One component-level change between revisions."""
    comp_name: str
    layer: str                              # "Top" or "Bottom"
    change_type: ChangeType
    part_name: str = ""
    old_part_name: str = ""                 # for MODIFIED: previous part_name
    # Old position (None if ADDED)
    old_x: Optional[float] = None
    old_y: Optional[float] = None
    old_rotation: Optional[float] = None
    old_mirror: Optional[bool] = None
    # New position (None if REMOVED)
    new_x: Optional[float] = None
    new_y: Optional[float] = None
    new_rotation: Optional[float] = None
    new_mirror: Optional[bool] = None
    # Computed deltas (only for RELOCATED)
    delta_x: Optional[float] = None
    delta_y: Optional[float] = None
    delta_rotation: Optional[float] = None
    mirror_changed: bool = False


@dataclass
class ChecklistChange:
    """One checklist rule change between revisions."""
    rule_id: str
    description: str
    category: str
    transition: ChecklistTransition
    old_status: Optional[str] = None        # "PASS", "FAIL", or None
    new_status: Optional[str] = None        # "PASS", "FAIL", or None
    old_message: str = ""
    new_message: str = ""
    old_affected_count: int = 0
    new_affected_count: int = 0


@dataclass
class SheetConfig:
    """Describes one Excel sheet to be generated in the comparison report."""
    sheet_name: str                         # Excel tab name (max 31 chars)
    title: str                              # Title row text
    columns: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    images: list[dict] = field(default_factory=list)
    # Each image dict: {"path": Path, "title": str, "width": int}


@dataclass
class ComparisonResult:
    """Result from a single comparator module."""
    comparator_id: str                      # e.g. "COMP-DIFF", "CKL-DIFF"
    title: str                              # Human-readable title
    summary: str                            # One-line summary message
    sheet_configs: list[SheetConfig] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class ComparatorBase(ABC):
    """Abstract base for comparison modules.

    Mirrors the ChecklistRule pattern: each comparator has an ID and
    produces a ComparisonResult.
    """
    comparator_id: str = ""
    title: str = ""

    @abstractmethod
    def compare(self, old_data: dict, new_data: dict) -> ComparisonResult:
        """Compare old and new job data, return structured results.

        Args:
            old_data: dict from _load_from_cache() for old revision.
            new_data: dict from _load_from_cache() for new revision.

        Returns:
            ComparisonResult with sheet configurations for the report.
        """
        raise NotImplementedError
