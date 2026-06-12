"""SQLite-backed provider response cache with TTL.

Replaces the v1 in-memory dict caches — survives restarts, shared by the Eel
app and the FastAPI server.
"""

import json
import time

from database import get_connection

# Default TTLs (seconds)
TTL_SEARCH = 7 * 86400      # searches reflect evolving DB state — shorter
TTL_RELEASE = 30 * 86400    # release/album metadata rarely changes


def init_cache_table():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS provider_cache (
            provider TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            fetched_at REAL NOT NULL,
            PRIMARY KEY (provider, key)
        );
    """)
    conn.commit()
    conn.close()


def get(provider: str, key: str, ttl: float):
    """Return the cached value, or None if absent/expired."""
    conn = get_connection()
    row = conn.execute(
        "SELECT value, fetched_at FROM provider_cache WHERE provider=? AND key=?",
        (provider, key)).fetchone()
    conn.close()
    if not row:
        return None
    if time.time() - row["fetched_at"] > ttl:
        return None
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return None


def put(provider: str, key: str, value):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO provider_cache (provider, key, value, fetched_at) "
        "VALUES (?, ?, ?, ?)",
        (provider, key, json.dumps(value, default=str), time.time()))
    conn.commit()
    conn.close()


def cached(provider: str, key: str, ttl: float, fetch_fn):
    """Read-through cache: return cached value or call fetch_fn and store.

    Exceptions from fetch_fn propagate; only successful (non-None) results
    are cached.
    """
    hit = get(provider, key, ttl)
    if hit is not None:
        return hit
    value = fetch_fn()
    if value is not None:
        put(provider, key, value)
    return value
