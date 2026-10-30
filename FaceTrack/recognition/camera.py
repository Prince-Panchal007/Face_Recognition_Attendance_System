"""
Webcam access in a background thread.

Tkinter is single-threaded: if we read the camera on the UI thread the window
would freeze.  `CameraStream` therefore reads frames in a daemon thread, runs an
optional `processor(frame) -> frame` function on each frame (face detection /
recognition), and stores only the most recent result.  The UI polls
`get_frame()` with `after()` and draws it – the only safe way to update Tk
widgets from background work.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Callable, Optional

import cv2
import numpy as np

log = logging.getLogger("facetrack.camera")

FRAME_WIDTH, FRAME_HEIGHT = 640, 480


def _backends() -> list[int]:
    if sys.platform.startswith("win"):
        return [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
    return [cv2.CAP_ANY]


def open_camera(index: int) -> Optional[cv2.VideoCapture]:
    """Try the available backends; return an opened capture or None."""
    for backend in _backends():
        cap = None
        try:
            cap = cv2.VideoCapture(index, backend)
            if not cap.isOpened():
                cap.release()
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
            for _ in range(5):              # some cameras need a few warm-up reads
                ok, frame = cap.read()
                if ok and frame is not None:
                    log.info("Camera %s opened (backend %s)", index, backend)
                    return cap
                time.sleep(0.1)
            cap.release()
        except Exception:                   # noqa: BLE001 – driver errors vary
            log.exception("Error opening camera %s with backend %s", index, backend)
            if cap is not None:
                cap.release()
    return None


def list_cameras(max_index: int = 4) -> list[int]:
    """Return the indices of cameras that can be opened (slow: run in a thread)."""
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
    """Reads frames from a webcam on a worker thread."""

    def __init__(self, processor: Optional[Callable[[np.ndarray], np.ndarray]] = None):
        self.processor = processor
        self.state = "stopped"          # stopped | opening | running | error
        self.error: Optional[str] = None
        self.camera_index: Optional[int] = None
        self.fps = 0.0
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._frame_id = 0

    # ------------------------------------------------------------------ #
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
        self._thread = threading.Thread(target=self._run, args=(index,),
                                        name="CameraStream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the worker to finish and wait briefly; releases the device."""
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

    # ------------------------------------------------------------------ #
    def _run(self, index: int) -> None:
        cap = open_camera(index)
        if cap is None:
            self.error = (f"Could not open camera {index}.\n\n"
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
                frame = cv2.flip(frame, 1)          # mirror view feels natural
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
