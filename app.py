"""Eel web UI adapter (v1 frontend).

All business logic lives in services/ (shared with the FastAPI server in
server/). This module is only the Eel transport layer plus the desktop
launcher, and is retired at the end of the v2 refactor.
"""

import eel
import os
import subprocess
import threading
import time
import webbrowser

from config import load_settings, save_settings, APP_NAME, APP_VERSION
from database import init_db, get_recent_logs, get_stats
from encoder import find_flac_exe

from services.art import (
    select_best_art, find_local_art_raw, find_local_art,
    fetch_album_art_compared, get_embedded_art as _get_embedded_art,
)
from services.completeness import (
    calculate_metadata_completeness, compute_album_completeness,
)
from services import providers, library_service, input_scan
from services.conversion import run_conversion

# Initialize Eel with the web folder
eel.init(os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"))

# Active conversion state (v1 single-job model)
_conversion_active = False
_conversion_cancel = False


# ─── App / Settings ────────────────────────────────────────────────────────────

@eel.expose
def get_app_info():
    return {"name": APP_NAME, "version": APP_VERSION}


@eel.expose
def get_settings():
    return load_settings()


@eel.expose
def update_settings(new_settings):
    settings = load_settings()
    settings.update(new_settings)
    save_settings(settings)
    return {"success": True}


@eel.expose
def browse_folder(dialog_type="folder"):
    """Open a folder/file browser dialog. Returns path or empty string."""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    if dialog_type == "folder":
        path = filedialog.askdirectory(title="Select Folder")
    elif dialog_type == "exe":
        path = filedialog.askopenfilename(
            title="Select flac.exe",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
    else:
        path = filedialog.askopenfilename(title="Select File")

    root.destroy()
    return path or ""


@eel.expose
def auto_detect_flac():
    return find_flac_exe() or ""


# ─── Convert: scan + lookup ─────────────────────────────────────────────────────

@eel.expose
def scan_input_folder(folder_path=None):
    if not folder_path:
        folder_path = load_settings().get("input_folder", "")
    return input_scan.scan_input_folder(folder_path)


@eel.expose
def run_automated_lookup(folder_path):
    return providers.automated_cue_lookup(folder_path)


@eel.expose
def lookup_metadata(artist, album, track_count=None):
    return providers.search_releases(artist=artist, album=album, track_count=track_count)


@eel.expose
def fetch_release_details(release_id):
    return providers.get_release(release_id)


@eel.expose
def fetch_album_art(release_id, folder_path=None):
    settings = load_settings()
    search_folder = folder_path or settings.get("input_folder", "")
    return fetch_album_art_compared(release_id, search_folder, settings)


@eel.expose
def get_metadata_completeness(release_details, cue_metadata, has_art):
    return compute_album_completeness(release_details, cue_metadata, has_art)


# ─── Convert: conversion ────────────────────────────────────────────────────────

@eel.expose
def start_conversion(files, release_details, options=None):
    global _conversion_active, _conversion_cancel
    if _conversion_active:
        return {"error": "Conversion already in progress"}

    _conversion_active = True
    _conversion_cancel = False

    def _worker():
        global _conversion_active
        try:
            run_conversion(
                files, release_details, options,
                on_progress=lambda p: eel.on_conversion_progress(p)(),
                on_file_done=lambda r: eel.on_conversion_file_done(r)(),
                is_cancelled=lambda: _conversion_cancel,
            )
        finally:
            _conversion_active = False

    threading.Thread(target=_worker, daemon=True).start()
    return {"success": True, "message": "Conversion started"}


@eel.expose
def cancel_conversion():
    global _conversion_cancel
    _conversion_cancel = True
    return {"success": True}


@eel.expose
def get_conversion_status():
    return {"active": _conversion_active}


# ─── History / Dashboard ────────────────────────────────────────────────────────

@eel.expose
def get_log_history(limit=100):
    return get_recent_logs(limit)


@eel.expose
def get_dashboard_stats():
    return get_stats()


# ─── Library Manager ────────────────────────────────────────────────────────────

@eel.expose
def scan_library():
    output_folder = load_settings().get("output_folder", "")
    return library_service.scan_library_full(output_folder)


@eel.expose
def delete_library_file(flac_path):
    output_folder = load_settings().get("output_folder", "")
    return library_service.delete_library_file(flac_path, output_folder)


@eel.expose
def get_embedded_art(flac_path):
    return _get_embedded_art(flac_path)


@eel.expose
def find_original_album(artist, title):
    from library_manager import find_original_album as _find
    return _find(artist, title)


@eel.expose
def find_original_album_by_name(artist, album_name):
    return providers.find_album_by_name(artist, album_name)


@eel.expose
def get_art_options(release_group_id):
    from library_manager import get_art_options as _get_art_options
    return _get_art_options(release_group_id)


@eel.expose
def get_release_for_reassign(release_id):
    return providers.get_release(release_id)


@eel.expose
def reassign_track(flac_path, new_metadata, move_file=True, art_release_id=None):
    output_folder = load_settings().get("output_folder", "")
    return library_service.reassign_track_with_art(
        flac_path, new_metadata, output_folder, move_file, art_release_id)


@eel.expose
def batch_reassign_album(tracks, album_metadata, art_release_id=None):
    output_folder = load_settings().get("output_folder", "")
    return library_service.batch_reassign_album(
        tracks, album_metadata, output_folder, art_release_id)


@eel.expose
def preview_reassign(flac_path, new_metadata):
    output_folder = load_settings().get("output_folder", "")
    return library_service.preview_reassign(flac_path, new_metadata, output_folder)


# ─── Launcher ───────────────────────────────────────────────────────────────────

_APP_PORT = 8178


def _find_browser():
    """Find Edge or Chrome executable path."""
    candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def main():
    init_db()
    settings = load_settings()

    if not settings.get("flac_exe_path"):
        detected = find_flac_exe()
        if detected:
            settings["flac_exe_path"] = detected
            save_settings(settings)

    url = f"http://localhost:{_APP_PORT}/index.html"
    browser_exe = _find_browser()

    def _launch_browser_delayed():
        time.sleep(1.5)
        if browser_exe:
            subprocess.Popen([browser_exe, f"--app={url}", "--disable-extensions"])
        else:
            webbrowser.open(url)

    threading.Thread(target=_launch_browser_delayed, daemon=True).start()

    print(f"Music Manager running at {url}")
    print("Close this window to stop the server.\n")

    try:
        eel.start(
            "index.html",
            mode=None,
            block=True,
            port=_APP_PORT,
            shutdown_delay=999999.0,  # Never auto-shutdown on disconnect
        )
    except (KeyboardInterrupt, SystemExit):
        pass
    except OSError as e:
        if "address already in use" in str(e).lower() or "10048" in str(e):
            print(f"Port {_APP_PORT} already in use. Opening browser to existing instance...")
            if browser_exe:
                subprocess.Popen([browser_exe, f"--app={url}", "--disable-extensions"])
            else:
                webbrowser.open(url)
        else:
            raise

    print("Music Manager stopped.")


if __name__ == "__main__":
    main()
