"""Job endpoints: upload, list, metadata, and cache-build status."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse

from api.deps import WORKSPACE_ROOT, get_current_user
from api.schemas import JobOut, JobStatus, ResultOut, TaskOut
from api.tasks import registry
from src.services import job_store

router = APIRouter(tags=["jobs"])


def _build_job(temp_path: str, original_filename: str, task_id: str,
               uploaded_by: str) -> None:
    """Background worker: ingest the uploaded archive into the workspace."""
    registry.update(task_id, status="running", message="parsing & caching")
    try:
        def on_progress(frac: float, msg: str) -> None:
            registry.update(task_id, progress=frac, message=msg)

        job_id = job_store.create_job(
            temp_path, original_filename=original_filename,
            uploaded_by=uploaded_by,
            workspace_root=WORKSPACE_ROOT, log=lambda m: None,
            progress=on_progress,
        )
        registry.update(task_id, status="done", progress=1.0,
                        job_id=job_id, result={"job_id": job_id})
    except Exception as exc:  # noqa: BLE001 - surface any parse failure to the client
        registry.update(task_id, status="error", error=str(exc))
    finally:
        Path(temp_path).unlink(missing_ok=True)


@router.post("/jobs", response_model=JobStatus)
async def upload_job(file: UploadFile, background: BackgroundTasks,
                     user: str = Depends(get_current_user)) -> JobStatus:
    """Upload an ODB++ ``.tgz``; build its cache in the background.

    The response carries the content-addressed ``job_id`` immediately.  If the
    same content was uploaded before, it is reused (status ``ready``).
    """
    suffix = Path(file.filename or "upload.tgz").suffix or ".tgz"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(await file.read())
    finally:
        tmp.close()

    job_id = job_store.compute_job_id(tmp.name)

    if job_store.is_cached(job_id, workspace_root=WORKSPACE_ROOT):
        # Already ingested — ensure source/meta exist, then drop the temp file.
        job_store.create_job(tmp.name, original_filename=file.filename or "",
                             uploaded_by=user,
                             workspace_root=WORKSPACE_ROOT, log=lambda m: None)
        Path(tmp.name).unlink(missing_ok=True)
        return JobStatus(job_id=job_id, status="ready", progress=1.0)

    task = registry.create("cache", job_id=job_id)
    background.add_task(_build_job, tmp.name, file.filename or "", task.id, user)
    return JobStatus(job_id=job_id, status="caching", message="build started")


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(user: str = Depends(get_current_user)) -> list[JobOut]:
    return [JobOut(**m) for m in job_store.list_jobs(workspace_root=WORKSPACE_ROOT)]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, user: str = Depends(get_current_user)) -> JobOut:
    try:
        meta = job_store.get_meta(job_id, workspace_root=WORKSPACE_ROOT)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="job not found")
    return JobOut(**meta)


@router.get("/jobs/{job_id}/results", response_model=list[ResultOut])
def job_results(job_id: str, user: str = Depends(get_current_user)) -> list[ResultOut]:
    """Completed analyses recorded for this job (checklist/copper/extract/…).

    Lets a feature page show a prior run instead of a blank screen, and the
    dashboard list which analyses are done — independent of the in-memory task
    registry, so it survives navigation and server restarts."""
    return [ResultOut(**r) for r in job_store.list_results(job_id, workspace_root=WORKSPACE_ROOT)]


@router.get("/jobs/{job_id}/report/{kind}")
def job_report(job_id: str, kind: str, download: bool = False,
               user: str = Depends(get_current_user)):
    """Serve a job's recorded report for a feature *kind* (task-independent)."""
    result = job_store.get_result(job_id, kind, workspace_root=WORKSPACE_ROOT)
    if not result or not result.get("report"):
        raise HTTPException(status_code=404, detail="no report for this kind")
    name = result["report"]
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="invalid report name")
    path = job_store.reports_dir(job_id, workspace_root=WORKSPACE_ROOT) / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="report file missing")
    if download:
        return FileResponse(path, media_type="text/html",
                            content_disposition_type="attachment",
                            filename=f"{kind}_{job_id}.html")
    return FileResponse(path, media_type="text/html",
                        content_disposition_type="inline")


@router.get("/jobs/{job_id}/artifact/{name}")
def job_artifact(job_id: str, name: str, user: str = Depends(get_current_user)):
    """Download a named artifact (e.g. parts.json) from a job's reports dir."""
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="invalid artifact name")
    path = job_store.reports_dir(job_id, workspace_root=WORKSPACE_ROOT) / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path, filename=name)


@router.get("/jobs/{job_id}/tasks/{kind}", response_model=TaskOut | None)
def latest_task(job_id: str, kind: str, user: str = Depends(get_current_user)):
    """Most recent in-memory task of *kind* for this job (to re-attach a page to
    a still-running analysis after navigating away). ``null`` if none."""
    task = registry.latest_for_job(job_id, kind)
    if task is None:
        return None
    return TaskOut(task_id=task.id, kind=task.kind, job_id=task.job_id,
                   status=task.status, progress=task.progress,
                   message=task.message, result=task.result, error=task.error)


@router.get("/jobs/{job_id}/status", response_model=JobStatus)
def job_status(job_id: str, user: str = Depends(get_current_user)) -> JobStatus:
    if job_store.is_cached(job_id, workspace_root=WORKSPACE_ROOT):
        return JobStatus(job_id=job_id, status="ready", progress=1.0)

    task = registry.latest_for_job(job_id, "cache")
    if task is None:
        raise HTTPException(status_code=404, detail="job not found")
    if task.status == "error":
        return JobStatus(job_id=job_id, status="error", error=task.error)
    return JobStatus(job_id=job_id, status="caching",
                     progress=task.progress, message=task.message)
