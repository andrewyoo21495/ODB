"""Lightweight access / activity log for the hub.

Deployment is unauthenticated (trusted intranet), so there is no real identity.
To still answer "who connected from where", every API request is appended to
``workspace/access_log.jsonl`` with the self-declared user, client IP, method
and path.  An admin "사용자 현황" page reads ``recent`` + ``summary``.

Appends are cheap (one line per request); the full file is only read when the
activity endpoint is queried.  Log rotation is left as future work.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()
_LOG_FILE = "access_log.jsonl"


def _path(workspace_root: str | Path) -> Path:
    return Path(workspace_root) / _LOG_FILE


def record(workspace_root: str | Path, *, user: str, ip: str,
           method: str, path: str) -> None:
    """Append one access entry to the log (thread-safe)."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": user or "anonymous",
        "ip": ip or "",
        "method": method,
        "path": path,
    }
    p = _path(workspace_root)
    line = json.dumps(entry, ensure_ascii=False)
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def _read_all(workspace_root: str | Path) -> list[dict]:
    p = _path(workspace_root)
    if not p.exists():
        return []
    out: list[dict] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def recent(workspace_root: str | Path, limit: int = 200) -> list[dict]:
    """Most recent access entries, newest first."""
    entries = _read_all(workspace_root)
    return list(reversed(entries))[: max(0, limit)]


def summary(workspace_root: str | Path) -> list[dict]:
    """Per-user aggregate: request count, distinct IPs, last-seen time."""
    agg: dict[str, dict] = {}
    for e in _read_all(workspace_root):
        key = e.get("user") or "anonymous"
        a = agg.setdefault(key, {"user": key, "count": 0, "ips": set(), "last_seen": ""})
        a["count"] += 1
        if e.get("ip"):
            a["ips"].add(e["ip"])
        ts = e.get("ts", "")
        if ts > a["last_seen"]:
            a["last_seen"] = ts
    result = [
        {"user": a["user"], "count": a["count"],
         "ips": sorted(a["ips"]), "last_seen": a["last_seen"]}
        for a in agg.values()
    ]
    result.sort(key=lambda x: x["last_seen"], reverse=True)
    return result
