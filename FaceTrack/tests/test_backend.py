"""
Backend tests for FaceTrack (no GUI, no webcam needed).

Run:  python tests/test_backend.py
Optionally pass a folder of Olivetti faces (see test_recognition_with_real_faces)
via the environment variable FACETRACK_OLIVETTI=<data_home> to test LBPH
recognition accuracy on real face photographs.

All tests run against a temporary copy of the data folders, so your real
database and face samples are never touched.
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["FACETRACK_QUIET"] = "1"

import config  # noqa: E402

# ---- redirect every data path into a temp folder ------------------------- #
TMP = Path(tempfile.mkdtemp(prefix="facetrack_test_"))
config.DATA_DIR = TMP
config.FACES_DIR = TMP / "faces"
config.PHOTOS_DIR = TMP / "photos"
config.MODELS_DIR = TMP / "models"
config.EXPORTS_DIR = TMP / "exports"
config.BACKUPS_DIR = TMP / "backups"
config.LOGS_DIR = TMP / "logs"
config.DB_PATH = TMP / "test.db"
config.MODEL_PATH = config.MODELS_DIR / "lbph_model.yml"
config.LABELS_PATH = config.MODELS_DIR / "labels.json"
config.LOG_PATH = config.LOGS_DIR / "test.log"
config.ensure_directories()
config.setup_logging()

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from database.db_manager import DatabaseManager, DatabaseError  # noqa: E402
from modules.attendance_manager import AttendanceManager  # noqa: E402
from modules.report_manager import ReportManager  # noqa: E402
from modules.student_manager import StudentManager, ValidationError  # noqa: E402
from recognition.face_detector import FaceDetector, preprocess_face  # noqa: E402
from recognition.face_recognizer import FaceRecognizer  # noqa: E402
from recognition.live_engine import LiveRecognitionEngine  # noqa: E402
from recognition import trainer  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def test(fn):
    try:
        fn()
        RESULTS.append((fn.__name__, True, ""))
        print(f"  PASS  {fn.__name__}")
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((fn.__name__, False, str(exc)))
        print(f"  FAIL  {fn.__name__}: {exc}")
        traceback.print_exc()
    return fn


db = DatabaseManager(config.DB_PATH)
sm = StudentManager(db)
am = AttendanceManager(db)
rm = ReportManager(db)


@test
def test_schema_created():
    tables = {r["name"] for r in db.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"students", "attendance", "settings"} <= tables, tables
    assert db.get_setting("recognition_threshold") == config.DEFAULT_SETTINGS["recognition_threshold"]


@test
def test_settings_roundtrip():
    db.set_setting("recognition_cooldown", 9)
    assert db.get_setting_int("recognition_cooldown") == 9
    db.set_setting("recognition_cooldown", 5)


@test
def test_student_validation():
    bad = [
        {},
        {"student_id": "CS01", "full_name": "A", "department": "X", "course": "Y"},
        {"student_id": "CS01", "full_name": "Asha", "department": "", "course": "Y"},
        {"student_id": "CS01", "full_name": "Asha", "department": "CS", "course": "Y", "email": "bad"},
        {"student_id": "CS 01!", "full_name": "Asha", "department": "CS", "course": "Y"},
    ]
    for b in bad:
        try:
            sm.validate(b)
        except ValidationError:
            continue
        raise AssertionError(f"accepted invalid data {b}")


@test
def test_student_crud_and_unique():
    pk = sm.add({"student_id": "CS101", "full_name": "Asha Verma", "department": "Computer Science",
                 "course": "B.Tech CSE 3rd Year", "email": "asha@college.edu", "phone": "9876543210"})
    assert sm.get(pk)["full_name"] == "Asha Verma"
    try:
        sm.add({"student_id": "CS101", "full_name": "Dup Name", "department": "Civil", "course": "X"})
        raise AssertionError("duplicate student_id accepted")
    except ValidationError:
        pass
    sm.update(pk, {"student_id": "CS101", "full_name": "Asha  K Verma", "department": "Computer Science",
                   "course": "B.Tech CSE 3rd Year"})
    assert sm.get(pk)["full_name"] == "Asha K Verma"
    assert len(sm.list("asha")) == 1 and len(sm.list("", "Civil")) == 0
    sm.add({"student_id": "ME201", "full_name": "Rahul Singh", "department": "Mechanical", "course": "B.Tech ME"})
    assert sm.count() == 2


@test
def test_attendance_duplicate_prevention():
    pk = sm.get_by_roll("CS101")["id"]
    r1 = am.mark(pk, "Face", 42.5)
    assert r1.status == "marked", r1.message
    r2 = am.mark(pk, "Face", 40.0)
    assert r2.status == "duplicate", r2.message
    r3 = am.mark(pk, "Manual")
    assert r3.status == "duplicate"
    n = db.fetch_one("SELECT COUNT(*) n FROM attendance WHERE student_id=?", (pk,))["n"]
    assert n == 1, n
    # The database itself must also refuse a duplicate (UNIQUE constraint)
    import sqlite3
    try:
        db.execute("INSERT INTO attendance (student_id, attendance_date, status, recognition_method) "
                   "VALUES (?, ?, 'Present', 'Manual')", (pk, date.today().isoformat()))
        raise AssertionError("UNIQUE constraint missing")
    except sqlite3.IntegrityError:
        pass


@test
def test_attendance_queries_update_delete():
    rahul = sm.get_by_roll("ME201")["id"]
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    db.execute("UPDATE students SET created_at = ?", ((date.today() - timedelta(days=10)).isoformat() + " 09:00:00",))
    r = am.mark(rahul, "Manual", day=yesterday, check_in="09:10:00")
    assert r.status == "marked"
    today = date.today().isoformat()
    rows = am.list_records(date_from=today, date_to=today, include_unmarked=True)
    assert {x["status"] for x in rows} == {"Present", "Absent"}, rows
    assert any(x["recognition_method"] == "Not marked" for x in rows)
    am.update_record(r.record["id"], "Late", "09:40:00")
    assert db.fetch_one("SELECT status FROM attendance WHERE id=?", (r.record["id"],))["status"] == "Late"
    s = am.today_summary()
    assert s["total"] == 2 and s["present"] == 1 and s["absent"] == 1 and s["percentage"] == 50.0, s
    out = am.export_csv(am.list_records(), config.EXPORTS_DIR / "sub" / "att.csv")
    assert out.exists() and len(out.read_text(encoding="utf-8-sig").splitlines()) == 3
    tmp = am.mark(rahul, "Manual", day="2020-01-01")
    am.delete_record(tmp.record["id"])
    assert am.get_record(rahul, "2020-01-01") is None


@test
def test_late_rule():
    db.set_setting("late_after", "09:30")
    assert am._auto_status("09:45:00") == "Late"
    assert am._auto_status("09:00:00") == "Present"
    db.set_setting("late_after", "")
    assert am._auto_status("23:00:00") == "Present"


@test
def test_reports():
    start = (date.today() - timedelta(days=6)).isoformat()
    end = date.today().isoformat()
    ov = rm.overall(start, end)
    assert ov["sessions"] == 2 and ov["expected"] == 4 and ov["attended"] == 2, ov
    assert ov["percentage"] == 50.0
    assert len(rm.last_n_days_trend(7)) == 7
    sw = rm.student_wise(start, end)
    assert {r["roll"]: r["percentage"] for r in sw} == {"CS101": 50.0, "ME201": 50.0}, sw
    dw = rm.department_wise(start, end)
    assert len(dw) == 2
    for kind in ("daily", "weekly", "monthly", "student", "department"):
        rows = rm.build(kind, start, end)
        p = rm.export_csv(kind, rows, config.EXPORTS_DIR / f"{kind}.csv", start, end)
        assert p.exists()
    pdf = rm.export_pdf(config.EXPORTS_DIR / "report.pdf", start, end)
    assert pdf.exists() and pdf.read_bytes()[:4] == b"%PDF"
    empty = rm.overall("2001-01-01", "2001-01-31")
    assert empty["sessions"] == 0 and empty["percentage"] == 0.0


@test
def test_backup_and_restore():
    b = db.backup()
    assert b.exists()
    pk = sm.add({"student_id": "TMP1", "full_name": "Temp Person", "department": "Civil", "course": "X"})
    db.restore(b)
    assert sm.get(pk) is None, "restore did not roll back"
    bogus = TMP / "bogus.db"
    bogus.write_text("not a database")
    try:
        db.restore(bogus)
        raise AssertionError("invalid backup accepted")
    except DatabaseError:
        pass


@test
def test_detector_loads_and_handles_blank():
    det = FaceDetector()
    assert det.detect(np.zeros((480, 640), np.uint8)) == []


@test
def test_recognizer_missing_and_corrupt_model():
    r = FaceRecognizer(config.MODEL_PATH, config.LABELS_PATH)
    if config.MODEL_PATH.exists():
        config.MODEL_PATH.unlink()
    assert r.load() is False and r.error
    config.MODEL_PATH.write_text("garbage")
    assert r.load() is False and "corrupt" in r.error.lower()
    config.MODEL_PATH.unlink()


@test
def test_train_without_samples_clears_model():
    res = trainer.train_model(db)
    assert res.success is False and not config.MODEL_PATH.exists()


@test
def test_recognition_with_real_faces():
    """
    Uses the Olivetti face dataset (40 people x 10 photos) when available:
    first 7 photos of 20 people are "enrolled"; the remaining 3 photos are
    used as live queries. The other 20 people act as UNKNOWN strangers.
    """
    home = os.environ.get("FACETRACK_OLIVETTI")
    if not home:
        print("        (skipped real-face accuracy test – FACETRACK_OLIVETTI not set)")
        return
    from sklearn.datasets import fetch_olivetti_faces
    data = fetch_olivetti_faces(data_home=home, download_if_missing=False)
    imgs = (data.images * 255).astype(np.uint8)
    targets = data.target

    def prep(img):
        return cv2.equalizeHist(cv2.resize(img, config.FACE_SIZE))

    pks = {}
    for person in range(20):
        pk = sm.add({"student_id": f"OL{person:02d}", "full_name": f"Olivetti Person {chr(65 + person % 26)}",
                     "department": "Other", "course": "Test"})
        pks[person] = pk
        d = trainer.student_face_dir(pk)
        d.mkdir(parents=True, exist_ok=True)
        for k, idx in enumerate(np.where(targets == person)[0][:7]):
            cv2.imwrite(str(d / f"{k:02d}.png"), prep(imgs[idx]))
        sm.mark_enrolled(pk, None)
    res = trainer.train_model(db)
    assert res.success and res.students == 20 and res.samples == 140, res
    rec = FaceRecognizer(config.MODEL_PATH, config.LABELS_PATH)
    assert rec.load()

    known_d, correct, stranger_d = [], 0, []
    for person in range(20):
        for idx in np.where(targets == person)[0][7:]:
            label, dist = rec.predict(prep(imgs[idx]))
            known_d.append(dist)
            correct += label == pks[person]
    for person in range(20, 40):
        for idx in np.where(targets == person)[0]:
            stranger_d.append(rec.predict(prep(imgs[idx]))[1])
    thr = float(config.DEFAULT_SETTINGS["recognition_threshold"])
    acc = correct / len(known_d)
    tar = np.mean(np.array(known_d) <= thr)
    far = np.mean(np.array(stranger_d) <= thr)
    print(f"        identification accuracy (nearest match): {acc:.1%}")
    print(f"        known distance  median {np.median(known_d):.1f}  (min {min(known_d):.1f}, max {max(known_d):.1f})")
    print(f"        stranger distance median {np.median(stranger_d):.1f}  (min {min(stranger_d):.1f})")
    print(f"        at threshold {thr:.0f}: accepted known {tar:.1%}, accepted strangers {far:.1%}")
    for t in (40, 45, 50, 55, 60, 65, 70):
        print(f"          threshold {t}: known accepted {np.mean(np.array(known_d) <= t):.1%}"
              f"  strangers accepted {np.mean(np.array(stranger_d) <= t):.1%}")
    assert acc >= 0.85, acc

    # End-to-end engine logic: recognized face -> attendance row, once only.
    class FakeDet:
        def detect(self, gray, min_size=None):
            return [(0, 0, gray.shape[1], gray.shape[0])]
    eng = LiveRecognitionEngine(FakeDet(), rec, am)
    db.set_setting("recognition_threshold", 200)        # accept the test image
    db.set_setting("confirm_frames", 3)
    db.set_setting("recognition_cooldown", 0)
    eng.reload()
    query = cv2.cvtColor(cv2.resize(imgs[np.where(targets == 0)[0][8]], (200, 200)), cv2.COLOR_GRAY2BGR)
    for _ in range(6):
        eng.process(query.copy())
    events = []
    while not eng.events.empty():
        events.append(eng.events.get())
    assert events and events[0][0] == "marked", events
    assert all(e[0] == "duplicate" for e in events[1:]), events
    n = db.fetch_one("SELECT COUNT(*) n FROM attendance WHERE student_id=?", (pks[0],))["n"]
    assert n == 1, n
    # Low-confidence match must NOT be marked.
    db.set_setting("recognition_threshold", 1)
    eng.reload()
    q2 = cv2.cvtColor(cv2.resize(imgs[np.where(targets == 1)[0][8]], (200, 200)), cv2.COLOR_GRAY2BGR)
    for _ in range(6):
        eng.process(q2.copy())
    assert eng.events.empty()
    assert am.get_record(pks[1], date.today().isoformat()) is None
    db.set_setting("recognition_threshold", config.DEFAULT_SETTINGS["recognition_threshold"])


@test
def test_delete_student_cascades():
    pk = sm.get_by_roll("CS101")["id"]
    sm.delete(pk)
    assert sm.get(pk) is None
    assert db.fetch_one("SELECT COUNT(*) n FROM attendance WHERE student_id=?", (pk,))["n"] == 0


if __name__ == "__main__":
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} tests passed. Temp data: {TMP}")
    sys.exit(1 if failed else 0)
