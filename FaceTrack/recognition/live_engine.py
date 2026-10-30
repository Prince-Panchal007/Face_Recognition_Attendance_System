"""
Live recognition engine – the heart of automatic attendance.

For every camera frame:
  1. detect all faces (Haar cascade),
  2. preprocess each face exactly like during enrollment,
  3. ask the LBPH model for the closest enrolled student and the distance,
  4. accept the match only if distance <= threshold (configurable),
  5. require the same student in N consecutive frames (prevents one-frame
     false positives),
  6. mark attendance in SQLite (duplicates are refused by AttendanceManager
     and by the UNIQUE constraint),
  7. a per-student cooldown prevents notification spam while the student
     keeps standing in front of the camera.
Events are pushed to a thread-safe queue that the UI drains.
"""
from __future__ import annotations

import logging
import queue
import time
from collections import defaultdict
from typing import Optional

import cv2
import numpy as np

import config
from modules.attendance_manager import AttendanceManager
from recognition.face_detector import FaceDetector, draw_face_box, hex_to_bgr, preprocess_face
from recognition.face_recognizer import FaceRecognizer

log = logging.getLogger("facetrack.live")

GREEN = hex_to_bgr(config.COLORS["success"])
AMBER = hex_to_bgr(config.COLORS["warning"])
RED = hex_to_bgr(config.COLORS["danger"])
GREY = (150, 150, 150)


class LiveRecognitionEngine:
    def __init__(self, detector: FaceDetector, recognizer: FaceRecognizer,
                 attendance: AttendanceManager):
        self.detector = detector
        self.recognizer = recognizer
        self.attendance = attendance
        self.db = attendance.db
        self.events: "queue.Queue" = queue.Queue()
        self.paused = False
        self.threshold = 65.0
        self.cooldown = 5.0
        self.confirm_frames = 3
        self.faces_in_frame = 0
        self.known_in_frame = 0
        self.unknown_in_frame = 0
        self._streak: dict[int, int] = defaultdict(int)
        self._last_event: dict[int, float] = {}
        self._students: dict[int, Optional[dict]] = {}

    def reload(self) -> None:
        """Re-read settings and clear caches (call before starting the camera)."""
        self.threshold = float(self.db.get_setting_int("recognition_threshold"))
        self.cooldown = float(self.db.get_setting_int("recognition_cooldown"))
        self.confirm_frames = max(1, self.db.get_setting_int("confirm_frames"))
        self._streak.clear()
        self._last_event.clear()
        self._students.clear()

    def _student(self, pk: int) -> Optional[dict]:
        if pk not in self._students:
            self._students[pk] = self.db.fetch_one(
                "SELECT id, student_id, full_name, department FROM students "
                "WHERE id = ? AND face_enrolled = 1", (pk,))
        return self._students[pk]

    # ------------------------------------------------------------------ #
    def process(self, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.detector.detect(gray)
        self.faces_in_frame = len(faces)
        known = unknown = 0
        seen: set[int] = set()

        for rect in faces:
            if self.paused:
                draw_face_box(frame, rect, GREY, "Recognition paused")
                continue
            if not self.recognizer.is_ready:
                draw_face_box(frame, rect, AMBER, "Face detected", "No trained model")
                continue

            label, dist = self.recognizer.predict(preprocess_face(gray, rect))
            student = self._student(label) if label is not None else None

            if student is None or dist > self.threshold:
                unknown += 1
                draw_face_box(frame, rect, RED, "UNKNOWN",
                              f"distance {dist:.1f} > {self.threshold:.0f}" if student
                              else f"distance {dist:.1f}")
                continue

            seen.add(label)
            self._streak[label] += 1
            if self._streak[label] < self.confirm_frames:
                draw_face_box(frame, rect, AMBER, "Verifying...",
                              f"{student['full_name']}  ·  distance {dist:.1f}")
                continue

            known += 1
            draw_face_box(frame, rect, GREEN, student["full_name"],
                          f"{student['student_id']}  ·  distance {dist:.1f}")
            self._on_recognized(student, dist)

        for label in list(self._streak):      # reset streaks of faces that left
            if label not in seen:
                del self._streak[label]
        self.known_in_frame, self.unknown_in_frame = known, unknown
        return frame

    def _on_recognized(self, student: dict, dist: float) -> None:
        now = time.time()
        last = self._last_event.get(student["id"])
        if last is not None and now - last < self.cooldown:
            return                                # still in cooldown – stay quiet
        self._last_event[student["id"]] = now
        try:
            result = self.attendance.mark(student["id"], method="Face", confidence=dist)
        except Exception:                         # noqa: BLE001 – DB problems must not kill the thread
            log.exception("Failed to mark attendance")
            self.events.put(("error", student, dist,
                             "Could not save attendance (database error). See log file."))
            return
        self.events.put((result.status, student, dist, result.message))
