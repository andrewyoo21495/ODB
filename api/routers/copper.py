"""Copper endpoint: compute per-layer / per-subsection copper ratios."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.deps import WORKSPACE_ROOT, get_current_user
from api.schemas import CopperRequest, TaskOut
from api.tasks import registry
from src.services import copper_service, job_store

router = APIRouter(tags=["copper"])

_REPORT_NAME = "copper.html"


def _run_copper(job_id: str, method: str, n_rows: int, n_cols: int, task_id: str) -> None:
    registry.update(task_id, status="running", message="calculating copper ratios")
    try:
        cache_dir, cache_name = job_store.cache_args(job_id, workspace_root=WORKSPACE_ROOT)
        meta = job_store.get_meta(job_id, workspace_root=WORKSPACE_ROOT)
        rdir = job_store.reports_dir(job_id, workspace_root=WORKSPACE_ROOT)

        def on_progress(frac: float, msg: str) -> None:
            registry.update(task_id, progress=frac, message=msg)

        summary = copper_service.run_report(
            cache_dir, cache_name,
            html_path=rdir / _REPORT_NAME,
            images_dir=rdir / "images",
            odb_filename=meta.get("original_filename", job_id),
            n_rows=n_rows, n_cols=n_cols, method=method,
            log=lambda m: None,
            progress=on_progress,
        )
        job_store.record_result(job_id, "copper", report=summary.get("report"),
                                summary=summary,
                                params={"method": method, "n_rows": n_rows, "n_cols": n_cols},
                                workspace_root=WORKSPACE_ROOT)
        registry.update(task_id, status="done", progress=1.0, result=summary)
    except Exception as exc:  # noqa: BLE001
        registry.update(task_id, status="error", error=str(exc))


@router.post("/jobs/{job_id}/copper", response_model=TaskOut)
def run_copper(job_id: str, req: CopperRequest, background: BackgroundTasks,
               user: str = Depends(get_current_user)) -> TaskOut:
    if not job_store.is_cached(job_id, workspace_root=WORKSPACE_ROOT):
        raise HTTPException(status_code=404, detail="job not found or not ready")
    task = registry.create("copper", job_id=job_id)
    background.add_task(_run_copper, job_id, req.method, req.n_rows, req.n_cols, task.id)
    return TaskOut(task_id=task.id, kind=task.kind, job_id=task.job_id,
                   status=task.status, progress=task.progress)
