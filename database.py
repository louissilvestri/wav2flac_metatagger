"""SQLite database for activity logging."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from config import DB_FILE, ensure_config_dir


def get_connection() -> sqlite3.Connection:
    ensure_config_dir()
    conn = sqlite3.connect(str(DB_FILE), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA wal_autocheckpoint=1000")
    conn.row_factory = sqlite3.Row
    return conn


# Current on-disk schema version. Bump this and add a block in _run_migrations()
# whenever the schema changes, so existing activity.db files upgrade cleanly.
_SCHEMA_VERSION = 1


def _run_migrations(conn: sqlite3.Connection):
    """Apply incremental schema migrations, tracked via PRAGMA user_version.

    The base tables are created with IF NOT EXISTS, so a database from before
    versioning is already at the v1 shape — we just stamp it. Future changes go
    here as `if version < N:` blocks that ALTER, then set version = N."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]

    # Example for the next schema change:
    # if version < 2:
    #     conn.execute("ALTER TABLE conversion_log ADD COLUMN replaygain_applied INTEGER")
    #     version = 2

    if version != _SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        conn.commit()


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversion_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            source_path TEXT NOT NULL,
            dest_path TEXT,
            status TEXT NOT NULL CHECK(status IN ('started', 'completed', 'failed', 'skipped')),
            duration_ms INTEGER,
            source_sample_rate INTEGER,
            source_bit_depth INTEGER,
            source_channels INTEGER,
            flac_compression_level INTEGER,
            verify_passed INTEGER,
            file_size_before INTEGER,
            file_size_after INTEGER,
            compression_ratio REAL,
            error_message TEXT,
            metadata_source TEXT,
            musicbrainz_release_id TEXT,
            album TEXT,
            artist TEXT,
            title TEXT,
            track_number INTEGER,
            disc_number INTEGER
        );

        CREATE TABLE IF NOT EXISTS metadata_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lookup_key TEXT NOT NULL UNIQUE,
            lookup_type TEXT NOT NULL,
            response_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            expires_at TEXT
        );

        CREATE TABLE IF NOT EXISTS album_art_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            musicbrainz_release_id TEXT NOT NULL UNIQUE,
            image_path TEXT,
            source_url TEXT,
            fetched_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_log_timestamp ON conversion_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_log_status ON conversion_log(status);
        CREATE INDEX IF NOT EXISTS idx_log_artist_album ON conversion_log(artist, album);
        CREATE INDEX IF NOT EXISTS idx_cache_key ON metadata_cache(lookup_key);
    """)
    conn.commit()
    _run_migrations(conn)
    conn.close()


def log_conversion(
    source_path: str,
    dest_path: str = None,
    status: str = "started",
    duration_ms: int = None,
    source_sample_rate: int = None,
    source_bit_depth: int = None,
    source_channels: int = None,
    flac_compression_level: int = None,
    verify_passed: bool = None,
    file_size_before: int = None,
    file_size_after: int = None,
    error_message: str = None,
    metadata_source: str = None,
    musicbrainz_release_id: str = None,
    album: str = None,
    artist: str = None,
    title: str = None,
    track_number: int = None,
    disc_number: int = None,
) -> int:
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    compression_ratio = None
    if file_size_before and file_size_after and file_size_before > 0:
        compression_ratio = round(file_size_after / file_size_before, 4)

    cursor = conn.execute(
        """INSERT INTO conversion_log (
            timestamp, source_path, dest_path, status, duration_ms,
            source_sample_rate, source_bit_depth, source_channels,
            flac_compression_level, verify_passed,
            file_size_before, file_size_after, compression_ratio,
            error_message, metadata_source, musicbrainz_release_id,
            album, artist, title, track_number, disc_number
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            now, source_path, dest_path, status, duration_ms,
            source_sample_rate, source_bit_depth, source_channels,
            flac_compression_level,
            1 if verify_passed is True else (0 if verify_passed is False else None),
            file_size_before, file_size_after, compression_ratio,
            error_message, metadata_source, musicbrainz_release_id,
            album, artist, title, track_number, disc_number,
        ),
    )
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def update_conversion(row_id: int, **kwargs):
    conn = get_connection()
    if "verify_passed" in kwargs and kwargs["verify_passed"] is not None:
        kwargs["verify_passed"] = 1 if kwargs["verify_passed"] else 0
    if "file_size_before" in kwargs and "file_size_after" in kwargs:
        before = kwargs["file_size_before"]
        after = kwargs["file_size_after"]
        if before and after and before > 0:
            kwargs["compression_ratio"] = round(after / before, 4)
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [row_id]
    conn.execute(f"UPDATE conversion_log SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()


def get_recent_logs(limit: int = 100) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM conversion_log ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    conn = get_connection()
    row = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
            SUM(file_size_before) as total_wav_bytes,
            SUM(file_size_after) as total_flac_bytes,
            AVG(compression_ratio) as avg_compression,
            AVG(duration_ms) as avg_duration_ms
        FROM conversion_log
    """).fetchone()
    conn.close()
    return dict(row) if row else {}
