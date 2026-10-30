"""
End-to-end UI integration test for FaceTrack.

Starts the real CustomTkinter application against an isolated temporary SQLite
database, switches through every page, registers students, marks attendance,
switches report tabs, saves settings, and closes cleanly.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["FACETRACK_QUIET"] = "1"
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "mpl_facetrack"))

import config  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="facetrack_ui_test_"))
config.DATA_DIR = TMP
config.FACES_DIR = TMP / "faces"
config.PHOTOS_DIR = TMP / "photos"
config.MODELS_DIR = TMP / "models"
config.EXPORTS_DIR = TMP / "exports"
config.BACKUPS_DIR = TMP / "backups"
config.LOGS_DIR = TMP / "logs"
config.DB_PATH = TMP / "ui_test.db"
config.MODEL_PATH = config.MODELS_DIR / "lbph_model.yml"
config.LABELS_PATH = config.MODELS_DIR / "labels.json"
config.LOG_PATH = config.LOGS_DIR / "ui_test.log"
config.ensure_directories()
config.setup_logging()

from database.db_manager import DatabaseManager  # noqa: E402
from ui.main_window import App  # noqa: E402


def run_ui_smoke():
    db = DatabaseManager(config.DB_PATH)
    app = App(db)

    steps = []

    def step1():
        # Empty state on dashboard
        assert app.current == "dashboard"
        steps.append("dashboard_empty")
        # Add two students and one attendance record
        pk1 = app.students.add({
            "student_id": "CS2026A",
            "full_name": "Ananya Sharma",
            "department": "Computer Science",
            "course": "B.Tech CSE 4th Year",
            "email": "ananya@college.edu",
            "phone": "9876501234",
        })
        pk2 = app.students.add({
            "student_id": "EC2026B",
            "full_name": "Vikram Rao",
            "department": "Electronics",
            "course": "B.Tech ECE 3rd Year",
        })
        res = app.attendance.mark(pk1, method="Manual")
        assert res.status == "marked"
        app.show_page("dashboard")
        app.update_idletasks()
        steps.append("dashboard_populated")
        app.after(150, step2)

    def step2():
        app.show_page("students")
        app.update_idletasks()
        sp = app.pages["students"]
        assert len(sp.table.rows) == 2
        first_iid = next(iter(sp.table.rows))
        sp.table.tree.selection_set(first_iid)
        sp._on_select(sp.table.rows[first_iid])
        steps.append("students_page")
        app.after(150, step3)

    def step3():
        app.show_page("live")
        app.update_idletasks()
        steps.append("live_page")
        app.after(150, step4)

    def step4():
        app.show_page("records")
        app.update_idletasks()
        rp = app.pages["records"]
        assert len(rp.current_rows) == 2  # 1 Present + 1 unmarked Absent
        steps.append("records_page")
        app.after(150, step5)

    def step5():
        app.show_page("reports")
        app.update_idletasks()
        rep = app.pages["reports"]
        for kind in ("daily", "weekly", "monthly", "student", "department"):
            rep.switch_tab(kind)
            app.update_idletasks()
        steps.append("reports_page")
        app.after(150, step6)

    def step6():
        app.show_page("settings")
        app.update_idletasks()
        st = app.pages["settings"]
        st.save_settings()
        steps.append("settings_page")
        app.after(150, finish)

    def finish():
        app.on_close()

    app.after(200, step1)
    app.mainloop()

    expected = [
        "dashboard_empty", "dashboard_populated", "students_page",
        "live_page", "records_page", "reports_page", "settings_page",
    ]
    assert steps == expected, f"Expected {expected}, got {steps}"
    print("UI integration test passed:", " -> ".join(steps))


if __name__ == "__main__":
    run_ui_smoke()
