"""Compare endpoint: diff two revisions and produce an HTML report."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.deps import WORKSPACE_ROOT, get_current_user
from api.schemas import CompareRequest, TaskOut
from api.tasks import registry
from src.services import compare_service, job_store

router = APIRouter(tags=["compare"])


def _run_compare(old_id: str, new_id: str, task_id: str) -> None:
    registry.update(task_id, status="running", message="comparing revisions")
    try:
        old_data = job_store.load_job_data(old_id, workspace_root=WORKSPACE_ROOT, log=lambda m: None)
        new_data = job_store.load_job_data(new_id, workspace_root=WORKSPACE_ROOT, log=lambda m: None)
        results = compare_service.compare(old_data, new_data)

        old_meta = job_store.get_meta(old_id, workspace_root=WORKSPACE_ROOT)
        new_meta = job_store.get_meta(new_id, workspace_root=WORKSPACE_ROOT)
        # Store the report under the NEW job's reports dir.
        report_name = f"compare_{old_id}.html"
        html_path = job_store.reports_dir(new_id, workspace_root=WORKSPACE_ROOT) / report_name
        compare_service.write_html_report(
            results, html_path,
            old_job_name=old_meta.get("original_filename", old_id),
            new_job_name=new_meta.get("original_filename", new_id),
        )
        registry.update(task_id, status="done", progress=1.0, result={
            "report": report_name,
            "summaries": [{"comparator_id": r.comparator_id, "title": r.title,
                           "summary": r.summary} for r in results],
        })
    except Exception as exc:  # noqa: BLE001
        registry.update(task_id, status="error", error=str(exc))


@router.post("/compare", response_model=TaskOut)
def run_compare(req: CompareRequest, background: BackgroundTasks,
                user: str = Depends(get_current_user)) -> TaskOut:
    for jid in (req.old_job_id, req.new_job_id):
        if not job_store.is_cached(jid, workspace_root=WORKSPACE_ROOT):
            raise HTTPException(status_code=404, detail=f"job not found or not ready: {jid}")
    # The report lives under the new job; report retrieval uses task.job_id.
    task = registry.create("compare", job_id=req.new_job_id)
    background.add_task(_run_compare, req.old_job_id, req.new_job_id, task.id)
    return TaskOut(task_id=task.id, kind=task.kind, job_id=task.job_id,
                   status=task.status, progress=task.progress)
