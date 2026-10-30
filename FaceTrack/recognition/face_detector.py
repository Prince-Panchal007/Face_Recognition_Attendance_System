"""
Face detection with OpenCV Haar Cascades.

HOW IT WORKS (short version)
----------------------------
A Haar cascade is a pre-trained classifier (Viola–Jones, 2001).  It slides a
window over the grayscale image at many scales and, for every window, checks
simple black/white rectangle patterns ("Haar features") such as "the eye region
is darker than the cheeks".  The checks are arranged in a *cascade*: cheap tests
first, so most non-face windows are rejected very quickly.  Windows that pass
every stage are reported as faces.

This module also contains `preprocess_face`, which turns a detected face into
the normalized 200x200 grayscale image used for BOTH enrollment and recognition.
Using exactly the same preprocessing in both places is essential for accuracy.
"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

import config

log = logging.getLogger("facetrack.detector")

CASCADE_NAME = "haarcascade_frontalface_default.xml"


class FaceDetectorError(Exception):
    pass


class FaceDetector:
    def __init__(self) -> None:
        candidates = [config.ASSETS_DIR / "haarcascades" / CASCADE_NAME]
        if hasattr(cv2, "data"):
            candidates.append(Path(cv2.data.haarcascades) / CASCADE_NAME)
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
                "The face detection model (Haar cascade) could not be loaded.\n"
                "Make sure assets/haarcascades/haarcascade_frontalface_default.xml exists.")

    def detect(self, gray: np.ndarray, min_size=config.MIN_FACE_SIZE) -> list[tuple]:
        """
        Return a list of (x, y, w, h) face rectangles, largest face first.
        `gray` must be a single-channel grayscale image.
        """
        equalized = cv2.equalizeHist(gray)          # reduce lighting effects
        faces = self.cascade.detectMultiScale(
            equalized,
            scaleFactor=1.15,     # image pyramid step (15 % per level)
            minNeighbors=6,       # how many overlapping hits confirm a face
            minSize=min_size,     # ignore tiny / far-away faces
        )
        faces = [tuple(int(v) for v in f) for f in faces]
        faces.sort(key=lambda r: r[2] * r[3], reverse=True)
        return faces


def preprocess_face(gray: np.ndarray, rect: tuple) -> np.ndarray:
    """Crop the face, resize to FACE_SIZE and equalize the histogram."""
    x, y, w, h = rect
    face = gray[y:y + h, x:x + w]
    face = cv2.resize(face, config.FACE_SIZE, interpolation=cv2.INTER_AREA)
    return cv2.equalizeHist(face)


def sharpness(img: np.ndarray) -> float:
    """Variance of the Laplacian – a standard blur measure (higher = sharper)."""
    return float(cv2.Laplacian(img, cv2.CV_64F).var())


# --------------------------------------------------------------------------- #
# Drawing helpers (used by enrollment and live attendance overlays)
# --------------------------------------------------------------------------- #
def hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b, g, r)


def draw_face_box(frame: np.ndarray, rect: tuple, color: tuple,
                  title: str = "", subtitle: str = "") -> None:
    """Draw a clean rectangle with corner accents and a label strip."""
    x, y, w, h = rect
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
    c = max(14, w // 6)   # corner accent length
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
    if top < 0:                      # not enough space above -> draw below
        top = y + h + 4
    cv2.rectangle(frame, (x - 1, top), (x - 1 + box_w, top + box_h), color, -1)
    ty = top + 6
    for (text, scale, thick), sz in zip(lines, sizes):
        ty += sz[1] + 4
        cv2.putText(frame, text, (x + 7, ty), font, scale, (255, 255, 255),
                    thick, cv2.LINE_AA)
        ty += 6
