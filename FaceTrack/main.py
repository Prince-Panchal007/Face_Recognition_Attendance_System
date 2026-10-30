"""
FaceTrack – Smart Face Recognition Attendance Management System
Entry point.

Run with:
    python main.py
or double-click `run.bat` on Windows.
"""
from __future__ import annotations

import os
import sys
from tkinter import messagebox

# Ensure Matplotlib uses a writable cache folder on locked-down machines
os.environ.setdefault("MPLCONFIGDIR", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", ".mplcache"))

import config
from database.db_manager import DatabaseError, DatabaseManager
from ui.main_window import App


def main() -> int:
    config.ensure_directories()
    os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)
    log = config.setup_logging()
    log.info("Starting %s v%s", config.APP_FULL_NAME, config.APP_VERSION)

    try:
        db = DatabaseManager(config.DB_PATH)
    except DatabaseError as exc:
        log.critical("Database initialization failed: %s", exc)
        messagebox.showerror("FaceTrack – Database Error", str(exc))
        return 1

    app = App(db)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
