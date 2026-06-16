"""Job endpoints: upload, list, metadata, and cache-build status."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from api.deps import WORKSPACE_ROOT, get_current_user
from api.schemas import (
    ActiveJob, JobMetaUpdate, JobOut, JobStatus, MetaOptions, ResultOut, TaskOut,
)
from api.tasks import registry
from src.services import job_store

router = APIRouter(tags=["jobs"])


def _build_job(temp_path: str, original_filename: str, task_id: str,
               uploaded_by: str, meta_fields: dict) -> None:
    """Background worker: ingest the uploaded archive into the workspace."""
    registry.update(task_id, status="running", message="parsing & caching")
    try:
        def on_progress(frac: float, msg: str) -> None:
            registry.update(task_id, progress=frac, message=msg)

        job_id = job_store.create_job(
            temp_path, original_filename=original_filename,
            uploaded_by=uploaded_by, meta_fields=meta_fields,
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
                     project: str = Form(""), board_type: str = Form(""),
                     revision: str = Form(""),
                     user: str = Depends(get_current_user)) -> JobStatus:
    """Upload an ODB++ ``.tgz``; build its cache in the background.

    The response carries the content-addressed ``job_id`` immediately.  If the
    same content was uploaded before, it is reused (status ``ready``).  The
    optional ``project``/``board_type``/``revision`` form fields are user-entered
    metadata (과제/타입/리비전); blank values never overwrite existing ones.
    """
    meta_fields = {"project": project, "board_type": board_type, "revision": revision}

    suffix = Path(file.filename or "upload.tgz").suffix or ".tgz"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(await file.read())
    finally:
        tmp.close()

    job_id = job_store.compute_job_id(tmp.name)

    if job_store.is_cached(job_id, workspace_root=WORKSPACE_ROOT):
        # Already ingested — ensure source/meta exist, refresh metadata, drop temp.
        job_store.create_job(tmp.name, original_filename=file.filename or "",
                             uploaded_by=user, meta_fields=meta_fields,
                             workspace_root=WORKSPACE_ROOT, log=lambda m: None)
        Path(tmp.name).unlink(missing_ok=True)
        return JobStatus(job_id=job_id, status="ready", progress=1.0)

    task = registry.create("cache", job_id=job_id, info={
        "original_filename": file.filename or "",
        "project": project, "board_type": board_type, "revision": revision,
        "uploaded_by": user,
    })
    background.add_task(_build_job, tmp.name, file.filename or "", task.id, user,
                        meta_fields)
    return JobStatus(job_id=job_id, status="caching", message="build started")


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(user: str = Depends(get_current_user)) -> list[JobOut]:
    return [JobOut(**m) for m in job_store.list_jobs(workspace_root=WORKSPACE_ROOT)]


@router.get("/jobs/active", response_model=list[ActiveJob])
def active_jobs(user: str = Depends(get_current_user)) -> list[ActiveJob]:
    """Uploads whose cache is still building (server-side, survives navigation)."""
    out: list[ActiveJob] = []
    for t in registry.active("cache"):
        info = t.info or {}
        out.append(ActiveJob(
            job_id=t.job_id or "",
            original_filename=info.get("original_filename", ""),
            project=info.get("project", ""),
            board_type=info.get("board_type", ""),
            revision=info.get("revision", ""),
            uploaded_by=info.get("uploaded_by", ""),
            progress=t.progress,
            message=t.message,
        ))
    return out


@router.get("/jobs/meta/options", response_model=MetaOptions)
def meta_options(user: str = Depends(get_current_user)) -> MetaOptions:
    """Previously-used values for 과제/타입/리비전 (input-history autocomplete)."""
    return MetaOptions(**job_store.meta_options(workspace_root=WORKSPACE_ROOT))


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, user: str = Depends(get_current_user)) -> JobOut:
    try:
        meta = job_store.get_meta(job_id, workspace_root=WORKSPACE_ROOT)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="job not found")
    return JobOut(**meta)


@router.patch("/jobs/{job_id}/meta", response_model=JobOut)
def update_job_meta(job_id: str, body: JobMetaUpdate,
                    user: str = Depends(get_current_user)) -> JobOut:
    """Update a job's user-entered metadata (과제/타입/리비전)."""
    fields = body.model_dump(exclude_none=True)
    try:
        meta = job_store.update_meta(job_id, fields, workspace_root=WORKSPACE_ROOT)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="job not found")
    return JobOut(**meta)


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, user: str = Depends(get_current_user)) -> dict:
    """Delete a job and all its data (source, cache, reports)."""
    removed = job_store.delete_job(job_id, workspace_root=WORKSPACE_ROOT)
    if not removed:
        raise HTTPException(status_code=404, detail="job not found")
    return {"deleted": job_id}


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
    task = registry.latest_for_job(job_id, "cache")
    # A running build takes priority over is_cached: cache_job writes the JSON
    # files (and meta.json) near the end, so is_cached flips to True before the
    # build is fully done.  Reporting "ready" then would drop the progress bar
    # while list_jobs still excludes the (meta-less) job — looks like a failure.
    if task is not None:
        if task.status == "error":
            return JobStatus(job_id=job_id, status="error", error=task.error)
        if task.status != "done":
            return JobStatus(job_id=job_id, status="caching",
                             progress=task.progress, message=task.message)

    if job_store.is_cached(job_id, workspace_root=WORKSPACE_ROOT):
        return JobStatus(job_id=job_id, status="ready", progress=1.0)

    if task is None:
        raise HTTPException(status_code=404, detail="job not found")
    # Task finished but cache not present yet (unexpected) — keep waiting.
    return JobStatus(job_id=job_id, status="caching",
                     progress=task.progress, message=task.message)
