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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api import activity
from api.deps import WORKSPACE_ROOT, sanitize_user
from api.routers import (
    activity as activity_router,
    checklist, compare, copper, extract, interposer, jobs, meta, tasks, viewer,
    volume,
)

app = FastAPI(title="ODB++ 자동화 허브 API", version="0.1.0")

# Compress large JSON/HTML responses (viewer geometry can be several MB).
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def _access_log(request: Request, call_next):
    """Record who (X-User) accessed what (path) from where (IP).

    Unauthenticated deployment has no real identity, so this access log is the
    only visibility into usage.  Skips CORS preflight, health, and the activity
    endpoint itself to avoid noise/recursion."""
    path = request.url.path
    if (request.method != "OPTIONS" and path.startswith("/api")
            and path != "/api/health" and not path.startswith("/api/activity")):
        xff = request.headers.get("x-forwarded-for")
        ip = (xff.split(",")[0].strip() if xff
              else (request.client.host if request.client else ""))
        activity.record(
            WORKSPACE_ROOT,
            user=sanitize_user(request.headers.get("x-user")),
            ip=ip, method=request.method, path=path,
        )
    return await call_next(request)

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
app.include_router(volume.router, prefix="/api")
app.include_router(compare.router, prefix="/api")
app.include_router(viewer.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(meta.router, prefix="/api")
app.include_router(activity_router.router, prefix="/api")


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

    # The SPA shell must NEVER be cached: it's the only file with a stable URL
    # and it points at content-hashed JS/CSS.  If the browser serves a stale
    # index.html it loads an old bundle after every deploy (the cause of the
    # "no password prompt / 401" report).  Hashed assets under /assets stay
    # cacheable (their URL changes when content changes).
    def _index_response() -> FileResponse:
        return FileResponse(
            _DIST / "index.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.get("/", include_in_schema=False)
    def _spa_index() -> FileResponse:
        return _index_response()

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa_fallback(full_path: str) -> FileResponse:
        # Never let an unregistered API path fall through to index.html — that
        # returns HTML with status 200, which the frontend then fails to parse
        # as JSON, hiding the real cause (e.g. a new router added but the server
        # not restarted).  Surface it as a clear 404 instead.
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")
        # Serve a real static file if it exists; otherwise return index.html
        # so client-side routes (/viewer, /compare, ...) work on refresh.
        candidate = _DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return _index_response()
