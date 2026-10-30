"""
Training the LBPH model from the face samples stored on disk.

Folder layout:   data/faces/<students.id>/<n>.png   (200x200 grayscale)

The integer database primary key (`students.id`) is used as the LBPH label,
so a prediction maps directly back to a row in the STUDENTS table.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

import config
from recognition.face_recognizer import create_lbph

log = logging.getLogger("facetrack.trainer")


@dataclass
class TrainResult:
    success: bool
    message: str
    students: int = 0
    samples: int = 0


def student_face_dir(student_pk: int) -> Path:
    return config.FACES_DIR / str(student_pk)


def count_samples(student_pk: int) -> int:
    d = student_face_dir(student_pk)
    return len(list(d.glob("*.png"))) if d.is_dir() else 0


def load_samples(enrolled: dict[int, dict]) -> tuple[list[np.ndarray], list[int]]:
    """Read every usable sample image for the given students."""
    faces, labels = [], []
    for pk in enrolled:
        for img_path in sorted(student_face_dir(pk).glob("*.png")):
            img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                log.warning("Skipping unreadable sample %s", img_path)
                continue
            if img.shape[::-1] != config.FACE_SIZE:
                img = cv2.resize(img, config.FACE_SIZE)
            faces.append(img)
            labels.append(pk)
    return faces, labels


def train_model(db) -> TrainResult:
    """
    Rebuild the LBPH model from all enrolled students' samples.
    `db` is a DatabaseManager.  Safe to call from a worker thread.
    """
    rows = db.fetch_all(
        "SELECT id, student_id, full_name FROM students WHERE face_enrolled = 1")
    enrolled = {r["id"]: {"student_id": r["student_id"], "full_name": r["full_name"]}
                for r in rows if count_samples(r["id"]) > 0}

    if not enrolled:
        # Nothing to train – remove stale model so no one is recognized wrongly.
        for p in (config.MODEL_PATH, config.LABELS_PATH):
            if p.exists():
                p.unlink()
        return TrainResult(False, "No enrolled face samples found. The model was cleared.")

    faces, labels = load_samples(enrolled)
    if not faces:
        return TrainResult(False, "Face sample files could not be read.")

    model = create_lbph()
    model.train(faces, np.array(labels, dtype=np.int32))
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.MODEL_PATH.with_suffix(".tmp.yml")
    model.write(str(tmp))
    tmp.replace(config.MODEL_PATH)          # atomic swap: never a half-written model
    config.LABELS_PATH.write_text(json.dumps({
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "samples": len(faces),
        "labels": {str(k): v for k, v in enrolled.items()},
    }, indent=2), encoding="utf-8")
    msg = f"Model trained on {len(faces)} samples from {len(enrolled)} student(s)."
    log.info(msg)
    return TrainResult(True, msg, len(enrolled), len(faces))
