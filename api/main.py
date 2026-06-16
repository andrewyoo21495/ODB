"""FastAPI application for the ODB++ 자동화 허브.

Run locally with::

    uvicorn api.main:app --reload

Interactive docs at ``/docs``.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# Ensure the repo root is importable (so ``src`` resolves) regardless of cwd.
sys.path.insert(0, str(REPO_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routers import (
    checklist, compare, copper, extract, interposer, jobs, meta, tasks, viewer,
)

app = FastAPI(title="ODB++ 자동화 허브 API", version="0.1.0")

# Compress large JSON/HTML responses (viewer geometry can be several MB).
app.add_middleware(GZipMiddleware, minimum_size=1024)

# CORS open for local dev (Vite dev server on another port).  Tighten for prod.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router, prefix="/api")
app.include_router(checklist.router, prefix="/api")
app.include_router(copper.router, prefix="/api")
app.include_router(extract.router, prefix="/api")
app.include_router(interposer.router, prefix="/api")
app.include_router(compare.router, prefix="/api")
app.include_router(viewer.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(meta.router, prefix="/api")


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Serve the built frontend (single-port deployment).
# Run `npm --prefix frontend run build` to produce frontend/dist, then this
# app serves the SPA at "/" alongside the API at "/api".  In dev (no dist),
# this block is skipped and the Vite dev server (port 5173) is used instead.
# ---------------------------------------------------------------------------
_DIST = REPO_ROOT / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def _spa_index() -> FileResponse:
        return FileResponse(_DIST / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa_fallback(full_path: str) -> FileResponse:
        # Serve a real static file if it exists; otherwise return index.html
        # so client-side routes (/viewer, /compare, ...) work on refresh.
        candidate = _DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
