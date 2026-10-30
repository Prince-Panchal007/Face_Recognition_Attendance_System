"""
Attendance management: marking (face / manual), duplicate prevention,
querying, correcting, deleting and exporting attendance records.

Duplicate prevention is enforced at TWO levels:
  1. The application checks for an existing record before inserting.
  2. The database has UNIQUE(student_id, attendance_date), so even a race
     condition can never create two rows for the same student on one day.
"""
from __future__ import annotations

import csv
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import config
from database.db_manager import DatabaseManager

log = logging.getLogger("facetrack.attendance")

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

    # ------------------------------------------------------------------ #
    # Marking
    # ------------------------------------------------------------------ #
    def _auto_status(self, check_in: str) -> str:
        """'Late' if a late-after time is configured and check-in is after it."""
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
        """Insert one attendance record; refuses duplicates for the same day."""
        day = day or date.today().isoformat()
        check_in = check_in or datetime.now().strftime("%H:%M:%S")
        student = self.db.fetch_one("SELECT * FROM students WHERE id = ?", (student_pk,))
        if not student:
            return MarkResult("error", "Student not found in the database.")
        existing = self.get_record(student_pk, day)
        if existing:
            return MarkResult("duplicate",
                              f"{student['full_name']} is already marked "
                              f"{existing['status']} for {day} at "
                              f"{existing['check_in_time'] or '—'}.", existing)
        status = status or self._auto_status(check_in)
        if status not in STATUSES or method not in METHODS:
            return MarkResult("error", "Invalid status or method.")
        try:
            rid = self.db.execute(
                "INSERT INTO attendance (student_id, attendance_date, check_in_time, status, "
                "recognition_method, confidence) VALUES (?, ?, ?, ?, ?, ?)",
                (student_pk, day, check_in if status != "Absent" else None, status, method,
                 round(confidence, 2) if confidence is not None else None))
        except sqlite3.IntegrityError:          # UNIQUE constraint – race condition
            return MarkResult("duplicate", f"{student['full_name']} is already marked for {day}.")
        record = self.db.fetch_one("SELECT * FROM attendance WHERE id = ?", (rid,))
        record.update(full_name=student["full_name"], roll=student["student_id"],
                      department=student["department"])
        log.info("Attendance: %s %s %s via %s", student["student_id"], day, status, method)
        return MarkResult("marked", f"{student['full_name']} marked {status} at {check_in}.",
                          record)

    def update_record(self, record_id: int, status: str, check_in: Optional[str],
                      day: Optional[str] = None) -> None:
        """Correct an existing record (status / time / date)."""
        if status not in STATUSES:
            raise ValueError("Invalid status")
        if check_in:
            datetime.strptime(check_in, "%H:%M:%S")      # validates format
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

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    def list_records(self, search: str = "", date_from: str = "", date_to: str = "",
                     department: str = "", status: str = "",
                     student_pk: Optional[int] = None,
                     include_unmarked: bool = False) -> list[dict]:
        """
        Filtered attendance list (newest first).
        include_unmarked: when a single day is selected (date_from == date_to),
        also list students with no record that day as 'Absent' (not stored).
        """
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

    # ------------------------------------------------------------------ #
    # Export
    # ------------------------------------------------------------------ #
    @staticmethod
    def export_csv(rows: list[dict], path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        headers = ["Attendance ID", "Student ID", "Student Name", "Department", "Course",
                   "Date", "Check-in Time", "Status", "Method", "LBPH Distance"]
        with path.open("w", newline="", encoding="utf-8-sig") as f:   # BOM -> Excel friendly
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
