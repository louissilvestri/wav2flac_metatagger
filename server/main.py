"""Music Manager v2 — FastAPI server.

REST + SSE transport over the shared services layer. Serves the static
Next.js export from web-next/out/ when present (Phase 3).

Run:  uvicorn server.main:app --port 8178
  or: python -m server
"""

import json
import os
import queue
import signal
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import load_settings, save_settings, APP_NAME, APP_VERSION
from database import init_db, get_recent_logs, get_stats
from encoder import find_flac_exe

from services import providers, library_service, input_scan
from services.art import fetch_album_art_compared, get_embedded_art
from services.completeness import calculate_metadata_completeness, compute_album_completeness
from services.conversion import run_conversion
from server.jobs import init_jobs_table, recover_orphaned_jobs, job_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_jobs_table()
    orphaned = recover_orphaned_jobs()
    if orphaned:
        print(f"Recovered {orphaned} orphaned job(s) from a previous run")
    yield


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)


# ─── Health / lifecycle ─────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"name": APP_NAME, "version": APP_VERSION, "status": "ok"}


@app.post("/api/shutdown")
def shutdown():
    """Graceful self-shutdown (used by the launcher to replace stale instances)."""
    def _exit():
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Timer(0.3, _exit).start()
    return {"shutting_down": True}


# ─── Settings ───────────────────────────────────────────────────────────────────

@app.get("/api/settings")
def get_settings():
    return load_settings()


@app.put("/api/settings")
def update_settings(new_settings: dict):
    settings = load_settings()
    settings.update(new_settings)
    save_settings(settings)
    return {"success": True}


@app.post("/api/settings/autodetect-flac")
def autodetect_flac():
    return {"path": find_flac_exe() or ""}


# ─── Convert: scan + lookup ─────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    folder_path: str | None = None


@app.post("/api/input/scan")
def scan_input(req: ScanRequest):
    folder = req.folder_path or load_settings().get("input_folder", "")
    return input_scan.scan_input_folder(folder)


@app.get("/api/input/local-art")
def input_local_art(folder: str | None = None):
    """Thumbnail of the rip folder's own EAC art, for the Convert art picker."""
    from services.art import get_local_art_preview
    search_folder = folder or load_settings().get("input_folder", "")
    return get_local_art_preview(search_folder)


@app.post("/api/lookup/automated")
def automated_lookup(req: ScanRequest):
    if not req.folder_path:
        raise HTTPException(400, "folder_path is required")
    return providers.automated_cue_lookup(req.folder_path)


@app.get("/api/lookup/search")
def search_releases(artist: str = "", album: str = "", tracks: int | None = None):
    return providers.search_releases(artist=artist or None, album=album or None,
                                     track_count=tracks)


@app.get("/api/releases/{release_id}")
def get_release(release_id: str):
    return providers.get_release(release_id)


@app.get("/api/releases/{release_id}/art")
def get_release_art(release_id: str, folder: str | None = None):
    settings = load_settings()
    search_folder = folder or settings.get("input_folder", "")
    return fetch_album_art_compared(release_id, search_folder, settings)


class CompletenessRequest(BaseModel):
    release_details: dict | None = None
    cue_metadata: dict | None = None
    has_art: bool = False
    metadata: dict | None = None  # single-track mode


@app.post("/api/completeness")
def completeness(req: CompletenessRequest):
    if req.metadata is not None:
        return calculate_metadata_completeness(req.metadata, has_art=req.has_art)
    return compute_album_completeness(req.release_details, req.cue_metadata, req.has_art)


# ─── Convert: jobs ──────────────────────────────────────────────────────────────

class ConvertRequest(BaseModel):
    files: list[dict]
    release_details: dict | None = None
    options: dict | None = None


@app.post("/api/convert")
def start_convert(req: ConvertRequest):
    if job_manager.is_running("convert"):
        raise HTTPException(409, "A conversion is already running")

    def _target(job_id, payload, ctx):
        return run_conversion(
            payload["files"], payload.get("release_details"), payload.get("options"),
            on_progress=ctx.progress,
            on_file_done=ctx.file_done,
            is_cancelled=ctx.is_cancelled,
        )

    job_id = job_manager.start("convert", req.model_dump(), _target)
    return {"job_id": job_id}


@app.get("/api/jobs")
def list_jobs(limit: int = 20):
    return job_manager.list_recent(limit)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if not job_manager.get(job_id):
        raise HTTPException(404, "Job not found")
    return {"cancelled": job_manager.cancel(job_id)}


@app.get("/api/jobs/{job_id}/events")
def job_events(job_id: str):
    """Server-Sent Events stream of job progress. Falls back politely: if the
    job is already finished, emits its final state and closes."""
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    def _stream():
        # Late joiner: replay current state first
        current = job_manager.get(job_id)
        yield f"event: status\ndata: {json.dumps({'status': current['status'], 'progress': current.get('progress')})}\n\n"
        if current["status"] in ("done", "failed", "cancelled", "interrupted"):
            return

        q = job_manager.subscribe(job_id)
        try:
            while True:
                try:
                    event = q.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'], default=str)}\n\n"
                if event["event"] == "done":
                    return
        finally:
            job_manager.unsubscribe(job_id, q)

    return StreamingResponse(_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


# ─── Metadata aggregation (Phase 2) ─────────────────────────────────────────────

class IdentifyRequest(BaseModel):
    artist: str = ""
    album: str = ""
    disc_id: str | None = None
    track_count: int | None = None
    file_paths: list[str] | None = None
    folder_path: str | None = None  # CUE folder: server derives disc_id/artist/album


@app.post("/api/metadata/identify")
def metadata_identify(req: IdentifyRequest):
    """Multi-provider identification: returns one merged record with per-field
    provenance, track listing, and ranked art candidates.

    Pass folder_path for a rip folder: the disc ID, artist/album hints, and
    fingerprintable file list are derived from the CUE + WAVs automatically.
    """
    from services.metadata.aggregator import identify

    artist, album = req.artist, req.album
    disc_id, track_count = req.disc_id, req.track_count
    file_paths = req.file_paths

    if req.folder_path:
        from cue_parser import (
            parse_cue_file, find_cue_file, cue_to_metadata,
            calculate_musicbrainz_discid, get_leadout_from_cue_and_wavs,
        )
        from file_manager import scan_wav_files

        cue_path = find_cue_file(req.folder_path)
        if cue_path:
            try:
                cue_data = parse_cue_file(cue_path)
                cue_meta = cue_to_metadata(cue_data)
                artist = artist or cue_meta["album"].get("artist", "")
                album = album or cue_meta["album"].get("album", "")
                track_count = track_count or cue_meta["track_count"]
                leadout = get_leadout_from_cue_and_wavs(cue_data, req.folder_path)
                if leadout and not disc_id:
                    disc_id = calculate_musicbrainz_discid(
                        cue_data, leadout, cue_folder=req.folder_path)
            except Exception:
                pass
        if not file_paths:
            file_paths = [f["path"] for f in scan_wav_files(req.folder_path)]

    return identify(
        artist=artist, album=album, disc_id=disc_id,
        track_count=track_count, file_paths=file_paths,
    )


@app.get("/api/metadata/fingerprint-status")
def fingerprint_status():
    from services.metadata.providers import acoustid
    return {
        "available": acoustid.is_available(),
        "fpcalc": acoustid.find_fpcalc(),
    }


@app.get("/api/metadata/precedence")
def metadata_precedence():
    """Effective per-field provider precedence + enabled providers, for the
    Settings editor. Saved back via PUT /api/settings (merge_precedence /
    metadata_providers_enabled keys)."""
    from services.metadata.merge import get_precedence, DEFAULT_PRECEDENCE
    from services.metadata.aggregator import DEFAULT_ENABLED
    settings = load_settings()
    return {
        "precedence": get_precedence(settings),
        "defaults": DEFAULT_PRECEDENCE,
        "enabled": settings.get("metadata_providers_enabled", DEFAULT_ENABLED),
        "all_providers": DEFAULT_ENABLED,
    }


# ─── History / Dashboard ────────────────────────────────────────────────────────

@app.get("/api/history")
def history(limit: int = 100):
    return get_recent_logs(limit)


@app.get("/api/stats")
def stats():
    return get_stats()


# ─── Library ────────────────────────────────────────────────────────────────────

@app.get("/api/library/scan")
def library_scan():
    output_folder = load_settings().get("output_folder", "")
    return library_service.scan_library_full(output_folder)


class PathRequest(BaseModel):
    path: str


@app.post("/api/library/delete-file")
def library_delete_file(req: PathRequest):
    output_folder = load_settings().get("output_folder", "")
    return library_service.delete_library_file(req.path, output_folder)


@app.get("/api/library/embedded-art")
def library_embedded_art(path: str):
    return get_embedded_art(path)


@app.get("/api/library/original-album")
def library_original_album(artist: str, title: str):
    from library_manager import find_original_album
    return find_original_album(artist, title)


@app.get("/api/library/album-search")
def library_album_search(artist: str = "", album: str = ""):
    result = providers.find_album_by_name(artist, album)
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(502, result["error"])
    return result


@app.get("/api/library/art-options")
def library_art_options(release_group_id: str):
    from library_manager import get_art_options
    return get_art_options(release_group_id)


class ReassignRequest(BaseModel):
    path: str
    metadata: dict
    move_file: bool = True
    art_release_id: str | None = None
    art_url: str | None = None


@app.post("/api/library/reassign")
def library_reassign(req: ReassignRequest):
    output_folder = load_settings().get("output_folder", "")
    return library_service.reassign_track_with_art(
        req.path, req.metadata, output_folder, req.move_file, req.art_release_id,
        art_url=req.art_url)


class ReassignPreviewRequest(BaseModel):
    path: str
    metadata: dict


@app.post("/api/library/reassign/preview")
def library_reassign_preview(req: ReassignPreviewRequest):
    output_folder = load_settings().get("output_folder", "")
    return library_service.preview_reassign(req.path, req.metadata, output_folder)


class BatchReassignRequest(BaseModel):
    tracks: list[dict]
    album_metadata: dict
    art_release_id: str | None = None
    art_url: str | None = None


@app.post("/api/library/batch-reassign")
def library_batch_reassign(req: BatchReassignRequest):
    output_folder = load_settings().get("output_folder", "")
    return library_service.batch_reassign_album(
        req.tracks, req.album_metadata, output_folder, req.art_release_id,
        art_url=req.art_url)


class BrowseRequest(BaseModel):
    kind: str = "folder"


@app.post("/api/settings/browse-dialog")
def browse_dialog(req: BrowseRequest):
    """Native folder/file picker — valid because the server runs on the
    user's own desktop session."""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    if req.kind == "exe":
        path = filedialog.askopenfilename(
            title="Select flac.exe",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")])
    else:
        path = filedialog.askdirectory(title="Select Folder")
    root.destroy()
    return {"path": path or ""}


# ─── Static frontend (Phase 3: Next.js export) ──────────────────────────────────

class _FrontendFiles(StaticFiles):
    """Static serving with sane caching: HTML is never cached (so a rebuild
    is picked up on plain reload — no stale UI referencing old chunks), while
    hashed /_next/static assets cache forever."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        elif "/_next/static/" in scope.get("path", ""):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


_NEXT_OUT = Path(__file__).resolve().parent.parent / "web-next" / "out"
if _NEXT_OUT.is_dir():
    app.mount("/", _FrontendFiles(directory=str(_NEXT_OUT), html=True), name="frontend")
