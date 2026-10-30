"""
Database layer for FaceTrack.

`DatabaseManager` owns the SQLite connection details and exposes small,
well-named methods.  Every query is parameterized (no string formatting of
user input) to prevent SQL injection.

A new connection is opened for every operation.  SQLite connections are cheap,
and this makes the class safe to use from the webcam worker thread as well as
the Tkinter UI thread.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import config

log = logging.getLogger("facetrack.db")


class DatabaseError(Exception):
    """Raised when the database cannot be used; message is user-friendly."""


class DatabaseManager:
    def __init__(self, db_path: Path | str = config.DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    # ------------------------------------------------------------------ #
    # Connection helpers
    # ------------------------------------------------------------------ #
    @contextmanager
    def connect(self):
        """Yield a connection with foreign keys on; commit or roll back."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
        except sqlite3.Error as exc:
            log.exception("Cannot open database")
            raise DatabaseError(f"Cannot open the database file:\n{exc}") from exc
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        """Create tables (if missing) and insert default settings."""
        schema = config.SCHEMA_PATH.read_text(encoding="utf-8")
        with self.connect() as conn:
            conn.executescript(schema)
            for key, value in config.DEFAULT_SETTINGS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO settings (setting_key, setting_value) "
                    "VALUES (?, ?)", (key, value))
        log.info("Database ready at %s", self.db_path)

    def fetch_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]

    def fetch_one(self, sql: str, params: Iterable[Any] = ()) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
            return dict(row) if row else None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Run a write query; returns lastrowid (inserts) or rowcount."""
        with self.connect() as conn:
            cur = conn.execute(sql, tuple(params))
            return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") \
                else cur.rowcount

    # ------------------------------------------------------------------ #
    # Settings
    # ------------------------------------------------------------------ #
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.fetch_one(
            "SELECT setting_value FROM settings WHERE setting_key = ?", (key,))
        if row is None:
            return default if default is not None else config.DEFAULT_SETTINGS.get(key)
        return row["setting_value"]

    def get_setting_int(self, key: str) -> int:
        try:
            return int(float(self.get_setting(key)))
        except (TypeError, ValueError):
            return int(config.DEFAULT_SETTINGS[key])

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings (setting_key, setting_value) VALUES (?, ?) "
            "ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value",
            (key, str(value)))

    def get_all_settings(self) -> dict[str, str]:
        rows = self.fetch_all("SELECT setting_key, setting_value FROM settings")
        return {r["setting_key"]: r["setting_value"] for r in rows}

    # ------------------------------------------------------------------ #
    # Backup / restore
    # ------------------------------------------------------------------ #
    def backup(self, dest_dir: Path | str = config.BACKUPS_DIR) -> Path:
        """Create a consistent copy using SQLite's online backup API."""
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = dest_dir / f"facetrack_backup_{stamp}.db"
        n = 1
        while dest.exists():                      # never overwrite an existing backup
            dest = dest_dir / f"facetrack_backup_{stamp}_{n}.db"
            n += 1
        src = sqlite3.connect(self.db_path)
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        log.info("Database backed up to %s", dest)
        return dest

    def restore(self, backup_file: Path | str) -> Path:
        """
        Restore from a backup file safely:
          1. validate that the file is a FaceTrack SQLite database,
          2. take an automatic safety backup of the current database,
          3. copy the backup over the live database using the backup API.
        Returns the path of the safety backup.
        """
        backup_file = Path(backup_file)
        if not backup_file.is_file():
            raise DatabaseError("The selected backup file does not exist.")
        try:
            test = sqlite3.connect(f"file:{backup_file}?mode=ro", uri=True)
            tables = {r[0] for r in test.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            ok = test.execute("PRAGMA integrity_check").fetchone()[0]
            test.close()
        except sqlite3.Error as exc:
            raise DatabaseError(f"The selected file is not a valid database:\n{exc}")
        if not {"students", "attendance", "settings"} <= tables or ok != "ok":
            raise DatabaseError("The selected file is not a valid FaceTrack backup.")

        safety = self.backup()
        src = sqlite3.connect(backup_file)
        dst = sqlite3.connect(self.db_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        self.initialize()
        log.info("Database restored from %s (safety copy: %s)", backup_file, safety)
        return safety

    @staticmethod
    def today() -> str:
        return date.today().isoformat()
