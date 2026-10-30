"""
FaceTrack – Smart Face Recognition Attendance Management System
Entry Point (`main.py`).

Run the application:
    python main.py

Run the built-in automated verification suite (database, LBPH vision & UI):
    python main.py --test
"""
from __future__ import annotations

import os
import sys
from tkinter import messagebox

# Ensure Matplotlib uses a writable local cache folder
os.environ.setdefault(
    "MPLCONFIGDIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", ".mplcache"),
)

import config


def run_app() -> int:
    from database import DatabaseError, DatabaseManager
    from ui import App

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


def run_tests() -> int:
    """Run all backend, LBPH recognition, report export, and UI smoke tests."""
    import sqlite3
    import tempfile
    import traceback
    from datetime import date, timedelta
    from pathlib import Path

    import cv2
    import numpy as np

    os.environ["FACETRACK_QUIET"] = "1"
    tmp = Path(tempfile.mkdtemp(prefix="facetrack_test_"))
    config.DATA_DIR = tmp
    config.FACES_DIR = tmp / "faces"
    config.PHOTOS_DIR = tmp / "photos"
    config.MODELS_DIR = tmp / "models"
    config.EXPORTS_DIR = tmp / "exports"
    config.BACKUPS_DIR = tmp / "backups"
    config.LOGS_DIR = tmp / "logs"
    config.DB_PATH = tmp / "test.db"
    config.MODEL_PATH = config.MODELS_DIR / "lbph_model.yml"
    config.LABELS_PATH = config.MODELS_DIR / "labels.json"
    config.LOG_PATH = config.LOGS_DIR / "test.log"
    config.ensure_directories()
    os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)
    config.setup_logging()

    from database import (
        AttendanceManager,
        DatabaseError,
        DatabaseManager,
        ReportManager,
        StudentManager,
        ValidationError,
        student_face_dir,
    )
    from ui import App
    from vision import (
        FaceDetector,
        FaceRecognizer,
        LiveRecognitionEngine,
        train_model,
    )

    results: list[tuple[str, bool, str]] = []

    def check(name: str, fn):
        try:
            fn()
            results.append((name, True, ""))
            print(f"  PASS  {name}")
        except Exception as exc:          # noqa: BLE001
            results.append((name, False, str(exc)))
            print(f"  FAIL  {name}: {exc}")
            traceback.print_exc()

    db = DatabaseManager(config.DB_PATH)
    sm = StudentManager(db)
    am = AttendanceManager(db)
    rm = ReportManager(db)

    def t_schema_and_settings():
        tables = {r["name"] for r in db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"students", "attendance", "settings"} <= tables
        db.set_setting("recognition_cooldown", 9)
        assert db.get_setting_int("recognition_cooldown") == 9
        db.set_setting("recognition_cooldown", 5)

    def t_student_crud_and_validation():
        for bad in ({}, {"student_id": "CS01", "full_name": "A",
                         "department": "CS", "course": "B.Tech"}):
            try:
                sm.validate(bad)
                raise AssertionError("Invalid student accepted")
            except ValidationError:
                pass
        pk = sm.add({"student_id": "CS101", "full_name": "Asha Verma",
                     "department": "Computer Science", "course": "B.Tech CSE",
                     "email": "asha@college.edu", "phone": "9876543210"})
        assert sm.get(pk)["full_name"] == "Asha Verma"
        sm.add({"student_id": "ME201", "full_name": "Rahul Singh",
                "department": "Mechanical", "course": "B.Tech ME"})
        assert sm.count() == 2

    def t_attendance_and_duplicates():
        pk = sm.get_by_roll("CS101")["id"]
        assert am.mark(pk, "Face", 42.5).status == "marked"
        assert am.mark(pk, "Face", 40.0).status == "duplicate"
        assert am.mark(pk, "Manual").status == "duplicate"
        try:
            db.execute(
                "INSERT INTO attendance (student_id, attendance_date, status, "
                "recognition_method) VALUES (?, ?, 'Present', 'Manual')",
                (pk, date.today().isoformat()))
            raise AssertionError("UNIQUE constraint missing")
        except sqlite3.IntegrityError:
            pass

    def t_reports_and_exports():
        rahul = sm.get_by_roll("ME201")["id"]
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        db.execute("UPDATE students SET created_at = ?",
                   ((date.today() - timedelta(days=10)).isoformat() + " 09:00:00",))
        am.mark(rahul, "Manual", day=yesterday, check_in="09:10:00")
        start = (date.today() - timedelta(days=6)).isoformat()
        end = date.today().isoformat()
        ov = rm.overall(start, end)
        assert ov["sessions"] == 2 and ov["percentage"] == 50.0
        csv_path = am.export_csv(am.list_records(), config.EXPORTS_DIR / "att.csv")
        pdf_path = rm.export_pdf(config.EXPORTS_DIR / "report.pdf", start, end)
        assert csv_path.exists() and pdf_path.exists() and pdf_path.read_bytes()[:4] == b"%PDF"

    def t_backup_and_restore():
        b = db.backup()
        pk = sm.add({"student_id": "TMP1", "full_name": "Temp Person",
                     "department": "Civil", "course": "X"})
        db.restore(b)
        assert sm.get(pk) is None

    def t_vision_and_lbph():
        det = FaceDetector()
        assert det.detect(np.zeros((480, 640), np.uint8)) == []
        pk1 = sm.get_by_roll("CS101")["id"]
        pk2 = sm.get_by_roll("ME201")["id"]
        rng = np.random.default_rng(42)
        base1 = rng.integers(40, 200, size=config.FACE_SIZE, dtype=np.uint8)
        base2 = rng.integers(40, 200, size=config.FACE_SIZE, dtype=np.uint8)
        for pk, base in ((pk1, base1), (pk2, base2)):
            d = student_face_dir(pk)
            d.mkdir(parents=True, exist_ok=True)
            for k in range(8):
                noise = rng.integers(-5, 6, size=config.FACE_SIZE, dtype=np.int16)
                sample = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
                cv2.imwrite(str(d / f"{k:02d}.png"), sample)
            sm.mark_enrolled(pk, None)
        res = train_model(db)
        assert res.success and res.students == 2
        rec = FaceRecognizer(config.MODEL_PATH, config.LABELS_PATH)
        assert rec.load()
        label, dist = rec.predict(base1)
        assert label == pk1 and dist < 20.0

    def t_ui_smoke():
        app = App(db)
        pages = ["dashboard", "students", "live", "records", "reports", "settings"]
        visited = []

        def step(i: int = 0):
            if i < len(pages):
                app.show_page(pages[i])
                app.update_idletasks()
                visited.append(pages[i])
                app.after(150, lambda: step(i + 1))
            else:
                app.after(200, app.on_close)

        app.after(400, step)
        app.mainloop()
        assert visited == pages

    check("schema_and_settings", t_schema_and_settings)
    check("student_crud_and_validation", t_student_crud_and_validation)
    check("attendance_and_duplicates", t_attendance_and_duplicates)
    check("reports_and_exports", t_reports_and_exports)
    check("backup_and_restore", t_backup_and_restore)
    check("vision_and_lbph", t_vision_and_lbph)
    check("ui_smoke", t_ui_smoke)

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(run_tests())
    sys.exit(run_app())
