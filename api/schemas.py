"""Pydantic request/response models for the API.

These mirror the dataclasses in ``src/models.py`` / ``job_store`` metadata at the
HTTP boundary.  FastAPI generates the OpenAPI schema from them, which the React
frontend can turn into TypeScript types (openapi-typescript).
"""

from __future__ import annotations

from pydantic import BaseModel


class JobOut(BaseModel):
    job_id: str
    original_filename: str = ""
    job_name: str = ""
    project: str = ""          # 과제 (user-entered)
    model: str = ""            # 모델 (user-entered)
    board_type: str = ""       # 타입 (user-entered: Main/Secondary/Sub/...)
    revision: str = ""         # 리비전 (user-entered)
    units: str = ""
    odb_version: str = ""
    data_type: str = ""
    uploaded_by: str = ""
    uploaded_at: str = ""


class JobMetaUpdate(BaseModel):
    """User-editable job metadata. Omitted (None) fields are left unchanged;
    an empty string clears the field."""
    project: str | None = None
    model: str | None = None
    board_type: str | None = None
    revision: str | None = None


class MetaOptions(BaseModel):
    """Previously-used values per field, for input-history autocomplete."""
    projects: list[str] = []
    models: list[str] = []
    board_types: list[str] = []
    revisions: list[str] = []


class ActiveJob(BaseModel):
    """An upload whose cache is still building (in-progress dashboard row).

    Served from the in-memory task registry so it survives page navigation but
    not a server restart (a crashed build never leaves a stuck row)."""
    job_id: str
    original_filename: str = ""
    project: str = ""
    model: str = ""
    board_type: str = ""
    revision: str = ""
    uploaded_by: str = ""
    progress: float = 0.0
    message: str = ""


class JobStatus(BaseModel):
    job_id: str
    status: str                       # caching | ready | error | unknown
    progress: float = 0.0
    message: str = ""
    error: str | None = None


class TaskOut(BaseModel):
    task_id: str
    kind: str
    job_id: str | None = None
    status: str
    progress: float = 0.0
    message: str = ""
    result: dict = {}
    error: str | None = None


class ResultOut(BaseModel):
    """A completed analysis recorded for a job (survives restarts/navigation)."""
    kind: str
    report: str | None = None
    summary: dict = {}
    params: dict = {}
    created_by: str = ""
    completed_at: str = ""


class RuleInfo(BaseModel):
    rule_id: str
    description: str = ""
    category: str = ""


class ChecklistRequest(BaseModel):
    rule_ids: list[str] | None = None


class CopperRequest(BaseModel):
    method: str = "vector"   # "vector" | "raster"
    n_rows: int = 5
    n_cols: int = 5


class ExtractRequest(BaseModel):
    categories: list[str] | None = None   # None/empty = all categories


class CompareRequest(BaseModel):
    old_job_id: str
    new_job_id: str


class ViewerRequest(BaseModel):
    layer: str


class NetViewerRequest(BaseModel):
    layer: str
    net: str


class ComponentViewerRequest(BaseModel):
    side: str = "top"                       # "top" | "bottom" | "both"
    refdes: list[str] | None = None         # None/empty = all components


class LayerInfo(BaseModel):
    name: str
    type: str = ""


class ComponentInfo(BaseModel):
    refdes: str
    part: str = ""
    category: str = ""
    side: str = ""


class ActivityEntry(BaseModel):
    ts: str
    user: str = ""
    ip: str = ""
    method: str = ""
    path: str = ""


class ActivityUser(BaseModel):
    user: str
    count: int = 0
    ips: list[str] = []
    last_seen: str = ""


class ActivityOut(BaseModel):
    recent: list[ActivityEntry] = []
    users: list[ActivityUser] = []
