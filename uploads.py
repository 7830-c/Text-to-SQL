import time
import uuid
import sqlite3
from pathlib import Path

import config


def save_upload(file_bytes):
    """Check an uploaded file and store it. Returns (db_id, error_message)."""
    if len(file_bytes) > config.MAX_UPLOAD_MB * 1024 * 1024:
        return None, f"File is larger than {config.MAX_UPLOAD_MB} MB."
    if not file_bytes.startswith(b"SQLite format 3\x00"):
        return None, "This does not look like a SQLite database file."

    folder = Path(config.UPLOAD_DIR)
    folder.mkdir(exist_ok=True)
    db_id = "upload_" + uuid.uuid4().hex[:12]
    path = folder / f"{db_id}.sqlite"
    path.write_bytes(file_bytes)

    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        n = conn.execute("SELECT COUNT(*) FROM sqlite_master "
                         "WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
        conn.close()
    except sqlite3.Error:
        path.unlink(missing_ok=True)
        return None, "Could not open this file as a SQLite database."
    if n == 0:
        path.unlink(missing_ok=True)
        return None, "The database has no tables."
    return db_id, None


def delete_upload(db_id):
    if db_id and db_id.startswith("upload_"):
        for ext in ("", "-wal", "-shm"):
            (Path(config.UPLOAD_DIR) / f"{db_id}.sqlite{ext}").unlink(missing_ok=True)


def cleanup_old_uploads():
    """Streamlit has no reliable 'session ended' signal, so old files are removed by age instead."""
    folder = Path(config.UPLOAD_DIR)
    if not folder.exists():
        return
    cutoff = time.time() - config.UPLOAD_TTL_MIN * 60
    for f in folder.glob("upload_*.sqlite"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass