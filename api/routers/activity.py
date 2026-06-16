"""Activity / access log endpoint for the "사용자 현황" admin page."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api import activity
from api.deps import WORKSPACE_ROOT, get_current_user
from api.schemas import ActivityOut

router = APIRouter(tags=["activity"])


@router.get("/activity", response_model=ActivityOut)
def get_activity(limit: int = 200,
                 user: str = Depends(get_current_user)) -> ActivityOut:
    """Recent access entries + per-user summary (who connected, from where)."""
    return ActivityOut(
        recent=activity.recent(WORKSPACE_ROOT, limit),
        users=activity.summary(WORKSPACE_ROOT),
    )
