"""
FaceTrack – Computer Vision & Recognition Layer (`vision.py`).

Consolidates the complete OpenCV pipeline in one well-structured module:
  1. `FaceDetector`          – Viola–Jones Haar Cascade frontal face detection,
                               200x200 histogram-equalized preprocessing,
                               Laplacian blur measurement, and box drawing.
  2. `FaceRecognizer`        – Thread-safe OpenCV LBPH (`cv2.face`) wrapper.
  3. `train_model()`         – Rebuilds `lbph_model.yml` + `labels.json` from
                               all enrolled students' face samples.
  4. `CameraStream`          – Background-threaded webcam reader (`cv2.VideoCapture`)
                               so camera I/O never freezes the Tkinter UI.
  5. `EnrollmentSession`     – Quality-checked 15-sample face capture session.
  6. `LiveRecognitionEngine` – Multi-frame streak verification, per-student
                               cooldown, and automatic attendance marking.
"""
from __future__ import annotations

import json
import logging
import queue
import shutil
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

import config
from database import AttendanceManager, count_samples, student_face_dir

log = logging.getLogger("facetrack.vision")

CASCADE_NAME = "haarcascade_frontalface_default.xml"
FRAME_WIDTH, FRAME_HEIGHT = 640, 480


# =========================================================================== #
# 1. Face Detection & Preprocessing (Haar Cascade)
# =========================================================================== #
class FaceDetectorError(Exception):
    pass


class FaceDetector:
    """Viola–Jones Haar Cascade frontal face detector."""

    def __init__(self) -> None:
        candidates = []
        if hasattr(cv2, "data"):
            candidates.append(Path(cv2.data.haarcascades) / CASCADE_NAME)
        candidates.append(config.DATA_DIR / CASCADE_NAME)
        self.cascade = None
        for path in candidates:
            if path.is_file():
                cascade = cv2.CascadeClassifier(str(path))
                if not cascade.empty():
                    self.cascade = cascade
                    log.info("Loaded Haar cascade from %s", path)
                    break
        if self.cascade is None:
            raise FaceDetectorError(
                "The OpenCV Haar Cascade file (haarcascade_frontalface_default.xml) "
                "could not be loaded.")

    def detect(self, gray: np.ndarray, min_size=config.MIN_FACE_SIZE) -> list[tuple]:
        """Return list of (x, y, w, h) face rectangles sorted largest-first."""
        equalized = cv2.equalizeHist(gray)
        faces = self.cascade.detectMultiScale(
            equalized,
            scaleFactor=1.15,
            minNeighbors=6,
            minSize=min_size,
        )
        faces = [tuple(int(v) for v in f) for f in faces]
        faces.sort(key=lambda r: r[2] * r[3], reverse=True)
        return faces


def preprocess_face(gray: np.ndarray, rect: tuple) -> np.ndarray:
    """Crop the detected face, resize to 200x200, and equalize histogram."""
    x, y, w, h = rect
    face = gray[y:y + h, x:x + w]
    face = cv2.resize(face, config.FACE_SIZE, interpolation=cv2.INTER_AREA)
    return cv2.equalizeHist(face)


def sharpness(img: np.ndarray) -> float:
    """Variance of the Laplacian (higher = sharper edges, lower = blurry)."""
    return float(cv2.Laplacian(img, cv2.CV_64F).var())


def hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b, g, r)


def draw_face_box(frame: np.ndarray, rect: tuple, color: tuple,
                  title: str = "", subtitle: str = "") -> None:
    """Draw a clean rectangle with corner brackets and a readable text banner."""
    x, y, w, h = rect
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
    c = max(14, w // 6)
    for (px, py, dx, dy) in ((x, y, 1, 1), (x + w, y, -1, 1),
                             (x, y + h, 1, -1), (x + w, y + h, -1, -1)):
        cv2.line(frame, (px, py), (px + dx * c, py), color, 4)
        cv2.line(frame, (px, py), (px, py + dy * c), color, 4)
    if not title:
        return
    font = cv2.FONT_HERSHEY_SIMPLEX
    lines = [(title, 0.6, 2)] + ([(subtitle, 0.45, 1)] if subtitle else [])
    sizes = [cv2.getTextSize(t, font, s, th)[0] for t, s, th in lines]
    box_w = max(sz[0] for sz in sizes) + 16
    box_h = sum(sz[1] for sz in sizes) + 10 * len(lines) + 6
    top = y - box_h - 4
    if top < 0:
        top = y + h + 4
    cv2.rectangle(frame, (x - 1, top), (x - 1 + box_w, top + box_h), color, -1)
    ty = top + 6
    for (text, scale, thick), sz in zip(lines, sizes):
        ty += sz[1] + 4
        cv2.putText(frame, text, (x + 7, ty), font, scale, (255, 255, 255),
                    thick, cv2.LINE_AA)
        ty += 6


# =========================================================================== #
# 2. LBPH Face Recognizer & Model Trainer
# =========================================================================== #
def create_lbph():
    if not hasattr(cv2, "face"):
        raise RuntimeError(
            "cv2.face is missing. Install 'opencv-contrib-python' (not 'opencv-python').")
    return cv2.face.LBPHFaceRecognizer_create(
        radius=1, neighbors=8, grid_x=8, grid_y=8)


class FaceRecognizer:
    """Thread-safe wrapper around the trained LBPH face recognition model."""

    def __init__(self, model_path: Path = config.MODEL_PATH,
                 labels_path: Path = config.LABELS_PATH):
        self.model_path = Path(model_path)
        self.labels_path = Path(labels_path)
        self._model = None
        self.labels: dict[int, dict] = {}
        self.error: Optional[str] = None
        self._lock = threading.Lock()

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    def load(self) -> bool:
        with self._lock:
            self._model = None
            self.labels = {}
            self.error = None
            if not self.model_path.is_file():
                self.error = ("No trained face model found. Enroll at least one "
                              "student's face first.")
                return False
            try:
                model = create_lbph()
                model.read(str(self.model_path))
                if self.labels_path.is_file():
                    raw = json.loads(self.labels_path.read_text(encoding="utf-8"))
                    self.labels = {int(k): v for k, v in raw.get("labels", {}).items()}
                self._model = model
                log.info("LBPH model loaded (%d identities)", len(self.labels))
                return True
            except Exception as exc:      # noqa: BLE001
                log.exception("Failed to load LBPH model")
                self.error = ("The face model file is corrupted or unreadable. "
                              "Use Settings → Retrain Model to rebuild it.\n"
                              f"({exc})")
                return False

    def predict(self, face: np.ndarray) -> tuple[Optional[int], float]:
        with self._lock:
            if self._model is None:
                return None, float("inf")
            label, distance = self._model.predict(face)
            return int(label), float(distance)


@dataclass
class TrainResult:
    success: bool
    message: str
    students: int = 0
    samples: int = 0


def train_model(db) -> TrainResult:
    """Train the LBPH recognizer from all enrolled students' stored samples."""
    rows = db.fetch_all(
        "SELECT id, student_id, full_name FROM students WHERE face_enrolled = 1")
    enrolled = {r["id"]: {"student_id": r["student_id"], "full_name": r["full_name"]}
                for r in rows if count_samples(r["id"]) > 0}

    if not enrolled:
        for p in (config.MODEL_PATH, config.LABELS_PATH):
            if p.exists():
                p.unlink()
        return TrainResult(False, "No enrolled face samples found. The model was cleared.")

    faces, labels = [], []
    for pk in enrolled:
        for img_path in sorted(student_face_dir(pk).glob("*.png")):
            img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            if img.shape[::-1] != config.FACE_SIZE:
                img = cv2.resize(img, config.FACE_SIZE)
            faces.append(img)
            labels.append(pk)

    if not faces:
        return TrainResult(False, "Face sample files could not be read.")

    model = create_lbph()
    model.train(faces, np.array(labels, dtype=np.int32))
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.MODEL_PATH.with_suffix(".tmp.yml")
    model.write(str(tmp))
    tmp.replace(config.MODEL_PATH)
    config.LABELS_PATH.write_text(json.dumps({
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "samples": len(faces),
        "labels": {str(k): v for k, v in enrolled.items()},
    }, indent=2), encoding="utf-8")
    msg = f"Model trained on {len(faces)} samples from {len(enrolled)} student(s)."
    log.info(msg)
    return TrainResult(True, msg, len(enrolled), len(faces))


# =========================================================================== #
# 3. Background Webcam Stream (`CameraStream`)
# =========================================================================== #
def _backends() -> list[int]:
    if sys.platform.startswith("win"):
        return [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
    return [cv2.CAP_ANY]


def open_camera(index: int) -> Optional[cv2.VideoCapture]:
    for backend in _backends():
        cap = None
        try:
            cap = cv2.VideoCapture(index, backend)
            if not cap.isOpened():
                cap.release()
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
            for _ in range(5):
                ok, frame = cap.read()
                if ok and frame is not None:
                    log.info("Camera %s opened (backend %s)", index, backend)
                    return cap
                time.sleep(0.1)
            cap.release()
        except Exception:                   # noqa: BLE001
            if cap is not None:
                cap.release()
    return None


def list_cameras(max_index: int = 4) -> list[int]:
    found = []
    for i in range(max_index + 1):
        cap = cv2.VideoCapture(i, _backends()[0])
        try:
            if cap.isOpened():
                ok, _ = cap.read()
                if ok:
                    found.append(i)
        finally:
            cap.release()
    return found


class CameraStream:
    """Reads webcam frames on a worker thread and runs an optional processor."""

    def __init__(self, processor: Optional[Callable[[np.ndarray], np.ndarray]] = None):
        self.processor = processor
        self.state = "stopped"
        self.error: Optional[str] = None
        self.camera_index: Optional[int] = None
        self.fps = 0.0
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._frame_id = 0

    @property
    def running(self) -> bool:
        return self.state in ("opening", "running")

    def start(self, index: int) -> None:
        self.stop()
        self._stop.clear()
        self.error = None
        self.camera_index = index
        self.state = "opening"
        with self._lock:
            self._frame = None
        self._thread = threading.Thread(
            target=self._run, args=(index,), name="CameraStream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=3)
        self._thread = None
        if self.state != "error":
            self.state = "stopped"

    def get_frame(self) -> tuple[int, Optional[np.ndarray]]:
        with self._lock:
            return self._frame_id, self._frame

    def _run(self, index: int) -> None:
        cap = open_camera(index)
        if cap is None:
            self.error = (
                f"Could not open camera {index}.\n\n"
                "• Check that a webcam is connected.\n"
                "• Close other apps using the camera (Zoom, Teams, Camera app).\n"
                "• Allow camera access in Windows Settings → Privacy → Camera.")
            self.state = "error"
            log.error("Camera %s could not be opened", index)
            return
        self.state = "running"
        failures = 0
        t_last, frames = time.time(), 0
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    failures += 1
                    if failures > 40:
                        self.error = "The camera stopped sending frames (was it disconnected?)."
                        self.state = "error"
                        break
                    time.sleep(0.05)
                    continue
                failures = 0
                frame = cv2.flip(frame, 1)
                if self.processor is not None:
                    try:
                        frame = self.processor(frame)
                    except Exception:               # noqa: BLE001
                        log.exception("Frame processor failed")
                with self._lock:
                    self._frame = frame
                    self._frame_id += 1
                frames += 1
                now = time.time()
                if now - t_last >= 1.0:
                    self.fps = frames / (now - t_last)
                    t_last, frames = now, 0
        finally:
            cap.release()
            log.info("Camera %s released", index)
            if self.state != "error":
                self.state = "stopped"


# =========================================================================== #
# 4. Guided Face Enrollment Session
# =========================================================================== #
CAPTURE_INTERVAL = 0.35
MIN_SHARPNESS = 25.0
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
GREY = (150, 150, 150)


class EnrollmentSession:
    """Captures quality-checked grayscale 200x200 face samples for one student."""

    def __init__(self, detector: FaceDetector, student_pk: int, target: int = 15):
        self.detector = detector
        self.student_pk = student_pk
        self.target = max(5, int(target))
        self.final_dir = student_face_dir(student_pk)
        self.face_dir = config.FACES_DIR / f"_tmp_{student_pk}"
        self.photo_path = config.PHOTOS_DIR / f"{student_pk}.jpg"
        self.tmp_photo = self.face_dir / "photo.jpg"
        self.count = 0
        self.capturing = False
        self.done = False
        self.message = "Position your face inside the frame, then press Start Capture."
        self.level = "info"
        self._last_capture = 0.0
        self._best_photo_sharpness = -1.0

    def begin(self) -> None:
        shutil.rmtree(self.face_dir, ignore_errors=True)
        self.face_dir.mkdir(parents=True, exist_ok=True)
        self.count = 0
        self.done = False
        self._best_photo_sharpness = -1.0
        self.capturing = True

    def commit(self) -> Optional[str]:
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

    def process(self, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.detector.detect(gray, min_size=config.ENROLL_MIN_FACE_SIZE)

        if not faces:
            self.message, self.level = "No face detected – face the camera in good light.", "warn"
            return frame
        if len(faces) > 1:
            for r in faces:
                draw_face_box(frame, r, RED)
            self.message, self.level = (
                "Multiple faces detected – only the student being enrolled should be in view.",
                "error")
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
            if sharp > self._best_photo_sharpness:
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


# =========================================================================== #
# 5. Live Recognition Engine
# =========================================================================== #
class LiveRecognitionEngine:
    """Real-time face recognition with streak verification and cooldown."""

    def __init__(self, detector: FaceDetector, recognizer: FaceRecognizer,
                 attendance: AttendanceManager):
        self.detector = detector
        self.recognizer = recognizer
        self.attendance = attendance
        self.db = attendance.db
        self.events: "queue.Queue" = queue.Queue()
        self.paused = False
        self.threshold = 50.0
        self.cooldown = 5.0
        self.confirm_frames = 3
        self.faces_in_frame = 0
        self.known_in_frame = 0
        self.unknown_in_frame = 0
        self._streak: dict[int, int] = defaultdict(int)
        self._last_event: dict[int, float] = {}
        self._students: dict[int, Optional[dict]] = {}

    def reload(self) -> None:
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
                draw_face_box(
                    frame, rect, RED, "UNKNOWN",
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

        for label in list(self._streak):
            if label not in seen:
                del self._streak[label]
        self.known_in_frame, self.unknown_in_frame = known, unknown
        return frame

    def _on_recognized(self, student: dict, dist: float) -> None:
        now = time.time()
        last = self._last_event.get(student["id"])
        if last is not None and now - last < self.cooldown:
            return
        self._last_event[student["id"]] = now
        try:
            result = self.attendance.mark(student["id"], method="Face", confidence=dist)
        except Exception:                         # noqa: BLE001
            log.exception("Failed to mark attendance")
            self.events.put(("error", student, dist,
                             "Could not save attendance (database error). See log file."))
            return
        self.events.put((result.status, student, dist, result.message))
