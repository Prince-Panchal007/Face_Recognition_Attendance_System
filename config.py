"""
FaceTrack – Global Configuration & Theme Tokens (`config.py`).

All filesystem paths, default settings, logging setup, color palette, and the
in-memory application logo generator live here so every module shares a single
source of truth without requiring external asset folders.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PIL import Image, ImageDraw

APP_NAME = "FaceTrack"
APP_FULL_NAME = "FaceTrack – Smart Face Recognition Attendance Management System"
APP_VERSION = "1.0.0"

# --------------------------------------------------------------------------- #
# Runtime Paths (all inside data/ — created automatically on startup)
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FACES_DIR = DATA_DIR / "faces"
PHOTOS_DIR = DATA_DIR / "photos"
MODELS_DIR = DATA_DIR / "models"
EXPORTS_DIR = DATA_DIR / "exports"
BACKUPS_DIR = DATA_DIR / "backups"
LOGS_DIR = DATA_DIR / "logs"

DB_PATH = DATA_DIR / "facetrack.db"
MODEL_PATH = MODELS_DIR / "lbph_model.yml"
LABELS_PATH = MODELS_DIR / "labels.json"
LOG_PATH = LOGS_DIR / "facetrack.log"

# --------------------------------------------------------------------------- #
# Computer Vision Constants & Default Settings
# --------------------------------------------------------------------------- #
FACE_SIZE = (200, 200)          # Every face sample is resized to 200x200 px
MIN_FACE_SIZE = (90, 90)        # Minimum detected face size in live mode
ENROLL_MIN_FACE_SIZE = (120, 120)

DEFAULT_SETTINGS = {
    "camera_index": "0",
    "recognition_threshold": "50",   # LBPH Chi-Square distance (lower = stricter)
    "recognition_cooldown": "5",     # Seconds between repeated notifications
    "face_sample_count": "15",       # Samples captured per student enrollment
    "export_dir": str(EXPORTS_DIR),
    "confirm_frames": "3",           # Consecutive frames needed before marking
    "late_after": "",                # Optional "HH:MM" cutoff; blank = disabled
}

# --------------------------------------------------------------------------- #
# Desktop UI Design Tokens (Warm off-white + Navy-Charcoal + Terracotta)
# --------------------------------------------------------------------------- #
COLORS = {
    "bg": "#F6F3EE",            # Warm off-white background
    "surface": "#FFFFFF",       # White cards & panels
    "surface_alt": "#FAF8F5",   # Table zebra rows & subtle fills
    "border": "#E4DED5",
    "border_strong": "#D3CBBF",
    "sidebar": "#1F2733",       # Dark navy-charcoal sidebar
    "sidebar_hover": "#2A3442",
    "sidebar_active": "#323E4F",
    "sidebar_text": "#C3CAD4",
    "sidebar_muted": "#7D8796",
    "text": "#1F2733",
    "text_muted": "#6B7280",
    "text_soft": "#9AA0A9",
    "accent": "#C2603A",        # Muted terracotta / orange accent
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
    """Create all runtime data directories if they do not exist yet."""
    for d in (DATA_DIR, FACES_DIR, PHOTOS_DIR, MODELS_DIR,
              EXPORTS_DIR, BACKUPS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def setup_logging() -> logging.Logger:
    """Configure rotating file + console logging."""
    ensure_directories()
    logger = logging.getLogger("facetrack")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    fh = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    if sys.stdout is not None and os.environ.get("FACETRACK_QUIET") != "1":
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    return logger


def build_logo_image(size: int = 256) -> Image.Image:
    """Generate the FaceTrack brand icon in memory using Pillow."""
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 12, 244, 244), radius=48, fill=COLORS["accent"])
    w = 14
    for (x0, y0, sx, sy) in [(54, 54, 1, 1), (202, 54, -1, 1),
                             (54, 202, 1, -1), (202, 202, -1, -1)]:
        d.line([(x0, y0), (x0 + sx * 38, y0)], fill="white", width=w)
        d.line([(x0, y0), (x0, y0 + sy * 38)], fill="white", width=w)
    d.ellipse((102, 82, 154, 134), fill="white")
    d.pieslice((78, 140, 178, 230), start=180, end=360, fill="white")
    if size != 256:
        img = img.resize((size, size), Image.LANCZOS)
    return img
