"""Component diff comparator: identifies ADDED, REMOVED, RELOCATED, and
MODIFIED components between two ODB++ revisions on Top and Bottom layers."""

from __future__ import annotations

from src.comparator.base import (
    ChangeType, ComponentChange, ComparatorBase, ComparisonResult, SheetConfig,
)
from src.comparator.engine import register_comparator

# Tolerance thresholds
POSITION_TOLERANCE = 0.01    # mm
ROTATION_TOLERANCE = 0.1     # degrees


def _diff_layer(old_comps: list, new_comps: list,
                layer: str) -> list[ComponentChange]:
    """Compare components on a single layer and return a list of changes.

    Components are matched by ``comp_name`` (reference designator), which is
    unique per layer within a single revision.
    """
    old_map = {c.comp_name: c for c in old_comps}
    new_map = {c.comp_name: c for c in new_comps}

    old_names = set(old_map.keys())
    new_names = set(new_map.keys())

    changes: list[ComponentChange] = []

    # ADDED: in new but not old
    for name in sorted(new_names - old_names):
        c = new_map[name]
        changes.append(ComponentChange(
            comp_name=name, layer=layer, change_type=ChangeType.ADDED,
            part_name=c.part_name,
            new_x=c.x, new_y=c.y,
            new_rotation=c.rotation, new_mirror=c.mirror,
        ))

    # REMOVED: in old but not new
    for name in sorted(old_names - new_names):
        c = old_map[name]
        changes.append(ComponentChange(
            comp_name=name, layer=layer, change_type=ChangeType.REMOVED,
            part_name=c.part_name,
            old_x=c.x, old_y=c.y,
            old_rotation=c.rotation, old_mirror=c.mirror,
        ))

    # RELOCATED / MODIFIED / UNCHANGED: present in both revisions
    for name in sorted(old_names & new_names):
        old_c = old_map[name]
        new_c = new_map[name]

        dx = abs(new_c.x - old_c.x)
        dy = abs(new_c.y - old_c.y)
        dr = abs(new_c.rotation - old_c.rotation) % 360
        dr = min(dr, 360 - dr)  # handle wrap-around
        mirror_changed = old_c.mirror != new_c.mirror
        part_changed = old_c.part_name != new_c.part_name

        position_changed = (dx > POSITION_TOLERANCE
                            or dy > POSITION_TOLERANCE
                            or dr > ROTATION_TOLERANCE
                            or mirror_changed)

        if position_changed:
            changes.append(ComponentChange(
                comp_name=name, layer=layer, change_type=ChangeType.RELOCATED,
                part_name=new_c.part_name,
                old_part_name=old_c.part_name if part_changed else "",
                old_x=old_c.x, old_y=old_c.y,
                old_rotation=old_c.rotation, old_mirror=old_c.mirror,
                new_x=new_c.x, new_y=new_c.y,
                new_rotation=new_c.rotation, new_mirror=new_c.mirror,
                delta_x=round(new_c.x - old_c.x, 4),
                delta_y=round(new_c.y - old_c.y, 4),
                delta_rotation=round(new_c.rotation - old_c.rotation, 2),
                mirror_changed=mirror_changed,
            ))
        elif part_changed:
            changes.append(ComponentChange(
                comp_name=name, layer=layer, change_type=ChangeType.MODIFIED,
                part_name=new_c.part_name,
                old_part_name=old_c.part_name,
                old_x=old_c.x, old_y=old_c.y,
                old_rotation=old_c.rotation, old_mirror=old_c.mirror,
                new_x=new_c.x, new_y=new_c.y,
                new_rotation=new_c.rotation, new_mirror=new_c.mirror,
            ))

    return changes


# Sort priority: ADDED=0, REMOVED=1, RELOCATED=2, MODIFIED=3
_CHANGE_ORDER = {
    ChangeType.ADDED: 0,
    ChangeType.REMOVED: 1,
    ChangeType.RELOCATED: 2,
    ChangeType.MODIFIED: 3,
}

_COMP_COLUMNS = [
    "comp_name", "part_name", "Change",
    "Old X (mm)", "Old Y (mm)", "Old Rot (\u00b0)", "Old Mirror",
    "New X (mm)", "New Y (mm)", "New Rot (\u00b0)", "New Mirror",
    "\u0394X (mm)", "\u0394Y (mm)", "\u0394Rot (\u00b0)",
]


def _changes_to_rows(changes: list[ComponentChange]) -> list[dict]:
    """Convert ComponentChange list to row dicts for SheetConfig."""
    sorted_changes = sorted(
        changes,
        key=lambda c: (_CHANGE_ORDER.get(c.change_type, 99), c.comp_name),
    )
    rows: list[dict] = []
    for ch in sorted_changes:
        row: dict = {
            "comp_name": ch.comp_name,
            "part_name": ch.part_name,
            "Change": ch.change_type.value,
        }
        if ch.old_x is not None:
            row["Old X (mm)"] = round(ch.old_x, 4)
            row["Old Y (mm)"] = round(ch.old_y, 4)
            row["Old Rot (\u00b0)"] = round(ch.old_rotation, 2)
            row["Old Mirror"] = ch.old_mirror
        if ch.new_x is not None:
            row["New X (mm)"] = round(ch.new_x, 4)
            row["New Y (mm)"] = round(ch.new_y, 4)
            row["New Rot (\u00b0)"] = round(ch.new_rotation, 2)
            row["New Mirror"] = ch.new_mirror
        if ch.delta_x is not None:
            row["\u0394X (mm)"] = ch.delta_x
            row["\u0394Y (mm)"] = ch.delta_y
            row["\u0394Rot (\u00b0)"] = ch.delta_rotation

        # For MODIFIED, show old part_name in a note
        if ch.change_type == ChangeType.MODIFIED and ch.old_part_name:
            row["part_name"] = f"{ch.part_name} (was: {ch.old_part_name})"

        rows.append(row)
    return rows


def _count_by_type(changes: list[ComponentChange]) -> dict[str, int]:
    """Count changes by ChangeType."""
    counts: dict[str, int] = {ct.value: 0 for ct in ChangeType if ct != ChangeType.UNCHANGED}
    for ch in changes:
        if ch.change_type != ChangeType.UNCHANGED:
            counts[ch.change_type.value] = counts.get(ch.change_type.value, 0) + 1
    return counts


@register_comparator
class ComponentDiffComparator(ComparatorBase):
    """Compare component placement between two revisions."""

    comparator_id = "COMP-DIFF"
    title = "Component Changes"

    def compare(self, old_data: dict, new_data: dict) -> ComparisonResult:
        top_changes = _diff_layer(
            old_data.get("components_top", []),
            new_data.get("components_top", []),
            "Top",
        )
        bot_changes = _diff_layer(
            old_data.get("components_bot", []),
            new_data.get("components_bot", []),
            "Bottom",
        )

        top_counts = _count_by_type(top_changes)
        bot_counts = _count_by_type(bot_changes)

        total_changes = len(top_changes) + len(bot_changes)
        summary = (
            f"{total_changes} change(s): "
            f"Top({top_counts.get('ADDED', 0)}A/"
            f"{top_counts.get('REMOVED', 0)}R/"
            f"{top_counts.get('RELOCATED', 0)}L/"
            f"{top_counts.get('MODIFIED', 0)}M) "
            f"Bot({bot_counts.get('ADDED', 0)}A/"
            f"{bot_counts.get('REMOVED', 0)}R/"
            f"{bot_counts.get('RELOCATED', 0)}L/"
            f"{bot_counts.get('MODIFIED', 0)}M)"
        )

        sheets: list[SheetConfig] = []

        # Comp Top sheet
        sheets.append(SheetConfig(
            sheet_name="Comp Top",
            title="Component Changes \u2014 Top Layer",
            columns=list(_COMP_COLUMNS),
            rows=_changes_to_rows(top_changes),
            stats={
                "layer": "Top",
                **top_counts,
                "old_total": len(old_data.get("components_top", [])),
                "new_total": len(new_data.get("components_top", [])),
            },
        ))

        # Comp Bottom sheet
        sheets.append(SheetConfig(
            sheet_name="Comp Bottom",
            title="Component Changes \u2014 Bottom Layer",
            columns=list(_COMP_COLUMNS),
            rows=_changes_to_rows(bot_changes),
            stats={
                "layer": "Bottom",
                **bot_counts,
                "old_total": len(old_data.get("components_bot", [])),
                "new_total": len(new_data.get("components_bot", [])),
            },
        ))

        return ComparisonResult(
            comparator_id=self.comparator_id,
            title=self.title,
            summary=summary,
            sheet_configs=sheets,
        )
