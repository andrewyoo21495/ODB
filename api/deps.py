"""Shared dependencies and settings for the API.

Paths are anchored to the repository root (``api/`` parent) so the server works
regardless of the current working directory.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import Header

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT / "workspace"
REFERENCES_DIR = REPO_ROOT / "references"

_USER_RE = re.compile(r"[^0-9A-Za-z가-힣 _.\-]")


def sanitize_user(raw: str | None) -> str:
    """Sanitise a self-declared user name; blank/invalid -> ``anonymous``."""
    name = (raw or "").strip()
    if not name:
        return "anonymous"
    return _USER_RE.sub("", name)[:40] or "anonymous"


def get_current_user(x_user: str | None = Header(default=None)) -> str:
    """Return the current user identity from the ``X-User`` request header.

    Deployment is **unauthenticated** (trusted intranet): the frontend sends a
    self-declared display name in ``X-User`` (no password).  This is enough for
    A2-level ownership tagging / "my jobs" filtering.  Swap for SSO-header trust
    or an API-key check later without touching the routers.  The value is
    sanitised and length-capped; missing/blank falls back to ``anonymous``.
    """
    return sanitize_user(x_user)
