"""Metadata endpoints: rule catalog and reference docs for the checklist UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from api.deps import REPO_ROOT, get_current_user
from api.schemas import RuleInfo

router = APIRouter(tags=["meta"])

_DOCS_DIR = REPO_ROOT / "documents"
# Preferred reference doc (the image-rich 검토기준 converted from Excel); falls
# back to the hand-written doc so the "검토기준" button works before the real
# file is dropped in.
_CHECKLIST_DOC_CANDIDATES = (
    "checklist_reference.html",
    "checklist_documentation.html",
)


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
    for name in _CHECKLIST_DOC_CANDIDATES:
        path = _DOCS_DIR / name
        if path.is_file():
            return FileResponse(path, media_type="text/html", content_disposition_type="inline")
    raise HTTPException(status_code=404, detail="검토기준 문서가 아직 준비되지 않았습니다.")
