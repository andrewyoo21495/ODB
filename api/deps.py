"""Shared dependencies and settings for the API.

Paths are anchored to the repository root (``api/`` parent) so the server works
regardless of the current working directory.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT / "workspace"
REFERENCES_DIR = REPO_ROOT / "references"


def get_current_user() -> str:
    """Return the current user identity.

    Deployment is initially **unauthenticated** (trusted intranet).  This is a
    ``Depends`` so it can be swapped for SSO-header trust or an API-key check
    later without touching the routers.
    """
    return "anonymous"
