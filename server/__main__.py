"""Launcher: `python -m server` starts the v2 API + UI.
`python -m server --open` also opens the desktop app window (Edge app mode).

Replaces a stale instance if one is already bound to the port: the old
server's /api/shutdown is called, then we take over. This kills the
"restarted the app but old code is still running" failure mode.
"""

import os
import subprocess
import sys
import threading
import time
import webbrowser

import httpx
import uvicorn

from config import APP_VERSION

PORT = 8178


def _open_app_window():
    """Open the UI in a chromeless browser app window after the server binds."""
    url = f"http://127.0.0.1:{PORT}/"
    candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
    ]
    time.sleep(1.5)
    for exe in candidates:
        if os.path.exists(exe):
            subprocess.Popen([exe, f"--app={url}", "--disable-extensions"])
            return
    webbrowser.open(url)


def _replace_stale_instance():
    base = f"http://127.0.0.1:{PORT}"
    try:
        r = httpx.get(f"{base}/api/health", timeout=2)
        info = r.json()
    except Exception:
        return  # Port free or not ours — uvicorn will report a real conflict

    print(f"Found running instance v{info.get('version')} on port {PORT}; replacing it...")
    try:
        httpx.post(f"{base}/api/shutdown", timeout=2)
    except Exception:
        pass
    for _ in range(20):
        time.sleep(0.25)
        try:
            httpx.get(f"{base}/api/health", timeout=1)
        except Exception:
            print("Old instance stopped.")
            return
    print("WARNING: old instance did not stop; startup may fail.", file=sys.stderr)


if __name__ == "__main__":
    _replace_stale_instance()
    if "--open" in sys.argv:
        threading.Thread(target=_open_app_window, daemon=True).start()
    print(f"Music Manager v{APP_VERSION} on http://127.0.0.1:{PORT}")
    uvicorn.run("server.main:app", host="127.0.0.1", port=PORT, log_level="warning")
