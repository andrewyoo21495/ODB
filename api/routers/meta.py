"""Metadata endpoints: rule catalog for the checklist UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_current_user
from api.schemas import RuleInfo

router = APIRouter(tags=["meta"])


@router.get("/rules", response_model=list[RuleInfo])
def list_rules(user: str = Depends(get_current_user)) -> list[RuleInfo]:
    """Catalog of available checklist rules (auto-discovered)."""
    from src.checklist.engine import discover_rules
    return [
        RuleInfo(rule_id=r.rule_id, description=r.description, category=r.category)
        for r in discover_rules()
    ]
