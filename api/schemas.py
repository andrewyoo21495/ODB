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
    units: str = ""
    odb_version: str = ""
    data_type: str = ""
    uploaded_at: str = ""


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
    side: str = "top"   # "top" | "bottom"


class LayerInfo(BaseModel):
    name: str
    type: str = ""
