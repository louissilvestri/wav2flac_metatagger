"""Launcher: `python -m server` starts the v2 API.

Replaces a stale instance if one is already bound to the port: the old
server's /api/shutdown is called, then we take over. This kills the
"restarted the app but old code is still running" failure mode.
"""

import sys
import time

import httpx
import uvicorn

from config import APP_VERSION

PORT = 8178


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
    print(f"Music Manager v{APP_VERSION} API on http://127.0.0.1:{PORT}")
    uvicorn.run("server.main:app", host="127.0.0.1", port=PORT, log_level="warning")
