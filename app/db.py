import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "smart_lab.sqlite"


def get_db(db_path=None):
    target = Path(db_path) if db_path else DB_PATH
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def log_activity(conn, actor_id, action, entity_type, entity_id=None, details=None):
    conn.execute(
        """
        INSERT INTO activity_logs (actor_id, action, entity_type, entity_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            actor_id,
            action,
            entity_type,
            entity_id,
            details,
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
