"""SQLite-backed download history (the Library store).

The JSON file (download_history.json) stays the compatibility floor: it is
what older builds read and what the app falls back to when the database
cannot answer. This module adds a real database on top - durable storage
that outgrows the JSON file's 200-entry cap. The full entry is kept as a
JSON payload so the UI sees exactly the dicts it always saw; the columns
exist only for what SQL must do itself: find (title/url LIKE), order
(completed_at/title/status) and prune (filepath).

Writes arrive through a sink attached on download_queue
(set_history_sink), so the queue's own history logic stays single-purpose
and anything that never sets the sink never touches a database.
"""

import json
import logging
import os
import sqlite3
import threading

logger = logging.getLogger("universal_audio_studio.library_db")

# How many entries the library keeps. The JSON file caps at 200; the
# database is the long-term store, so its cap is generous but finite -
# unbounded growth on a download tool is not a feature.
MAX_ENTRIES = 2000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    url          TEXT PRIMARY KEY,
    title        TEXT NOT NULL DEFAULT '',
    filepath     TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT '',
    is_video     INTEGER NOT NULL DEFAULT 0,
    completed_at REAL NOT NULL DEFAULT 0,
    payload      TEXT NOT NULL DEFAULT '{}'
)
"""

_migration_checked = False
_migration_lock = threading.Lock()


def db_path() -> str:
    """The database file. TUNELAB_LIBRARY_DB overrides it (tests use this)."""
    override = os.environ.get("TUNELAB_LIBRARY_DB", "").strip()
    if override:
        return override
    from download_queue import APP_DATA_DIR
    return os.path.join(APP_DATA_DIR, "library.sqlite3")


def _connect():
    conn = sqlite3.connect(db_path(), timeout=10)
    # WAL so a worker-thread write never blocks a UI-thread read.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_SCHEMA)
    return conn


def _close(conn):
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def _row_to_entry(row) -> dict:
    payload, url, title, filepath, status, is_video, completed_at = row
    try:
        entry = json.loads(payload)
        if isinstance(entry, dict):
            return entry
    except Exception:
        pass
    # Reconstruct from the columns if the payload ever fails to parse.
    return {"url": url, "title": title, "filepath": filepath,
            "status": status, "is_video": bool(is_video),
            "completed_at": completed_at}


def record(entry) -> None:
    """Insert or replace one history entry (upsert by URL). Never raises."""
    if not isinstance(entry, dict):
        return
    url = str(entry.get("url", "")).strip()
    if not url:
        return
    conn = None
    try:
        conn = _connect()
        conn.execute(
            "INSERT INTO downloads (url, title, filepath, status, is_video,"
            " completed_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(url) DO UPDATE SET title=excluded.title,"
            " filepath=excluded.filepath, status=excluded.status,"
            " is_video=excluded.is_video,"
            " completed_at=excluded.completed_at, payload=excluded.payload",
            (url, str(entry.get("title") or ""),
             str(entry.get("filepath") or ""),
             str(entry.get("status") or ""),
             1 if entry.get("is_video") else 0,
             float(entry.get("completed_at") or 0),
             json.dumps(entry)))
        # Trim to the cap: drop the oldest past MAX_ENTRIES.
        conn.execute(
            "DELETE FROM downloads WHERE url IN (SELECT url FROM downloads"
            " ORDER BY completed_at DESC, url LIMIT -1 OFFSET ?)",
            (MAX_ENTRIES,))
        conn.commit()
    except Exception as e:
        logger.debug("Library record failed: %s", e)
    finally:
        _close(conn)

def entries(search="", limit=MAX_ENTRIES):
    """All entries as the same dicts the JSON file served, newest first.

    *search* filters on title or URL (case-insensitive substring). Returns
    None when the database cannot answer, so callers can fall back to the
    JSON file instead of showing an empty history.
    """
    conn = None
    try:
        conn = _connect()
        sql = ("SELECT payload, url, title, filepath, status, is_video,"
               " completed_at FROM downloads")
        params: list = []
        query = str(search or "").strip()
        if query:
            like = "%" + query.replace("\\", "\\\\").replace("%", r"\%") \
                              .replace("_", r"\_") + "%"
            sql += (" WHERE title LIKE ? ESCAPE '\\' OR url LIKE ?"
                    " ESCAPE '\\'")
            params = [like, like]
        sql += " ORDER BY completed_at DESC, url LIMIT ?"
        params.append(int(limit))
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_entry(r) for r in rows]
    except Exception as e:
        logger.debug("Library read failed: %s", e)
        return None
    finally:
        _close(conn)


def count() -> int:
    conn = None
    try:
        conn = _connect()
        return int(conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0])
    except Exception:
        return 0
    finally:
        _close(conn)


def prune_missing() -> int:
    """Drop rows whose file is gone from disk. Returns the count."""
    removed = 0
    conn = None
    try:
        conn = _connect()
        rows = conn.execute("SELECT url, filepath FROM downloads").fetchall()
        # Entries without a filepath are kept: nothing to check, same rule
        # the JSON prune applies.
        gone = [(u,) for u, p in rows if p and not os.path.exists(p)]
        if gone:
            conn.executemany("DELETE FROM downloads WHERE url = ?", gone)
            conn.commit()
            removed = len(gone)
    except Exception as e:
        logger.debug("Library prune failed: %s", e)
    finally:
        _close(conn)
    return removed


def clear() -> None:
    conn = None
    try:
        conn = _connect()
        conn.execute("DELETE FROM downloads")
        conn.commit()
    except Exception as e:
        logger.debug("Library clear failed: %s", e)
    finally:
        _close(conn)
    global _migration_checked
    _migration_checked = False


def ensure_migrated(records) -> int:
    """One-time import of the JSON history into an empty database.

    *records* is the JSON history list. The import runs once per process
    and only when the database is empty, so a long-lived library is never
    re-seeded from the shorter JSON file.
    """
    global _migration_checked
    with _migration_lock:
        if _migration_checked:
            return 0
        imported = 0
        try:
            if count() == 0:
                for entry in records or []:
                    if (isinstance(entry, dict)
                            and str(entry.get("url", "")).strip()):
                        record(entry)
                        imported += 1
            _migration_checked = True
            if imported:
                logger.debug("Imported %d history entries into the library",
                             imported)
        except Exception:
            return 0
        return imported
