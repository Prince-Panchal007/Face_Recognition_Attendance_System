"""
LBPH face recognition.

HOW LBPH WORKS (short version)
------------------------------
1. Local Binary Patterns: for every pixel, compare it with its 8 neighbours.
   Neighbour >= centre -> 1, otherwise 0.  The 8 bits form a number 0-255 that
   describes the local texture (edge, corner, flat area ...).
2. The face image is divided into an 8x8 grid of cells.  For each cell a
   histogram of those LBP numbers is computed.
3. All 64 histograms are concatenated into one long feature vector.
4. Recognition = find the training sample whose histogram vector is closest
   (chi-square distance).  The returned "confidence" is that DISTANCE:
   **lower means more similar**.  If the distance is above our threshold we
   treat the face as UNKNOWN.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

import config

log = logging.getLogger("facetrack.recognizer")


def create_lbph():
    """Create an LBPH recognizer with the classic parameters."""
    if not hasattr(cv2, "face"):
        raise RuntimeError(
            "cv2.face is missing. Install 'opencv-contrib-python' (not 'opencv-python').")
    return cv2.face.LBPHFaceRecognizer_create(radius=1, neighbors=8,
                                              grid_x=8, grid_y=8)


class FaceRecognizer:
    """Thread-safe wrapper around a trained LBPH model."""

    def __init__(self, model_path: Path = config.MODEL_PATH,
                 labels_path: Path = config.LABELS_PATH):
        self.model_path = Path(model_path)
        self.labels_path = Path(labels_path)
        self._model = None
        self.labels: dict[int, dict] = {}   # label -> {"student_id", "full_name"}
        self.error: Optional[str] = None
        self._lock = threading.Lock()

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    def load(self) -> bool:
        """Load the model from disk. Returns False (with self.error) on failure."""
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
            except Exception as exc:      # noqa: BLE001 – corrupted file etc.
                log.exception("Failed to load LBPH model")
                self.error = ("The face model file is corrupted or unreadable. "
                              "Use Settings → Retrain Model to rebuild it.\n"
                              f"({exc})")
                return False

    def predict(self, face: np.ndarray) -> tuple[Optional[int], float]:
        """
        Predict the identity of a preprocessed face.
        Returns (label, distance).  label is None if no model is loaded.
        """
        with self._lock:
            if self._model is None:
                return None, float("inf")
            label, distance = self._model.predict(face)
            return int(label), float(distance)
