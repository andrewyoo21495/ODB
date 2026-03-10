"""Reference CSV file loader with sample-data fallback.

Provides a central function to load managed component lists from
``references/*.csv``.  When a required CSV file is missing the loader
automatically generates a small sample file so that the checklist
pipeline can still be tested end-to-end.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Optional

# Base directory for reference CSV files (project root / references)
_REFERENCES_DIR = Path(__file__).resolve().parent.parent.parent / "references"

# ---------------------------------------------------------------------------
# Sample data – used when a CSV file does not exist yet
# ---------------------------------------------------------------------------

_SAMPLE_DATA: dict[str, list[dict[str, str]]] = {
    "capacitors_10_list": [
        {"part_name": "2203-105681", "size": "1024"},
        {"part_name": "2203-105311", "size": "135"},
        {"part_name": "2203-744610", "size": "2640"},
        {"part_name": "2203-315645", "size": "2080"},
        {"part_name": "2203-135781", "size": "2012"},
        {"part_name": "2203-108466", "size": "5648"},
        {"part_name": "2203-123154", "size": "1320"},
        {"part_name": "2203-441354", "size": "4268"},
        {"part_name": "2203-764646", "size": "3030"},
        {"part_name": "2203-132009", "size": "5648"},
    ],
    "capacitors_41_list": [
        {"part_name": "2203-313639", "size": "3640"},
        {"part_name": "2203-946989", "size": "8880"},
        {"part_name": "2203-203060", "size": "5648"},
        {"part_name": "2203-798464", "size": "1320"},
        {"part_name": "2203-008689", "size": "4268"},
        {"part_name": "2203-008572", "size": "3030"},
        {"part_name": "2203-009099", "size": "5648"},
        {"part_name": "2203-010223", "size": "3640"},
        {"part_name": "2203-010284", "size": "8880"},
        {"part_name": "2203-010113", "size": "9980"},
        {"part_name": "2203-033213", "size": "103180"},
        {"part_name": "2203-500001", "size": "2012"},
        {"part_name": "2203-500002", "size": "1608"},
        {"part_name": "2203-500003", "size": "1005"},
        {"part_name": "2203-500004", "size": "3216"},
        {"part_name": "2203-500005", "size": "2012"},
        {"part_name": "2203-500006", "size": "1608"},
        {"part_name": "2203-500007", "size": "1005"},
        {"part_name": "2203-500008", "size": "3216"},
        {"part_name": "2203-500009", "size": "4532"},
        {"part_name": "2203-500010", "size": "5750"},
        {"part_name": "2203-500011", "size": "2012"},
        {"part_name": "2203-500012", "size": "1608"},
        {"part_name": "2203-500013", "size": "1005"},
        {"part_name": "2203-500014", "size": "3216"},
        {"part_name": "2203-500015", "size": "2012"},
        {"part_name": "2203-500016", "size": "1608"},
        {"part_name": "2203-500017", "size": "1005"},
        {"part_name": "2203-500018", "size": "3216"},
        {"part_name": "2203-500019", "size": "4532"},
        {"part_name": "2203-500020", "size": "5750"},
        {"part_name": "2203-500021", "size": "2012"},
        {"part_name": "2203-500022", "size": "1608"},
        {"part_name": "2203-500023", "size": "1005"},
        {"part_name": "2203-500024", "size": "3216"},
        {"part_name": "2203-500025", "size": "2012"},
        {"part_name": "2203-500026", "size": "1608"},
        {"part_name": "2203-500027", "size": "1005"},
        {"part_name": "2203-500028", "size": "3216"},
        {"part_name": "2203-500029", "size": "4532"},
        {"part_name": "2203-500030", "size": "5750"},
        {"part_name": "2203-500031", "size": "2012"},
    ],
    "inductors_2s_list": [
        {"part_name": "2703-013543", "size": "10321"},
        {"part_name": "2703-132135", "size": "4242"},
        {"part_name": "2703-135434", "size": "2034"},
        {"part_name": "2703-975166", "size": "2024"},
        {"part_name": "2703-213546", "size": "2354"},
    ],
    "ap_memory": [
        {"part_name": "1105-003546", "rank": "A", "category": "DRAM"},
        {"part_name": "1105-946565", "rank": "A", "category": "MCP"},
        {"part_name": "1105-481351", "rank": "A", "category": "AP"},
        {"part_name": "1105-798778", "rank": "A", "category": "CP"},
        {"part_name": "1105-461323", "rank": "B", "category": "AP"},
    ],
}


def _generate_sample_csv(csv_path: Path, file_key: str) -> None:
    """Write a sample CSV file from the built-in sample data."""
    rows = _SAMPLE_DATA.get(file_key)
    if not rows:
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  [reference_loader] Generated sample CSV: {csv_path}")


def load_reference_csv(filename: str,
                       references_dir: Optional[str | Path] = None,
                       ) -> list[dict[str, str]]:
    """Load a reference CSV file, generating a sample if missing.

    Args:
        filename: CSV filename (e.g. ``"capacitors_10_list.csv"``).
                  The ``.csv`` extension is optional.
        references_dir: Override for the references directory.

    Returns:
        List of dicts, one per CSV row.
    """
    if not filename.endswith(".csv"):
        filename += ".csv"
    base_dir = Path(references_dir) if references_dir else _REFERENCES_DIR
    csv_path = base_dir / filename

    file_key = Path(filename).stem  # e.g. "capacitors_10_list"

    if not csv_path.exists():
        if file_key in _SAMPLE_DATA:
            _generate_sample_csv(csv_path, file_key)
        else:
            print(f"  [reference_loader] Warning: {csv_path} not found and "
                  f"no sample data available for '{file_key}'.")
            return []

    entries: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append({k: (v or "").strip() for k, v in row.items()})
    return entries


def get_managed_part_names(filename: str,
                           references_dir: Optional[str | Path] = None,
                           ) -> set[str]:
    """Return the set of ``part_name`` values from a reference CSV."""
    rows = load_reference_csv(filename, references_dir)
    return {r["part_name"] for r in rows if r.get("part_name")}


def get_part_category_map(filename: str,
                          references_dir: Optional[str | Path] = None,
                          ) -> dict[str, str]:
    """Return a mapping ``part_name -> category`` from a reference CSV."""
    rows = load_reference_csv(filename, references_dir)
    result: dict[str, str] = {}
    for r in rows:
        pn = r.get("part_name", "")
        cat = r.get("category", "")
        if pn and cat:
            result[pn] = cat
    return result


def get_part_size_map(filename: str,
                      references_dir: Optional[str | Path] = None,
                      ) -> dict[str, int]:
    """Return a mapping ``part_name -> size`` (as int) from a reference CSV."""
    rows = load_reference_csv(filename, references_dir)
    result: dict[str, int] = {}
    for r in rows:
        pn = r.get("part_name", "")
        sz = r.get("size", "")
        if pn and sz.isdigit():
            result[pn] = int(sz)
    return result
