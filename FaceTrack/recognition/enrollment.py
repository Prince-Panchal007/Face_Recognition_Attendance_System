"""
Face enrollment: captures good-quality face samples for one student.

For every camera frame `process()`:
  1. detects faces with the Haar cascade,
  2. rejects the frame if there is no face / more than one face,
  3. checks quality (face size, sharpness, brightness),
  4. while capturing, saves at most one sample every CAPTURE_INTERVAL seconds
     so that the samples differ (angle / expression) instead of being copies.
Samples are saved as 200x200 grayscale PNGs in data/faces/<students.id>/.
"""
from __future__ import annotations

import shutil
import time

import cv2
import numpy as np

import config
from recognition.face_detector import (FaceDetector, draw_face_box, hex_to_bgr,
                                       preprocess_face, sharpness)
from recognition.trainer import student_face_dir

CAPTURE_INTERVAL = 0.35      # seconds between saved samples
MIN_SHARPNESS = 25.0         # Laplacian variance below this = too blurry
GUIDANCE = [
    "Look straight at the camera",
    "Turn your head slightly LEFT",
    "Turn your head slightly RIGHT",
    "Tilt your head slightly UP",
    "Tilt your head slightly DOWN",
    "Smile naturally",
    "Neutral expression, look straight",
]

GREEN = hex_to_bgr(config.COLORS["success"])
AMBER = hex_to_bgr(config.COLORS["warning"])
RED = hex_to_bgr(config.COLORS["danger"])


class EnrollmentSession:
    def __init__(self, detector: FaceDetector, student_pk: int, target: int = 15):
        self.detector = detector
        self.student_pk = student_pk
        self.target = max(5, int(target))
        self.final_dir = student_face_dir(student_pk)
        # Samples are captured into a temporary folder and only moved into place
        # by commit(), so cancelling never destroys a previous enrollment.
        self.face_dir = config.FACES_DIR / f"_tmp_{student_pk}"
        self.photo_path = config.PHOTOS_DIR / f"{student_pk}.jpg"
        self.tmp_photo = self.face_dir / "photo.jpg"
        self.count = 0
        self.capturing = False
        self.done = False
        self.message = "Position your face inside the frame, then press Start Capture."
        self.level = "info"            # info | ok | warn | error  (for the UI colour)
        self._last_capture = 0.0
        self._best_photo_sharpness = -1.0

    # ------------------------------------------------------------------ #
    def begin(self) -> None:
        """Start (or restart) capturing into the temporary folder."""
        shutil.rmtree(self.face_dir, ignore_errors=True)
        self.face_dir.mkdir(parents=True, exist_ok=True)
        self.count = 0
        self.done = False
        self._best_photo_sharpness = -1.0
        self.capturing = True

    def commit(self) -> str | None:
        """Replace the student's samples with the new ones. Returns photo path."""
        self.capturing = False
        if self.count == 0:
            raise ValueError("No usable face samples were captured.")
        shutil.rmtree(self.final_dir, ignore_errors=True)
        photo = None
        if self.tmp_photo.exists():
            config.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.move(str(self.tmp_photo), str(self.photo_path))
            photo = str(self.photo_path)
        shutil.move(str(self.face_dir), str(self.final_dir))
        return photo

    def discard(self) -> None:
        self.capturing = False
        shutil.rmtree(self.face_dir, ignore_errors=True)

    def guidance(self) -> str:
        step = len(GUIDANCE) * self.count // max(self.target, 1)
        return GUIDANCE[min(step, len(GUIDANCE) - 1)]

    # ------------------------------------------------------------------ #
    def process(self, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.detector.detect(gray, min_size=config.ENROLL_MIN_FACE_SIZE)

        if not faces:
            self.message, self.level = "No face detected – face the camera in good light.", "warn"
            return frame
        if len(faces) > 1:
            for r in faces:
                draw_face_box(frame, r, RED)
            self.message, self.level = ("Multiple faces detected – only the student being "
                                        "enrolled should be in view."), "error"
            return frame

        rect = faces[0]
        x, y, w, h = rect
        raw = cv2.resize(gray[y:y + h, x:x + w], config.FACE_SIZE)
        sharp = sharpness(raw)
        brightness = float(raw.mean())

        problem = None
        if sharp < MIN_SHARPNESS:
            problem = "Image is blurry – hold still."
        elif brightness < 45:
            problem = "Too dark – improve the lighting."
        elif brightness > 215:
            problem = "Too bright – avoid strong light behind/at the camera."

        if self.done:
            draw_face_box(frame, rect, GREEN, "Enrollment complete")
            self.message, self.level = f"Captured {self.count} samples. Click Save & Train.", "ok"
            return frame

        if problem:
            draw_face_box(frame, rect, AMBER, "Adjust", problem)
            self.message, self.level = problem, "warn"
            return frame

        if not self.capturing:
            draw_face_box(frame, rect, GREEN, "Face detected", "Ready to capture")
            self.message, self.level = "Face detected. Press Start Capture when ready.", "ok"
            return frame

        now = time.time()
        if now - self._last_capture >= CAPTURE_INTERVAL:
            self._last_capture = now
            face = preprocess_face(gray, rect)
            self.count += 1
            cv2.imwrite(str(self.face_dir / f"{self.count:02d}.png"), face)
            if sharp > self._best_photo_sharpness:      # keep the sharpest colour photo
                self._best_photo_sharpness = sharp
                self._save_photo(frame, rect)
            if self.count >= self.target:
                self.done, self.capturing = True, False

        draw_face_box(frame, rect, GREEN, f"Capturing {self.count}/{self.target}",
                      self.guidance())
        self.message, self.level = f"{self.guidance()}  ({self.count}/{self.target})", "ok"
        return frame

    def _save_photo(self, frame: np.ndarray, rect: tuple) -> None:
        x, y, w, h = rect
        m = int(0.35 * w)
        H, W = frame.shape[:2]
        crop = frame[max(0, y - m):min(H, y + h + m), max(0, x - m):min(W, x + w + m)]
        if crop.size:
            cv2.imwrite(str(self.tmp_photo), cv2.resize(crop, (260, 260)))
