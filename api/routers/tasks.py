"""Task endpoints: poll status and download the produced report."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from api.deps import WORKSPACE_ROOT, get_current_user
from api.schemas import TaskOut
from api.tasks import registry
from src.services import job_store

router = APIRouter(tags=["tasks"])


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: str, user: str = Depends(get_current_user)) -> TaskOut:
    task = registry.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskOut(task_id=task.id, kind=task.kind, job_id=task.job_id,
                   status=task.status, progress=task.progress,
                   message=task.message, result=task.result, error=task.error)


@router.get("/tasks/{task_id}/report")
def get_task_report(task_id: str, user: str = Depends(get_current_user)):
    task = registry.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    if task.status != "done":
        raise HTTPException(status_code=409, detail=f"task not done (status={task.status})")
    report_name = task.result.get("report")
    if not report_name or not task.job_id:
        raise HTTPException(status_code=404, detail="no report for this task")
    path = job_store.reports_dir(task.job_id, workspace_root=WORKSPACE_ROOT) / report_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="report file missing")
    # Serve inline (no `filename=`) so the browser renders the HTML in the iframe
    # / new tab instead of downloading it as an attachment.
    return FileResponse(path, media_type="text/html",
                        content_disposition_type="inline")


@router.get("/tasks/{task_id}/artifact/{name}")
def get_task_artifact(task_id: str, name: str, user: str = Depends(get_current_user)):
    """Download a named artifact file (e.g. parts.json) from the task's reports dir."""
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="invalid artifact name")
    task = registry.get(task_id)
    if task is None or not task.job_id:
        raise HTTPException(status_code=404, detail="task not found")
    path = job_store.reports_dir(task.job_id, workspace_root=WORKSPACE_ROOT) / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path, filename=name)
