"""Persistent job queue for long-running work (conversions).

Jobs live in SQLite so they survive server restarts: a job killed mid-run is
marked 'interrupted' on the next startup instead of being lost. Progress
events stream to subscribers via in-memory queues (SSE), with the DB row as
the source of truth for late joiners and reconnects.
"""

import json
import queue
import threading
import uuid
from datetime import datetime, timezone

from database import get_connection


def init_jobs_table():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN
                ('queued', 'running', 'done', 'failed', 'cancelled', 'interrupted')),
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            payload TEXT,
            progress TEXT,
            result TEXT,
            error TEXT
        );
    """)
    conn.commit()
    conn.close()


def recover_orphaned_jobs() -> int:
    """Mark jobs left 'running'/'queued' by a previous process as interrupted."""
    conn = get_connection()
    cur = conn.execute(
        "UPDATE jobs SET status='interrupted', finished_at=? "
        "WHERE status IN ('running', 'queued')",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()
    count = cur.rowcount
    conn.close()
    return count


class JobManager:
    """Runs one job at a time per type, broadcasting progress events."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cancel_flags: dict[str, threading.Event] = {}
        self._subscribers: dict[str, list[queue.Queue]] = {}

    # ── persistence ──────────────────────────────────────────────────────────

    def _update(self, job_id: str, **fields):
        conn = get_connection()
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), job_id))
        conn.commit()
        conn.close()

    def get(self, job_id: str) -> dict | None:
        conn = get_connection()
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        conn.close()
        if not row:
            return None
        job = dict(row)
        for key in ("payload", "progress", "result"):
            if job.get(key):
                try:
                    job[key] = json.loads(job[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return job

    def list_recent(self, limit: int = 20) -> list[dict]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, type, status, created_at, started_at, finished_at, error "
            "FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ── events ───────────────────────────────────────────────────────────────

    def subscribe(self, job_id: str) -> queue.Queue:
        q = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id: str, q: queue.Queue):
        with self._lock:
            subs = self._subscribers.get(job_id, [])
            if q in subs:
                subs.remove(q)

    def _emit(self, job_id: str, event: dict):
        with self._lock:
            subs = list(self._subscribers.get(job_id, []))
        for q in subs:
            q.put(event)

    # ── lifecycle ────────────────────────────────────────────────────────────

    def is_running(self, job_type: str) -> bool:
        conn = get_connection()
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE type=? AND status='running'",
            (job_type,)).fetchone()
        conn.close()
        return row["n"] > 0

    def start(self, job_type: str, payload: dict, target) -> str:
        """Create a job row and run `target(job_id, payload, ctx)` in a thread.

        ctx provides: progress(dict), file_done(dict), is_cancelled() -> bool.
        target's return value is stored as the job result.
        """
        job_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()

        conn = get_connection()
        conn.execute(
            "INSERT INTO jobs (id, type, status, created_at, payload) VALUES (?, ?, 'queued', ?, ?)",
            (job_id, job_type, now, json.dumps(payload, default=str)),
        )
        conn.commit()
        conn.close()

        cancel_event = threading.Event()
        self._cancel_flags[job_id] = cancel_event

        manager = self

        class Ctx:
            @staticmethod
            def progress(p: dict):
                manager._update(job_id, progress=json.dumps(p, default=str))
                manager._emit(job_id, {"event": "progress", "data": p})

            @staticmethod
            def file_done(r: dict):
                manager._emit(job_id, {"event": "file_done", "data": r})

            @staticmethod
            def is_cancelled() -> bool:
                return cancel_event.is_set()

        def _runner():
            self._update(job_id, status="running",
                         started_at=datetime.now(timezone.utc).isoformat())
            self._emit(job_id, {"event": "status", "data": {"status": "running"}})
            try:
                result = target(job_id, payload, Ctx)
                status = "cancelled" if cancel_event.is_set() else "done"
                self._update(job_id, status=status,
                             finished_at=datetime.now(timezone.utc).isoformat(),
                             result=json.dumps(result, default=str))
                self._emit(job_id, {"event": "done", "data": {"status": status, "result": result}})
            except Exception as e:
                self._update(job_id, status="failed",
                             finished_at=datetime.now(timezone.utc).isoformat(),
                             error=str(e))
                self._emit(job_id, {"event": "done", "data": {"status": "failed", "error": str(e)}})
            finally:
                self._cancel_flags.pop(job_id, None)

        threading.Thread(target=_runner, daemon=True).start()
        return job_id

    def cancel(self, job_id: str) -> bool:
        event = self._cancel_flags.get(job_id)
        if event:
            event.set()
            return True
        return False


job_manager = JobManager()
