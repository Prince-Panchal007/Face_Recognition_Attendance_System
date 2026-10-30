"""
Student management: validation and CRUD operations on the STUDENTS table,
plus cleanup of each student's face samples and photograph.
"""
from __future__ import annotations

import logging
import re
import shutil
import sqlite3
from typing import Optional

import config
from database.db_manager import DatabaseManager
from recognition.trainer import count_samples, student_face_dir

log = logging.getLogger("facetrack.students")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-]{6,18}$")
ROLL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_/]{0,29}$")


class ValidationError(Exception):
    """Invalid user input – message is shown directly to the user."""


class StudentManager:
    def __init__(self, db: DatabaseManager):
        self.db = db

    # ------------------------------------------------------------------ #
    @staticmethod
    def validate(data: dict) -> dict:
        """Trim and validate the form fields. Returns the cleaned dict."""
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

    # ------------------------------------------------------------------ #
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
        """Delete the student, their attendance (cascade), samples and photo.
        Returns True if the student had enrolled faces (model must be retrained)."""
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
        """Departments in use plus the default list, de-duplicated."""
        used = [r["department"] for r in self.db.fetch_all(
            "SELECT DISTINCT department FROM students ORDER BY department")]
        out = list(config.DEPARTMENTS)
        for d in used:
            if d not in out:
                out.append(d)
        return out

    # ------------------------------------------------------------------ #
    def mark_enrolled(self, pk: int, photo_path: Optional[str]) -> None:
        enrolled = 1 if count_samples(pk) > 0 else 0
        self.db.execute("UPDATE students SET face_enrolled=?, photo_path=? WHERE id=?",
                        (enrolled, photo_path, pk))

    def clear_enrollment(self, pk: int) -> None:
        shutil.rmtree(student_face_dir(pk), ignore_errors=True)
        self.db.execute("UPDATE students SET face_enrolled=0 WHERE id=?", (pk,))

    @staticmethod
    def sample_count(pk: int) -> int:
        return count_samples(pk)
