"""
FaceTrack – Database & Business Logic Layer (`database.py`).

Contains:
  1. SQLite Schema (`SCHEMA_SQL`) with primary/foreign keys, indexes, and the
     `UNIQUE(student_id, attendance_date)` duplicate-prevention constraint.
  2. `DatabaseManager`  – thread-safe parameterized SQLite queries, settings,
                          online backup, and integrity-checked restore.
  3. `StudentManager`   – input regex validation, student CRUD, sample cleanup.
  4. `AttendanceManager`– automatic & manual attendance marking, duplicate
                          prevention, record correction, and CSV export.
  5. `ReportManager`    – daily, weekly, monthly, student-wise, and
                          department-wise analytics, CSV export, and PDF report.
"""
from __future__ import annotations

import csv
import logging
import re
import shutil
import sqlite3
import tempfile
from collections import OrderedDict, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

import config

log = logging.getLogger("facetrack.db")

# =========================================================================== #
# 1. SQLite Relational Schema
# =========================================================================== #
SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS students (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    TEXT    NOT NULL UNIQUE,
    full_name     TEXT    NOT NULL,
    department    TEXT    NOT NULL,
    course        TEXT    NOT NULL,
    email         TEXT,
    phone         TEXT,
    photo_path    TEXT,
    face_enrolled INTEGER NOT NULL DEFAULT 0 CHECK (face_enrolled IN (0, 1)),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_students_department ON students(department);
CREATE INDEX IF NOT EXISTS idx_students_name ON students(full_name);

CREATE TABLE IF NOT EXISTS attendance (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id         INTEGER NOT NULL,
    attendance_date    TEXT    NOT NULL,
    check_in_time      TEXT,
    status             TEXT    NOT NULL DEFAULT 'Present'
                               CHECK (status IN ('Present', 'Late', 'Absent')),
    recognition_method TEXT    NOT NULL DEFAULT 'Face'
                               CHECK (recognition_method IN ('Face', 'Manual')),
    confidence         REAL,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    UNIQUE (student_id, attendance_date)
);

CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(attendance_date);
CREATE INDEX IF NOT EXISTS idx_attendance_student ON attendance(student_id);

CREATE TABLE IF NOT EXISTS settings (
    setting_key   TEXT PRIMARY KEY,
    setting_value TEXT
);
"""


def student_face_dir(student_pk: int) -> Path:
    return config.FACES_DIR / str(student_pk)


def count_samples(student_pk: int) -> int:
    d = student_face_dir(student_pk)
    return len(list(d.glob("*.png"))) if d.is_dir() else 0


# =========================================================================== #
# 2. DatabaseManager
# =========================================================================== #
class DatabaseError(Exception):
    """Raised when the SQLite database cannot be opened or restored."""


class DatabaseManager:
    def __init__(self, db_path: Path | str = config.DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self):
        """Yield a short-lived connection with foreign keys enabled."""
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
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
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
        with self.connect() as conn:
            cur = conn.execute(sql, tuple(params))
            return (cur.lastrowid if sql.lstrip().upper().startswith("INSERT")
                    else cur.rowcount)

    # ---- Settings -------------------------------------------------------- #
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

    # ---- Online Backup & Safe Restore ----------------------------------- #
    def backup(self, dest_dir: Path | str = config.BACKUPS_DIR) -> Path:
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = dest_dir / f"facetrack_backup_{stamp}.db"
        n = 1
        while dest.exists():
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


# =========================================================================== #
# 3. StudentManager
# =========================================================================== #
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-]{6,18}$")
ROLL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_/]{0,29}$")


class ValidationError(Exception):
    """Raised when student form fields fail validation."""


class StudentManager:
    def __init__(self, db: DatabaseManager):
        self.db = db

    @staticmethod
    def validate(data: dict) -> dict:
        clean = {k: (data.get(k) or "").strip() for k in
                 ("student_id", "full_name", "department", "course", "email", "phone")}
        if not clean["student_id"]:
            raise ValidationError("Student ID / Roll Number is required.")
        if not ROLL_RE.match(clean["student_id"]):
            raise ValidationError("Student ID may contain letters, digits, '-', '_' or '/' "
                                  "(max 30 characters).")
        if len(clean["full_name"]) < 2:
            raise ValidationError("Full Name must contain at least 2 characters.")
        if not re.match(r"^[A-Za-z][A-Za-z .'\-]*$", clean["full_name"]):
            raise ValidationError("Full Name may contain only letters, spaces, '.', ''' and '-'.")
        if not clean["department"]:
            raise ValidationError("Please select a Department.")
        if not clean["course"]:
            raise ValidationError("Course / Class is required.")
        if clean["email"] and not EMAIL_RE.match(clean["email"]):
            raise ValidationError("Email address is not valid.")
        if clean["phone"] and not PHONE_RE.match(clean["phone"]):
            raise ValidationError("Phone number is not valid (digits, spaces, '-' and '+').")
        clean["full_name"] = " ".join(clean["full_name"].split())
        return clean

    def add(self, data: dict) -> int:
        c = self.validate(data)
        try:
            return self.db.execute(
                "INSERT INTO students (student_id, full_name, department, course, email, phone) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (c["student_id"], c["full_name"], c["department"], c["course"],
                 c["email"] or None, c["phone"] or None))
        except sqlite3.IntegrityError:
            raise ValidationError(f"A student with ID '{c['student_id']}' already exists.")

    def update(self, pk: int, data: dict) -> None:
        c = self.validate(data)
        try:
            self.db.execute(
                "UPDATE students SET student_id=?, full_name=?, department=?, course=?, "
                "email=?, phone=? WHERE id=?",
                (c["student_id"], c["full_name"], c["department"], c["course"],
                 c["email"] or None, c["phone"] or None, pk))
        except sqlite3.IntegrityError:
            raise ValidationError(f"Another student already uses ID '{c['student_id']}'.")

    def delete(self, pk: int) -> bool:
        student = self.get(pk)
        if not student:
            return False
        had_faces = bool(student["face_enrolled"])
        self.db.execute("DELETE FROM students WHERE id = ?", (pk,))
        shutil.rmtree(student_face_dir(pk), ignore_errors=True)
        photo = config.PHOTOS_DIR / f"{pk}.jpg"
        if photo.exists():
            photo.unlink()
        log.info("Deleted student %s (%s)", student["student_id"], student["full_name"])
        return had_faces

    def get(self, pk: int) -> Optional[dict]:
        return self.db.fetch_one("SELECT * FROM students WHERE id = ?", (pk,))

    def get_by_roll(self, roll: str) -> Optional[dict]:
        return self.db.fetch_one("SELECT * FROM students WHERE student_id = ?", (roll,))

    def list(self, search: str = "", department: str = "") -> list[dict]:
        sql = "SELECT * FROM students WHERE 1=1"
        params: list = []
        if search:
            sql += " AND (student_id LIKE ? OR full_name LIKE ? OR course LIKE ?)"
            like = f"%{search.strip()}%"
            params += [like, like, like]
        if department and department != "All Departments":
            sql += " AND department = ?"
            params.append(department)
        sql += " ORDER BY full_name COLLATE NOCASE"
        return self.db.fetch_all(sql, params)

    def count(self) -> int:
        return self.db.fetch_one("SELECT COUNT(*) AS n FROM students")["n"]

    def recent(self, limit: int = 6) -> list[dict]:
        return self.db.fetch_all(
            "SELECT * FROM students ORDER BY created_at DESC, id DESC LIMIT ?", (limit,))

    def departments(self) -> list[str]:
        used = [r["department"] for r in self.db.fetch_all(
            "SELECT DISTINCT department FROM students ORDER BY department")]
        out = list(config.DEPARTMENTS)
        for d in used:
            if d not in out:
                out.append(d)
        return out

    def mark_enrolled(self, pk: int, photo_path: Optional[str]) -> None:
        enrolled = 1 if count_samples(pk) > 0 else 0
        self.db.execute("UPDATE students SET face_enrolled=?, photo_path=? WHERE id=?",
                        (enrolled, photo_path, pk))

    @staticmethod
    def sample_count(pk: int) -> int:
        return count_samples(pk)


# =========================================================================== #
# 4. AttendanceManager
# =========================================================================== #
STATUSES = ("Present", "Late", "Absent")
METHODS = ("Face", "Manual")


@dataclass
class MarkResult:
    status: str             # "marked" | "duplicate" | "error"
    message: str
    record: Optional[dict] = None


class AttendanceManager:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def _auto_status(self, check_in: str) -> str:
        late_after = (self.db.get_setting("late_after") or "").strip()
        if late_after:
            try:
                limit = datetime.strptime(late_after, "%H:%M").time()
                if datetime.strptime(check_in, "%H:%M:%S").time() > limit:
                    return "Late"
            except ValueError:
                pass
        return "Present"

    def get_record(self, student_pk: int, day: str) -> Optional[dict]:
        return self.db.fetch_one(
            "SELECT * FROM attendance WHERE student_id = ? AND attendance_date = ?",
            (student_pk, day))

    def mark(self, student_pk: int, method: str = "Face",
             confidence: Optional[float] = None, status: Optional[str] = None,
             day: Optional[str] = None, check_in: Optional[str] = None) -> MarkResult:
        day = day or date.today().isoformat()
        check_in = check_in or datetime.now().strftime("%H:%M:%S")
        student = self.db.fetch_one("SELECT * FROM students WHERE id = ?", (student_pk,))
        if not student:
            return MarkResult("error", "Student not found in the database.")
        existing = self.get_record(student_pk, day)
        if existing:
            return MarkResult(
                "duplicate",
                f"{student['full_name']} is already marked {existing['status']} "
                f"for {day} at {existing['check_in_time'] or '—'}.", existing)
        status = status or self._auto_status(check_in)
        if status not in STATUSES or method not in METHODS:
            return MarkResult("error", "Invalid status or method.")
        try:
            rid = self.db.execute(
                "INSERT INTO attendance (student_id, attendance_date, check_in_time, status, "
                "recognition_method, confidence) VALUES (?, ?, ?, ?, ?, ?)",
                (student_pk, day, check_in if status != "Absent" else None, status, method,
                 round(confidence, 2) if confidence is not None else None))
        except sqlite3.IntegrityError:
            return MarkResult("duplicate", f"{student['full_name']} is already marked for {day}.")
        record = self.db.fetch_one("SELECT * FROM attendance WHERE id = ?", (rid,))
        record.update(full_name=student["full_name"], roll=student["student_id"],
                      department=student["department"])
        log.info("Attendance: %s %s %s via %s", student["student_id"], day, status, method)
        return MarkResult("marked", f"{student['full_name']} marked {status} at {check_in}.",
                          record)

    def update_record(self, record_id: int, status: str, check_in: Optional[str],
                      day: Optional[str] = None) -> None:
        if status not in STATUSES:
            raise ValueError("Invalid status")
        if check_in:
            datetime.strptime(check_in, "%H:%M:%S")
        if day:
            datetime.strptime(day, "%Y-%m-%d")
        rec = self.db.fetch_one("SELECT * FROM attendance WHERE id = ?", (record_id,))
        if not rec:
            raise ValueError("Record not found")
        try:
            self.db.execute(
                "UPDATE attendance SET status=?, check_in_time=?, attendance_date=? WHERE id=?",
                (status, check_in if status != "Absent" else None,
                 day or rec["attendance_date"], record_id))
        except sqlite3.IntegrityError:
            raise ValueError("This student already has a record on that date.")

    def delete_record(self, record_id: int) -> None:
        self.db.execute("DELETE FROM attendance WHERE id = ?", (record_id,))

    def list_records(self, search: str = "", date_from: str = "", date_to: str = "",
                     department: str = "", status: str = "",
                     student_pk: Optional[int] = None,
                     include_unmarked: bool = False) -> list[dict]:
        sql = ("SELECT a.id, s.id AS student_pk, s.student_id AS roll, s.full_name, "
               "s.department, s.course, a.attendance_date, a.check_in_time, a.status, "
               "a.recognition_method, a.confidence "
               "FROM attendance a JOIN students s ON s.id = a.student_id WHERE 1=1")
        params: list = []
        if search:
            sql += " AND (s.full_name LIKE ? OR s.student_id LIKE ?)"
            params += [f"%{search.strip()}%"] * 2
        if date_from:
            sql += " AND a.attendance_date >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND a.attendance_date <= ?"
            params.append(date_to)
        if department and department != "All Departments":
            sql += " AND s.department = ?"
            params.append(department)
        if status and status != "All Statuses":
            sql += " AND a.status = ?"
            params.append(status)
        if student_pk is not None:
            sql += " AND s.id = ?"
            params.append(student_pk)
        sql += " ORDER BY a.attendance_date DESC, a.check_in_time DESC, a.id DESC"
        rows = self.db.fetch_all(sql, params)

        if include_unmarked and date_from and date_from == date_to \
                and status in ("", "All Statuses", "Absent"):
            usql = ("SELECT s.id AS student_pk, s.student_id AS roll, s.full_name, "
                    "s.department, s.course FROM students s WHERE s.id NOT IN "
                    "(SELECT student_id FROM attendance WHERE attendance_date = ?) "
                    "AND date(s.created_at) <= ?")
            uparams: list = [date_from, date_from]
            if search:
                usql += " AND (s.full_name LIKE ? OR s.student_id LIKE ?)"
                uparams += [f"%{search.strip()}%"] * 2
            if department and department != "All Departments":
                usql += " AND s.department = ?"
                uparams.append(department)
            if student_pk is not None:
                usql += " AND s.id = ?"
                uparams.append(student_pk)
            for r in self.db.fetch_all(usql + " ORDER BY s.full_name", uparams):
                r.update(id=None, attendance_date=date_from, check_in_time=None,
                         status="Absent", recognition_method="Not marked", confidence=None)
                rows.append(r)
        return rows

    def today_summary(self) -> dict:
        today = date.today().isoformat()
        total = self.db.fetch_one("SELECT COUNT(*) AS n FROM students")["n"]
        r = self.db.fetch_one(
            "SELECT SUM(status IN ('Present','Late')) AS attended, "
            "SUM(status = 'Late') AS late, SUM(recognition_method='Face') AS face "
            "FROM attendance WHERE attendance_date = ?", (today,))
        attended = r["attended"] or 0
        return {
            "total": total,
            "present": attended,
            "late": r["late"] or 0,
            "face": r["face"] or 0,
            "absent": max(total - attended, 0),
            "percentage": round(attended * 100 / total, 1) if total else 0.0,
        }

    def recent(self, limit: int = 8, today_only: bool = False) -> list[dict]:
        sql = ("SELECT a.*, s.student_id AS roll, s.full_name, s.department "
               "FROM attendance a JOIN students s ON s.id = a.student_id ")
        params: list = []
        if today_only:
            sql += "WHERE a.attendance_date = ? "
            params.append(date.today().isoformat())
        sql += "ORDER BY a.attendance_date DESC, a.check_in_time DESC, a.id DESC LIMIT ?"
        params.append(limit)
        return self.db.fetch_all(sql, params)

    @staticmethod
    def export_csv(rows: list[dict], path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        headers = ["Attendance ID", "Student ID", "Student Name", "Department", "Course",
                   "Date", "Check-in Time", "Status", "Method", "LBPH Distance"]
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(headers)
            for r in rows:
                w.writerow([r.get("id") or "", r.get("roll"), r.get("full_name"),
                            r.get("department"), r.get("course", ""),
                            r.get("attendance_date"), r.get("check_in_time") or "",
                            r.get("status"), r.get("recognition_method"),
                            "" if r.get("confidence") is None else r.get("confidence")])
        log.info("Exported %d attendance rows to %s", len(rows), path)
        return path


# =========================================================================== #
# 5. ReportManager
# =========================================================================== #
def _pct(a: int, b: int) -> float:
    return round(a * 100.0 / b, 1) if b else 0.0


def _daterange(d1: date, d2: date):
    for i in range((d2 - d1).days + 1):
        yield d1 + timedelta(days=i)


class ReportManager:
    REPORT_COLUMNS = {
        "daily": [("period", "Date"), ("expected", "Expected"), ("present", "Present"),
                  ("late", "Late"), ("absent", "Absent"), ("percentage", "Attendance %")],
        "weekly": [("period", "Week"), ("sessions", "Sessions"), ("expected", "Expected"),
                   ("attended", "Attended"), ("absent", "Absent"), ("percentage", "Attendance %")],
        "monthly": [("period", "Month"), ("sessions", "Sessions"), ("expected", "Expected"),
                    ("attended", "Attended"), ("absent", "Absent"), ("percentage", "Attendance %")],
        "student": [("roll", "Student ID"), ("full_name", "Name"), ("department", "Department"),
                    ("sessions", "Sessions"), ("attended", "Attended"), ("late", "Late"),
                    ("absent", "Absent"), ("percentage", "Attendance %")],
        "department": [("department", "Department"), ("students", "Students"),
                       ("expected", "Expected"), ("attended", "Attended"),
                       ("absent", "Absent"), ("percentage", "Attendance %")],
    }

    def __init__(self, db: DatabaseManager):
        self.db = db

    def _load(self, date_from: str, date_to: str, department: str = ""):
        sql = "SELECT id, student_id, full_name, department, course, date(created_at) AS reg FROM students"
        params: list = []
        if department and department != "All Departments":
            sql += " WHERE department = ?"
            params.append(department)
        students = self.db.fetch_all(sql + " ORDER BY full_name COLLATE NOCASE", params)
        ids = {s["id"] for s in students}
        recs = [r for r in self.db.fetch_all(
            "SELECT student_id, attendance_date, status FROM attendance "
            "WHERE attendance_date BETWEEN ? AND ?", (date_from, date_to))
            if r["student_id"] in ids]
        by_day: dict[str, dict[int, str]] = defaultdict(dict)
        for r in recs:
            by_day[r["attendance_date"]][r["student_id"]] = r["status"]
        return students, by_day

    @staticmethod
    def _expected(students, day: str, day_recs: dict) -> list[dict]:
        return [s for s in students if (s["reg"] or day) <= day or s["id"] in day_recs]

    def daily(self, date_from: str, date_to: str, department: str = "",
              all_days: bool = False) -> list[dict]:
        students, by_day = self._load(date_from, date_to, department)
        if all_days:
            d1 = datetime.strptime(date_from, "%Y-%m-%d").date()
            d2 = datetime.strptime(date_to, "%Y-%m-%d").date()
            days = [d.isoformat() for d in _daterange(d1, d2)]
        else:
            days = sorted(by_day)
        rows = []
        for day in days:
            recs = by_day.get(day, {})
            expected = len(self._expected(students, day, recs))
            present = sum(1 for s in recs.values() if s == "Present")
            late = sum(1 for s in recs.values() if s == "Late")
            attended = present + late
            rows.append({"period": day, "sessions": 1 if recs else 0, "expected": expected,
                         "present": present, "late": late, "attended": attended,
                         "absent": max(expected - attended, 0),
                         "percentage": _pct(attended, expected) if recs else 0.0})
        return rows

    def _grouped(self, date_from, date_to, department, key_fn) -> list[dict]:
        groups: "OrderedDict[str, dict]" = OrderedDict()
        for r in self.daily(date_from, date_to, department):
            k = key_fn(datetime.strptime(r["period"], "%Y-%m-%d").date())
            g = groups.setdefault(k, {"period": k, "sessions": 0, "expected": 0, "present": 0,
                                      "late": 0, "attended": 0, "absent": 0})
            for f in ("sessions", "expected", "present", "late", "attended", "absent"):
                g[f] += r[f]
        for g in groups.values():
            g["percentage"] = _pct(g["attended"], g["expected"])
        return list(groups.values())

    def weekly(self, date_from, date_to, department=""):
        def key(d: date):
            start = d - timedelta(days=d.weekday())
            return f"{start:%d %b} – {start + timedelta(days=6):%d %b %Y}"
        return self._grouped(date_from, date_to, department, key)

    def monthly(self, date_from, date_to, department=""):
        return self._grouped(date_from, date_to, department, lambda d: d.strftime("%B %Y"))

    def student_wise(self, date_from, date_to, department="") -> list[dict]:
        students, by_day = self._load(date_from, date_to, department)
        rows = []
        for s in students:
            eligible = attended = late = 0
            for day, recs in by_day.items():
                if (s["reg"] or day) <= day or s["id"] in recs:
                    eligible += 1
                    st = recs.get(s["id"])
                    if st in ("Present", "Late"):
                        attended += 1
                    if st == "Late":
                        late += 1
            rows.append({"roll": s["student_id"], "full_name": s["full_name"],
                         "department": s["department"], "course": s["course"],
                         "sessions": eligible, "attended": attended, "late": late,
                         "absent": eligible - attended, "percentage": _pct(attended, eligible)})
        rows.sort(key=lambda r: (-r["percentage"], r["full_name"]))
        return rows

    def department_wise(self, date_from, date_to) -> list[dict]:
        per: dict[str, dict] = {}
        for r in self.student_wise(date_from, date_to):
            d = per.setdefault(r["department"], {"department": r["department"], "students": 0,
                                                 "expected": 0, "attended": 0, "absent": 0})
            d["students"] += 1
            d["expected"] += r["sessions"]
            d["attended"] += r["attended"]
            d["absent"] += r["absent"]
        rows = list(per.values())
        for d in rows:
            d["percentage"] = _pct(d["attended"], d["expected"])
        rows.sort(key=lambda r: r["department"])
        return rows

    def overall(self, date_from, date_to, department="") -> dict:
        daily = self.daily(date_from, date_to, department)
        expected = sum(r["expected"] for r in daily)
        attended = sum(r["attended"] for r in daily)
        return {"sessions": len(daily), "expected": expected, "attended": attended,
                "present": sum(r["present"] for r in daily),
                "late": sum(r["late"] for r in daily),
                "absent": expected - attended, "percentage": _pct(attended, expected)}

    def last_n_days_trend(self, n: int = 7) -> list[dict]:
        today = date.today()
        start = today - timedelta(days=n - 1)
        return self.daily(start.isoformat(), today.isoformat(), all_days=True)

    def build(self, kind: str, date_from: str, date_to: str, department: str = "") -> list[dict]:
        if kind == "daily":
            return self.daily(date_from, date_to, department)
        if kind == "weekly":
            return self.weekly(date_from, date_to, department)
        if kind == "monthly":
            return self.monthly(date_from, date_to, department)
        if kind == "student":
            return self.student_wise(date_from, date_to, department)
        if kind == "department":
            return self.department_wise(date_from, date_to)
        raise ValueError(kind)

    def export_csv(self, kind: str, rows: list[dict], path: Path | str,
                   date_from: str, date_to: str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = self.REPORT_COLUMNS[kind]
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow([f"FaceTrack {kind.title()} Attendance Report", f"{date_from} to {date_to}"])
            w.writerow([])
            w.writerow([c[1] for c in cols])
            for r in rows:
                w.writerow([r.get(k, "") for k, _ in cols])
        log.info("Exported %s report to %s", kind, path)
        return path

    def export_pdf(self, path: Path | str, date_from: str, date_to: str,
                   department: str = "") -> Path:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                        Table, TableStyle)
        from matplotlib.figure import Figure

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        ov = self.overall(date_from, date_to, department)
        daily = self.daily(date_from, date_to, department)
        dept = self.department_wise(date_from, date_to)
        students = self.student_wise(date_from, date_to, department)

        styles = getSampleStyleSheet()
        accent = colors.HexColor(config.COLORS["accent"])
        navy = colors.HexColor(config.COLORS["sidebar"])
        h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=navy, fontSize=18)
        h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=accent)
        body = styles["BodyText"]

        def table(data, widths=None):
            t = Table(data, colWidths=widths, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), navy),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAF8F5")]),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E4DED5")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            return t

        story = [
            Paragraph("FaceTrack – Attendance Report", h1),
            Paragraph(
                f"Period: <b>{date_from}</b> to <b>{date_to}</b>"
                f"{' &nbsp; Department: <b>' + department + '</b>' if department and department != 'All Departments' else ''}"
                f" &nbsp; Generated: {datetime.now():%Y-%m-%d %H:%M}", body),
            Spacer(1, 10), Paragraph("Overview", h2),
            table([["Session days", "Expected", "Present", "Late", "Absent", "Attendance %"],
                   [ov["sessions"], ov["expected"], ov["present"], ov["late"], ov["absent"],
                    f'{ov["percentage"]}%']]),
        ]

        tmp_png = None
        if daily:
            fig = Figure(figsize=(7, 2.6), dpi=150)
            ax = fig.add_subplot(111)
            ax.plot([r["period"][5:] for r in daily], [r["percentage"] for r in daily],
                    color=config.COLORS["accent"], marker="o", linewidth=2)
            ax.set_ylim(0, 105)
            ax.set_ylabel("Attendance %")
            ax.grid(axis="y", alpha=0.3)
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
            ax.tick_params(axis="x", labelrotation=45, labelsize=7)
            fig.tight_layout()
            tmp_png = Path(tempfile.gettempdir()) / f"facetrack_chart_{datetime.now():%H%M%S%f}.png"
            fig.savefig(tmp_png)
            story += [Spacer(1, 8), Paragraph("Attendance Trend", h2),
                      Image(str(tmp_png), width=17 * cm, height=6.3 * cm)]

        def add_section(title, kind, rows):
            story.append(Spacer(1, 8))
            story.append(Paragraph(title, h2))
            if not rows:
                story.append(Paragraph("No data for the selected period.", body))
                return
            cols = self.REPORT_COLUMNS[kind]
            data = [[c[1] for c in cols]] + [[r.get(k, "") for k, _ in cols] for r in rows]
            story.append(table(data))

        add_section("Daily Attendance", "daily", daily)
        add_section("Department-wise Attendance", "department", dept)
        add_section("Student-wise Attendance", "student", students)

        doc = SimpleDocTemplate(
            str(path), pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
            topMargin=1.4 * cm, bottomMargin=1.4 * cm, title="FaceTrack Attendance Report")
        doc.build(story)
        if tmp_png and tmp_png.exists():
            tmp_png.unlink()
        log.info("PDF report written to %s", path)
        return path
