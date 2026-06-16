"""Job store: content-addressed workspace for the ODB++ hub.

Each uploaded ODB++ archive becomes a *job* identified by the SHA-256 of its
content.  Everything related to that job lives under one directory::

    workspace/<job_id>/
    ├── source.tgz     copied source archive
    ├── meta.json      job metadata (filename, job_name, units, timestamps, hash)
    ├── cache/         data_service JSON cache (incl. copper_data.json)
    └── reports/       generated HTML reports

This is the storage layer the web API (and MCP) build on.  The CLI keeps its
own ``cache/<stem>/`` layout; both share :mod:`src.services.data_service`
underneath, so there is no duplicated parsing logic.

Because ``job_id`` is the content hash, re-uploading the same archive reuses
the existing cache instead of re-parsing (avoids redundant work, no filename
collisions between users).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from src.services import data_service

LogFn = Callable[[str], None]

DEFAULT_WORKSPACE_ROOT = Path("workspace")

CACHE_NAME = "cache"         # data_service cache_name -> workspace/<id>/cache/
_CACHE_NAME = CACHE_NAME      # backward-compatible alias
_REPORTS_SUBDIR = "reports"
_META_FILE = "meta.json"
_RESULTS_FILE = "results.json"
_SOURCE_FILE = "source.tgz"
_LOCK_DIR = ".lock"

# Serialises read-modify-write of results.json within this process (the server
# is single-process; tasks run in a threadpool).
_RESULTS_LOCK = threading.Lock()

_JOB_ID_LEN = 16


# --------------------------------------------------------------------------- #
# Path helpers
# --------------------------------------------------------------------------- #
def job_dir(job_id: str, *, workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT) -> Path:
    """Root directory for a job (``workspace/<job_id>``)."""
    return Path(workspace_root) / job_id


def cache_json_dir(job_id: str, *, workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT) -> Path:
    """Directory holding the JSON cache files (``workspace/<job_id>/cache``)."""
    return job_dir(job_id, workspace_root=workspace_root) / _CACHE_NAME


def copper_data_path(job_id: str, *, workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT) -> Path:
    """Path to the job's ``copper_data.json`` (may not exist)."""
    return cache_json_dir(job_id, workspace_root=workspace_root) / "copper_data.json"


def reports_dir(job_id: str, *, workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT) -> Path:
    """Directory for generated reports, created on demand."""
    p = job_dir(job_id, workspace_root=workspace_root) / _REPORTS_SUBDIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_args(job_id: str, *, workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT) -> tuple[Path, str]:
    """Return ``(cache_dir, cache_name)`` to pass to ``data_service`` functions."""
    return job_dir(job_id, workspace_root=workspace_root), CACHE_NAME


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #
def _hash_file(path: Path, *, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _cache_present(job_id: str, *, workspace_root: str | Path) -> bool:
    d = cache_json_dir(job_id, workspace_root=workspace_root)
    return d.exists() and any(d.glob("*.json"))


def compute_job_id(source: str | Path) -> str:
    """Return the content-addressed job_id for an archive without ingesting it."""
    return _hash_file(Path(source))[:_JOB_ID_LEN]


def is_cached(job_id: str, *, workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT) -> bool:
    """True if the job's JSON cache already exists."""
    return _cache_present(job_id, workspace_root=workspace_root)


@contextlib.contextmanager
def _build_lock(jdir: Path, *, timeout: float = 600.0, poll: float = 0.2):
    """Single-machine mutex via atomic ``os.mkdir`` of a ``.lock`` directory.

    Only the cache-build section is serialised; reads need no lock because the
    cache is write-once.  Sufficient for a single-host server (deployment A).
    """
    lock = jdir / _LOCK_DIR
    start = time.time()
    while True:
        try:
            os.mkdir(lock)
            break
        except FileExistsError:
            if time.time() - start > timeout:
                raise TimeoutError(f"Timed out acquiring build lock: {lock}")
            time.sleep(poll)
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.rmdir(lock)


def _write_meta(jdir: Path, *, job_id: str, original_filename: str,
                source_sha256: str, data: dict | None,
                uploaded_by: str = "anonymous") -> dict:
    job_info = data.get("job_info") if data else None
    meta = {
        "job_id": job_id,
        "original_filename": original_filename,
        "job_name": getattr(job_info, "job_name", "") if job_info else "",
        "units": getattr(job_info, "units", "") if job_info else "",
        "odb_version": (
            f"{job_info.odb_version_major}.{job_info.odb_version_minor}"
            if job_info else ""
        ),
        "data_type": data.get("data_type", "") if data else "",
        "source_sha256": source_sha256,
        "uploaded_by": uploaded_by,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    (jdir / _META_FILE).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return meta


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def create_job(source: str | Path, *, original_filename: str | None = None,
               uploaded_by: str = "anonymous",
               workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT,
               log: LogFn | None = None,
               progress: data_service.ProgressFn | None = None) -> str:
    """Register an ODB++ archive as a job and ensure its cache is built.

    Args:
        source: path to the ODB++ ``.tgz`` archive.
        original_filename: name to remember for display (defaults to source name).
        workspace_root: workspace root directory.
        log: optional progress callback forwarded to the cache builder.
        progress: optional ``(fraction, message)`` callback for a UI progress bar.

    Returns:
        The content-addressed ``job_id``.  Idempotent: an archive whose content
        was already ingested reuses the existing cache without re-parsing.
    """
    source = Path(source)
    source_sha256 = _hash_file(source)
    job_id = source_sha256[:_JOB_ID_LEN]

    jdir = job_dir(job_id, workspace_root=workspace_root)
    jdir.mkdir(parents=True, exist_ok=True)

    # Keep a self-contained copy of the source archive.
    stored_source = jdir / _SOURCE_FILE
    if not stored_source.exists():
        shutil.copy2(source, stored_source)

    if not _cache_present(job_id, workspace_root=workspace_root):
        with _build_lock(jdir):
            # Re-check inside the lock in case another worker just built it.
            if not _cache_present(job_id, workspace_root=workspace_root):
                data = data_service.build_cache(
                    stored_source, jdir, cache_name=_CACHE_NAME,
                    log=log if log is not None else print,
                    progress=progress,
                )
                _write_meta(jdir, job_id=job_id,
                            original_filename=original_filename or source.name,
                            source_sha256=source_sha256, data=data,
                            uploaded_by=uploaded_by)

    # Ensure meta exists even for a pre-existing cache without one.
    if not (jdir / _META_FILE).exists():
        _write_meta(jdir, job_id=job_id,
                    original_filename=original_filename or source.name,
                    source_sha256=source_sha256, data=None,
                    uploaded_by=uploaded_by)

    return job_id


def load_job_data(job_id: str, *, workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT,
                  log: LogFn | None = None) -> dict:
    """Load and reconstruct a job's parsed data from its cache."""
    jdir = job_dir(job_id, workspace_root=workspace_root)
    if not _cache_present(job_id, workspace_root=workspace_root):
        raise FileNotFoundError(f"No cache for job_id={job_id} under {jdir}")
    return data_service.load_job(jdir, _CACHE_NAME, log=log)


def get_meta(job_id: str, *, workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT) -> dict:
    """Return a job's metadata dict."""
    p = job_dir(job_id, workspace_root=workspace_root) / _META_FILE
    if not p.exists():
        raise FileNotFoundError(f"No meta.json for job_id={job_id}")
    return json.loads(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Results index — records completed analyses so a job's prior reports survive
# page navigation and server restarts (in-memory TaskRegistry does not persist).
# --------------------------------------------------------------------------- #
def _results_path(job_id: str, *, workspace_root: str | Path) -> Path:
    return job_dir(job_id, workspace_root=workspace_root) / _RESULTS_FILE


def record_result(job_id: str, kind: str, *, report: str | None = None,
                  summary: dict | None = None, params: dict | None = None,
                  created_by: str = "anonymous",
                  workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT) -> dict:
    """Persist (or overwrite) the latest completed result for a (job, kind).

    Stores the report filename + summary + params so a feature page can show a
    prior run without recomputing.  Keyed by ``kind`` (latest wins)."""
    entry = {
        "kind": kind,
        "report": report,
        "summary": summary or {},
        "params": params or {},
        "created_by": created_by,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _results_path(job_id, workspace_root=workspace_root)
    with _RESULTS_LOCK:
        results: dict = {}
        if path.exists():
            with contextlib.suppress(json.JSONDecodeError):
                results = json.loads(path.read_text(encoding="utf-8"))
        results[kind] = entry
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(results, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    return entry


def list_results(job_id: str, *,
                 workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT) -> list[dict]:
    """All recorded results for a job (one entry per kind)."""
    path = _results_path(job_id, workspace_root=workspace_root)
    if not path.exists():
        return []
    with contextlib.suppress(json.JSONDecodeError):
        return list(json.loads(path.read_text(encoding="utf-8")).values())
    return []


def get_result(job_id: str, kind: str, *,
               workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT) -> dict | None:
    """The recorded result for one (job, kind), or ``None``."""
    path = _results_path(job_id, workspace_root=workspace_root)
    if not path.exists():
        return None
    with contextlib.suppress(json.JSONDecodeError):
        return json.loads(path.read_text(encoding="utf-8")).get(kind)
    return None


def delete_job(job_id: str, *,
               workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT) -> bool:
    """Delete a job's entire workspace directory (source, cache, reports).

    Returns True if a directory was removed, False if it did not exist.
    """
    jdir = job_dir(job_id, workspace_root=workspace_root)
    if not jdir.exists():
        return False
    shutil.rmtree(jdir)
    return True


def list_jobs(*, workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT) -> list[dict]:
    """List metadata for all jobs in the workspace (for the dashboard)."""
    root = Path(workspace_root)
    if not root.exists():
        return []
    jobs: list[dict] = []
    for d in sorted(root.iterdir()):
        meta = d / _META_FILE
        if d.is_dir() and meta.exists():
            jobs.append(json.loads(meta.read_text(encoding="utf-8")))
    return jobs
