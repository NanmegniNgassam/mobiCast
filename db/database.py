"""MobiCast — SQLite connection module and data access layer.

Schema
------
users        : application accounts
analyses     : one row per analysis run
source_files : files attached to an analysis (one row per source)
"""

import logging
import os
import sqlite3
from typing import Optional

from werkzeug.security import generate_password_hash

from config import DATABASE_PATH

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    UNIQUE NOT NULL,
    password_hash TEXT    NOT NULL,
    first_name    TEXT,
    last_name     TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_DDL_ANALYSES = """
CREATE TABLE IF NOT EXISTS analyses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    user_id        INTEGER REFERENCES users(id),
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    row_count      INTEGER,
    status         TEXT    DEFAULT 'running',
    sources_folder TEXT
)
"""

_DDL_SOURCE_FILES = """
CREATE TABLE IF NOT EXISTS source_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER REFERENCES analyses(id),
    source_type TEXT    NOT NULL,
    file_name   TEXT    NOT NULL,
    file_path   TEXT    NOT NULL
)
"""

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

# Columns added after the initial schema — applied automatically on startup.
_USER_MIGRATIONS = [
    ("first_name", "TEXT"),
    ("last_name",  "TEXT"),
]


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Add any columns missing from existing tables (forward-only migrations).

    Uses PRAGMA table_info so the ALTER TABLE only runs when the column does
    not yet exist — safe to call on every startup regardless of DB age.
    """
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(users)").fetchall()
    }
    for col, col_type in _USER_MIGRATIONS:
        if col not in existing:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
            logger.info("Schema migration applied: users.%s (%s)", col, col_type)


def get_connection() -> sqlite3.Connection:
    """Return a new SQLite connection with row_factory set to sqlite3.Row.

    Foreign key enforcement is enabled on every connection.
    The caller is responsible for closing the connection.
    """
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create all tables and seed a default admin user if none exist.

    Idempotent — safe to call on every application startup.
    Default credentials: admin / admin (should be changed after first login).
    """
    os.makedirs(os.path.dirname(os.path.abspath(DATABASE_PATH)), exist_ok=True)
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_DDL_USERS)
        cur.execute(_DDL_ANALYSES)
        cur.execute(_DDL_SOURCE_FILES)

        # Forward-only column migrations (safe on existing volumes).
        _apply_migrations(conn)

        # INSERT OR IGNORE is atomic: safe when multiple gunicorn workers call
        # init_db() concurrently on first startup.
        cur.execute(
            """
            INSERT OR IGNORE INTO users (username, password_hash, first_name, last_name)
            VALUES (?, ?, ?, ?)
            """,
            ("admin", generate_password_hash("admin"), "Administrateur", ""),
        )
        if cur.rowcount:
            logger.info("Default admin user created (username: admin, password: admin)")

        conn.commit()
        logger.info("Database ready at %s", DATABASE_PATH)
    except Exception:
        conn.rollback()
        logger.exception("Database initialisation failed")
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def get_user_by_id(user_id: int) -> Optional[sqlite3.Row]:
    """Return the user row for the given primary key, or None if not found."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()


def get_user_by_username(username: str) -> Optional[sqlite3.Row]:
    """Return the user row matching the given username, or None if not found."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    finally:
        conn.close()


def insert_user(
    username: str,
    password_hash: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> int:
    """Insert a new user and return the new row id.

    Args:
        username:      Unique login name.
        password_hash: Pre-hashed password string (werkzeug format).
        first_name:    Optional given name displayed in the UI.
        last_name:     Optional family name displayed in the UI.

    Returns:
        The auto-generated primary key of the inserted row.
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO users (username, password_hash, first_name, last_name)
            VALUES (?, ?, ?, ?)
            """,
            (username, password_hash, first_name, last_name),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------


def get_analysis_by_id(analysis_id: int) -> Optional[sqlite3.Row]:
    """Return the analysis row for the given primary key, or None."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM analyses WHERE id = ?", (analysis_id,)
        ).fetchone()
    finally:
        conn.close()


def get_all_analyses() -> list:
    """Return all analysis rows ordered by creation date, most recent first.

    Each row also exposes the author username via a JOIN on users.
    """
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT
                a.*,
                COALESCE(
                    NULLIF(TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')), ''),
                    u.username
                ) AS author
            FROM analyses a
            LEFT JOIN users u ON u.id = a.user_id
            ORDER BY a.created_at DESC
            """
        ).fetchall()
    finally:
        conn.close()


def insert_analysis(name: str, user_id: int) -> int:
    """Insert a new analysis record with status 'running' and return its id.

    Args:
        name:    Human-readable label chosen by the user.
        user_id: Primary key of the authenticated user who triggered the run.

    Returns:
        The auto-generated primary key of the new analysis row.
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO analyses (name, user_id) VALUES (?, ?)",
            (name, user_id),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_analysis_status(
    analysis_id: int,
    status: str,
    row_count: Optional[int] = None,
    sources_folder: Optional[str] = None,
) -> None:
    """Update the status (and optionally row_count / sources_folder) of an analysis.

    Args:
        analysis_id:    Primary key of the analysis to update.
        status:         One of 'running', 'done', 'error'.
        row_count:      Number of data rows processed (set when status='done').
        sources_folder: Absolute path to the persisted analysis folder.
    """
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE analyses
            SET status = ?,
                row_count = COALESCE(?, row_count),
                sources_folder = COALESCE(?, sources_folder)
            WHERE id = ?
            """,
            (status, row_count, sources_folder, analysis_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Source files
# ---------------------------------------------------------------------------


def get_source_files_by_analysis_id(analysis_id: int) -> list:
    """Return all source file rows associated with the given analysis.

    Args:
        analysis_id: Primary key of the parent analysis.

    Returns:
        List of source_files rows (may be empty if analysis not found).
    """
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM source_files WHERE analysis_id = ?", (analysis_id,)
        ).fetchall()
    finally:
        conn.close()


def insert_source_file(
    analysis_id: int, source_type: str, file_name: str, file_path: str
) -> int:
    """Insert a source file record and return its id.

    Args:
        analysis_id: Foreign key to the parent analysis.
        source_type: One of 'unesco', 'oecd', 'erasmus',
                     'default_oecd', 'default_erasmus'.
        file_name:   Original filename (for display).
        file_path:   Absolute path to the stored file.

    Returns:
        The auto-generated primary key of the new source_files row.
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO source_files (analysis_id, source_type, file_name, file_path)
            VALUES (?, ?, ?, ?)
            """,
            (analysis_id, source_type, file_name, file_path),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
