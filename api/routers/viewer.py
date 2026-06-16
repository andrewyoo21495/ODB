"""Viewer endpoints: list layers and build layer geometry for the canvas."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.deps import WORKSPACE_ROOT, get_current_user
from api.schemas import (
    ComponentViewerRequest, LayerInfo, NetViewerRequest, TaskOut, ViewerRequest,
)
from api.tasks import registry
from src.services import job_store, viewer_service

router = APIRouter(tags=["viewer"])


@router.get("/jobs/{job_id}/layers", response_model=list[LayerInfo])
def list_layers(job_id: str, user: str = Depends(get_current_user)) -> list[LayerInfo]:
    if not job_store.is_cached(job_id, workspace_root=WORKSPACE_ROOT):
        raise HTTPException(status_code=404, detail="job not found or not ready")
    cache_dir, cache_name = job_store.cache_args(job_id, workspace_root=WORKSPACE_ROOT)
    return [LayerInfo(**l) for l in viewer_service.list_layers(cache_dir, cache_name)]


@router.get("/jobs/{job_id}/nets", response_model=list[str])
def list_nets(job_id: str, layer: str, user: str = Depends(get_current_user)) -> list[str]:
    if not job_store.is_cached(job_id, workspace_root=WORKSPACE_ROOT):
        raise HTTPException(status_code=404, detail="job not found or not ready")
    cache_dir, cache_name = job_store.cache_args(job_id, workspace_root=WORKSPACE_ROOT)
    return viewer_service.list_nets(cache_dir, cache_name, layer)


def _run_viewer(job_id: str, layer: str, task_id: str) -> None:
    registry.update(task_id, status="running", message=f"building geometry: {layer}")
    try:
        cache_dir, cache_name = job_store.cache_args(job_id, workspace_root=WORKSPACE_ROOT)
        rdir = job_store.reports_dir(job_id, workspace_root=WORKSPACE_ROOT)
        out_path = rdir / f"geom_{viewer_service.safe_name(layer)}.json"
        summary = viewer_service.build_layer_geometry(
            cache_dir, cache_name, layer, out_path, log=lambda m: None,
        )
        registry.update(task_id, status="done", progress=1.0, result=summary)
    except Exception as exc:  # noqa: BLE001
        registry.update(task_id, status="error", error=str(exc))


@router.post("/jobs/{job_id}/viewer", response_model=TaskOut)
def run_viewer(job_id: str, req: ViewerRequest, background: BackgroundTasks,
               user: str = Depends(get_current_user)) -> TaskOut:
    if not job_store.is_cached(job_id, workspace_root=WORKSPACE_ROOT):
        raise HTTPException(status_code=404, detail="job not found or not ready")
    task = registry.create("viewer", job_id=job_id)
    background.add_task(_run_viewer, job_id, req.layer, task.id)
    return TaskOut(task_id=task.id, kind=task.kind, job_id=task.job_id,
                   status=task.status, progress=task.progress)


def _run_net_viewer(job_id: str, layer: str, net: str, task_id: str) -> None:
    registry.update(task_id, status="running", message=f"net geometry: {net}")
    try:
        cache_dir, cache_name = job_store.cache_args(job_id, workspace_root=WORKSPACE_ROOT)
        rdir = job_store.reports_dir(job_id, workspace_root=WORKSPACE_ROOT)
        out_path = rdir / f"geomnet_{viewer_service.safe_name(layer)}_{viewer_service.safe_name(net)}.json"
        summary = viewer_service.build_net_geometry(
            cache_dir, cache_name, layer, net, out_path, log=lambda m: None)
        registry.update(task_id, status="done", progress=1.0, result=summary)
    except Exception as exc:  # noqa: BLE001
        registry.update(task_id, status="error", error=str(exc))


@router.post("/jobs/{job_id}/viewer/net", response_model=TaskOut)
def run_net_viewer(job_id: str, req: NetViewerRequest, background: BackgroundTasks,
                   user: str = Depends(get_current_user)) -> TaskOut:
    if not job_store.is_cached(job_id, workspace_root=WORKSPACE_ROOT):
        raise HTTPException(status_code=404, detail="job not found or not ready")
    task = registry.create("viewer", job_id=job_id)
    background.add_task(_run_net_viewer, job_id, req.layer, req.net, task.id)
    return TaskOut(task_id=task.id, kind=task.kind, job_id=task.job_id,
                   status=task.status, progress=task.progress)


def _run_component_viewer(job_id: str, side: str, task_id: str) -> None:
    registry.update(task_id, status="running", message=f"component geometry: {side}")
    try:
        cache_dir, cache_name = job_store.cache_args(job_id, workspace_root=WORKSPACE_ROOT)
        rdir = job_store.reports_dir(job_id, workspace_root=WORKSPACE_ROOT)
        out_path = rdir / f"geomcomp_{side}.json"
        summary = viewer_service.build_component_geometry(
            cache_dir, cache_name, side, out_path, log=lambda m: None)
        registry.update(task_id, status="done", progress=1.0, result=summary)
    except Exception as exc:  # noqa: BLE001
        registry.update(task_id, status="error", error=str(exc))


@router.post("/jobs/{job_id}/viewer/component", response_model=TaskOut)
def run_component_viewer(job_id: str, req: ComponentViewerRequest,
                         background: BackgroundTasks,
                         user: str = Depends(get_current_user)) -> TaskOut:
    if not job_store.is_cached(job_id, workspace_root=WORKSPACE_ROOT):
        raise HTTPException(status_code=404, detail="job not found or not ready")
    task = registry.create("viewer", job_id=job_id)
    background.add_task(_run_component_viewer, job_id, req.side, task.id)
    return TaskOut(task_id=task.id, kind=task.kind, job_id=task.job_id,
                   status=task.status, progress=task.progress)
