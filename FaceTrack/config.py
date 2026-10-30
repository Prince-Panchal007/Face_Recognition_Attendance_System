"""
FaceTrack - global configuration.

All filesystem paths, default settings and the UI design tokens live here so
that every other module shares a single source of truth.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_NAME = "FaceTrack"
APP_FULL_NAME = "FaceTrack – Smart Face Recognition Attendance Management System"
APP_VERSION = "1.0.0"

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FACES_DIR = DATA_DIR / "faces"
PHOTOS_DIR = DATA_DIR / "photos"
MODELS_DIR = DATA_DIR / "models"
EXPORTS_DIR = DATA_DIR / "exports"
BACKUPS_DIR = DATA_DIR / "backups"
LOGS_DIR = DATA_DIR / "logs"
ASSETS_DIR = BASE_DIR / "assets"
ICONS_DIR = ASSETS_DIR / "icons"
IMAGES_DIR = ASSETS_DIR / "images"

DB_PATH = DATA_DIR / "facetrack.db"
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"
MODEL_PATH = MODELS_DIR / "lbph_model.yml"
LABELS_PATH = MODELS_DIR / "labels.json"
LOG_PATH = LOGS_DIR / "facetrack.log"

# --------------------------------------------------------------------------- #
# Face processing constants
# --------------------------------------------------------------------------- #
FACE_SIZE = (200, 200)          # every stored face sample is resized to this
MIN_FACE_SIZE = (90, 90)        # minimum detected face size (pixels)
ENROLL_MIN_FACE_SIZE = (120, 120)

# Default values for settings stored in the SETTINGS table
DEFAULT_SETTINGS = {
    "camera_index": "0",
    "recognition_threshold": "50",   # LBPH distance: lower = stricter
    "recognition_cooldown": "5",     # seconds between repeated notifications
    "face_sample_count": "15",
    "export_dir": str(EXPORTS_DIR),
    "confirm_frames": "3",           # consecutive matches needed before marking
    "late_after": "",                # "HH:MM" -> later check-ins are 'Late'; blank = off
}

# --------------------------------------------------------------------------- #
# Design tokens (warm, professional palette)
# --------------------------------------------------------------------------- #
COLORS = {
    "bg": "#F6F3EE",            # warm off-white app background
    "surface": "#FFFFFF",       # cards / panels
    "surface_alt": "#FAF8F5",   # table zebra / subtle fills
    "border": "#E4DED5",
    "border_strong": "#D3CBBF",
    "sidebar": "#1F2733",       # dark navy-charcoal
    "sidebar_hover": "#2A3442",
    "sidebar_active": "#323E4F",
    "sidebar_text": "#C3CAD4",
    "sidebar_muted": "#7D8796",
    "text": "#1F2733",
    "text_muted": "#6B7280",
    "text_soft": "#9AA0A9",
    "accent": "#C2603A",        # muted terracotta
    "accent_hover": "#A94F2C",
    "accent_soft": "#F6E7DF",
    "success": "#3F7D58",
    "success_soft": "#E3F0E7",
    "danger": "#B4443B",
    "danger_soft": "#F7E1DF",
    "warning": "#B7832F",
    "warning_soft": "#F6ECD9",
    "info": "#3D6A8E",
    "info_soft": "#E2EBF2",
}

FONT_FAMILY = "Segoe UI"
FONT_FAMILY_SEMI = "Segoe UI Semibold"

DEPARTMENTS = [
    "Computer Science",
    "Information Technology",
    "Electronics",
    "Electrical",
    "Mechanical",
    "Civil",
    "Business Administration",
    "Other",
]


def ensure_directories() -> None:
    """Create every runtime directory if it does not already exist."""
    for d in (DATA_DIR, FACES_DIR, PHOTOS_DIR, MODELS_DIR, EXPORTS_DIR,
              BACKUPS_DIR, LOGS_DIR, ICONS_DIR, IMAGES_DIR):
        d.mkdir(parents=True, exist_ok=True)


def setup_logging() -> logging.Logger:
    """Configure application-wide logging to a rotating file (and console)."""
    ensure_directories()
    logger = logging.getLogger("facetrack")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    fh = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3,
                             encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    if sys.stdout is not None and os.environ.get("FACETRACK_QUIET") != "1":
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    return logger
