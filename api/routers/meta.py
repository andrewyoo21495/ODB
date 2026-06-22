"""Metadata endpoints: rule catalog and reference docs for the checklist UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from api.deps import REFERENCES_DIR, get_current_user
from api.schemas import RuleInfo

router = APIRouter(tags=["meta"])

# The 검토기준 document is served straight from this fixed path: updating the
# file (references/ is gitignored, deployed/updated out-of-band) is reflected
# immediately on the next request — FileResponse re-reads the file each time.
_CHECKLIST_REFERENCE = REFERENCES_DIR / "checklist_reference.html"


@router.get("/rules", response_model=list[RuleInfo])
def list_rules(user: str = Depends(get_current_user)) -> list[RuleInfo]:
    """Catalog of available checklist rules (auto-discovered)."""
    from src.checklist.engine import discover_rules
    return [
        RuleInfo(rule_id=r.rule_id, description=r.description, category=r.category)
        for r in discover_rules()
    ]


@router.get("/docs/checklist", include_in_schema=True)
def checklist_doc() -> FileResponse:
    """Serve the checklist 검토기준 documentation HTML for inline viewing.

    Opened in a new browser tab by the "검토기준" button on the checklist page.
    Served inline (not as a download) so the browser renders it.
    """
    if _CHECKLIST_REFERENCE.is_file():
        return FileResponse(
            _CHECKLIST_REFERENCE,
            media_type="text/html",
            content_disposition_type="inline",
        )
    raise HTTPException(status_code=404, detail="검토기준 문서가 아직 준비되지 않았습니다.")
