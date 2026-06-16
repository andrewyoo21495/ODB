"""Checklist endpoint: run the design-rule checklist for a job."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.deps import REFERENCES_DIR, WORKSPACE_ROOT, get_current_user
from api.schemas import ChecklistRequest, TaskOut
from api.tasks import registry
from src.services import checklist_service, job_store

router = APIRouter(tags=["checklist"])

_REPORT_NAME = "checklist.html"


def _run_checklist(job_id: str, rule_ids: list[str] | None, task_id: str) -> None:
    registry.update(task_id, status="running", message="running rules")
    try:
        data = job_store.load_job_data(job_id, workspace_root=WORKSPACE_ROOT,
                                       log=lambda m: None)

        # Rules occupy 0–90% of the bar; report writing the final 10%.
        def on_progress(frac: float, msg: str) -> None:
            registry.update(task_id, progress=round(frac * 0.9, 3), message=msg)

        results = checklist_service.evaluate(data, rule_ids, progress=on_progress)

        registry.update(task_id, progress=0.9, message="generating report")
        meta = job_store.get_meta(job_id, workspace_root=WORKSPACE_ROOT)
        job_info = data.get("job_info")
        html_path = job_store.reports_dir(job_id, workspace_root=WORKSPACE_ROOT) / _REPORT_NAME
        checklist_service.write_report(
            results,
            html_path=html_path,
            odb_filename=meta.get("original_filename", job_id),
            job_name=job_info.job_name if job_info else job_id,
            components_top=data.get("components_top", []),
            components_bot=data.get("components_bot", []),
            references_dir=REFERENCES_DIR,
        )

        passed = sum(1 for r in results if r.passed)
        summary = {
            "passed": passed,
            "failed": len(results) - passed,
            "total": len(results),
            "report": _REPORT_NAME,
        }
        job_store.record_result(job_id, "checklist", report=_REPORT_NAME,
                                summary=summary, params={"rule_ids": rule_ids},
                                workspace_root=WORKSPACE_ROOT)
        registry.update(task_id, status="done", progress=1.0, result=summary)
    except Exception as exc:  # noqa: BLE001
        registry.update(task_id, status="error", error=str(exc))


@router.post("/jobs/{job_id}/checklist", response_model=TaskOut)
def run_checklist(job_id: str, req: ChecklistRequest, background: BackgroundTasks,
                  user: str = Depends(get_current_user)) -> TaskOut:
    if not job_store.is_cached(job_id, workspace_root=WORKSPACE_ROOT):
        raise HTTPException(status_code=404, detail="job not found or not ready")
    task = registry.create("checklist", job_id=job_id)
    background.add_task(_run_checklist, job_id, req.rule_ids, task.id)
    return TaskOut(task_id=task.id, kind=task.kind, job_id=task.job_id,
                   status=task.status, progress=task.progress)
