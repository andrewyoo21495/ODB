"""Parser for misc/info and misc/attrlist files."""

from __future__ import annotations

from pathlib import Path

from src.models import JobInfo
from src.parsers.base_parser import parse_key_value, read_file


def parse_info(path: Path) -> JobInfo:
    """Parse the misc/info file."""
    lines = read_file(path)
    kv = parse_key_value(lines)

    return JobInfo(
        job_name=kv.get("JOB_NAME", ""),
        odb_version_major=int(kv.get("ODB_VERSION_MAJOR", 0)),
        odb_version_minor=int(kv.get("ODB_VERSION_MINOR", 0)),
        odb_source=kv.get("ODB_SOURCE", ""),
        creation_date=kv.get("CREATION_DATE", ""),
        save_date=kv.get("SAVE_DATE", ""),
        save_app=kv.get("SAVE_APP", ""),
        save_user=kv.get("SAVE_USER", ""),
        units=kv.get("UNITS", "INCH"),
        max_uid=int(kv.get("MAX_UID", 0)),
    )


def parse_attrlist(path: Path) -> dict[str, str]:
    """Parse an attrlist file (simple key=value pairs)."""
    lines = read_file(path)
    return parse_key_value(lines)
