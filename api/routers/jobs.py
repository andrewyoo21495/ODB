"""Job endpoints: upload, list, metadata, and cache-build status."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile

from api.deps import WORKSPACE_ROOT, get_current_user
from api.schemas import JobOut, JobStatus
from api.tasks import registry
from src.services import job_store

router = APIRouter(tags=["jobs"])


def _build_job(temp_path: str, original_filename: str, task_id: str) -> None:
    """Background worker: ingest the uploaded archive into the workspace."""
    registry.update(task_id, status="running", message="parsing & caching")
    try:
        job_id = job_store.create_job(
            temp_path, original_filename=original_filename,
            workspace_root=WORKSPACE_ROOT, log=lambda m: None,
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
                             workspace_root=WORKSPACE_ROOT, log=lambda m: None)
        Path(tmp.name).unlink(missing_ok=True)
        return JobStatus(job_id=job_id, status="ready", progress=1.0)

    task = registry.create("cache", job_id=job_id)
    background.add_task(_build_job, tmp.name, file.filename or "", task.id)
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
