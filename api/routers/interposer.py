"""Interposer endpoint: per-side interposer-area / PCB-area ratio."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.deps import WORKSPACE_ROOT, get_current_user
from api.schemas import TaskOut
from api.tasks import registry
from src.services import interposer_service, job_store

router = APIRouter(tags=["interposer"])


def _run_interposer(job_id: str, task_id: str) -> None:
    registry.update(task_id, status="running", message="analyzing interposers")
    try:
        cache_dir, cache_name = job_store.cache_args(job_id, workspace_root=WORKSPACE_ROOT)
        meta = job_store.get_meta(job_id, workspace_root=WORKSPACE_ROOT)
        rdir = job_store.reports_dir(job_id, workspace_root=WORKSPACE_ROOT)
        summary = interposer_service.run_interposer(
            cache_dir, cache_name,
            out_dir=rdir,
            odb_filename=meta.get("original_filename", job_id),
            log=lambda m: None,
        )
        job_store.record_result(job_id, "interposer", report=summary.get("report"),
                                summary=summary, workspace_root=WORKSPACE_ROOT)
        registry.update(task_id, status="done", progress=1.0, result=summary)
    except Exception as exc:  # noqa: BLE001
        registry.update(task_id, status="error", error=str(exc))


@router.post("/jobs/{job_id}/interposer", response_model=TaskOut)
def run_interposer(job_id: str, background: BackgroundTasks,
                   user: str = Depends(get_current_user)) -> TaskOut:
    if not job_store.is_cached(job_id, workspace_root=WORKSPACE_ROOT):
        raise HTTPException(status_code=404, detail="job not found or not ready")
    task = registry.create("interposer", job_id=job_id)
    background.add_task(_run_interposer, job_id, task.id)
    return TaskOut(task_id=task.id, kind=task.kind, job_id=task.job_id,
                   status=task.status, progress=task.progress)
