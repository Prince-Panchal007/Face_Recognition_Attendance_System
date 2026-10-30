"""
Main application window: fixed sidebar, header with page title and live clock,
and a content area that hosts one page at a time.

The App object also owns the shared "services" (database, managers, face
detector and recognizer) and passes itself to every page, so pages can call
e.g. `self.app.students.add(...)`.
"""
from __future__ import annotations

import logging
import threading
import tkinter as tk
from datetime import datetime
from typing import Callable, Optional

import customtkinter as ctk

import config
from database.db_manager import DatabaseManager
from modules.attendance_manager import AttendanceManager
from modules.report_manager import ReportManager
from modules.student_manager import StudentManager
from recognition.face_detector import FaceDetector, FaceDetectorError
from recognition.face_recognizer import FaceRecognizer
from recognition import trainer
from ui import components as ui

C = config.COLORS
log = logging.getLogger("facetrack.ui")

NAV_ITEMS = [
    ("dashboard", "Dashboard", "dashboard"),
    ("live", "Live Attendance", "live"),
    ("students", "Students", "students"),
    ("records", "Attendance Records", "records"),
    ("reports", "Reports & Analytics", "reports"),
    ("settings", "Settings", "settings"),
]

PAGE_TITLES = {
    "dashboard": ("Dashboard", "Overview of today's attendance"),
    "live": ("Live Attendance", "Real-time face recognition attendance"),
    "students": ("Students", "Register students and enroll their faces"),
    "records": ("Attendance Records", "Search, correct and export attendance"),
    "reports": ("Reports & Analytics", "Attendance statistics from your data"),
    "settings": ("Settings", "Camera, recognition and data management"),
}


class Page(ctk.CTkFrame):
    """Base class for all pages."""

    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color=C["bg"], corner_radius=0)
        self.app = app

    def on_show(self) -> None:
        """Called every time the page becomes visible – refresh data here."""

    def on_hide(self) -> None:
        """Called when leaving the page – release resources (e.g. webcam)."""


class NavButton(ctk.CTkFrame):
    def __init__(self, master, key: str, text: str, icon_name: str, command: Callable):
        super().__init__(master, fg_color="transparent", corner_radius=6, height=42, cursor="hand2")
        self.key, self.command = key, command
        self.pack_propagate(False)
        self.indicator = ctk.CTkFrame(self, width=3, fg_color="transparent", corner_radius=2)
        self.indicator.pack(side="left", fill="y", pady=9)
        self.icon = ctk.CTkLabel(self, text="", width=24,
                                 image=ui.glyph_image(icon_name, C["sidebar_text"], 17))
        self.icon.pack(side="left", padx=(12, 10))
        self.label = ctk.CTkLabel(self, text=text, font=ui.font(13), text_color=C["sidebar_text"],
                                  anchor="w")
        self.label.pack(side="left", fill="x", expand=True)
        self._icon_name = icon_name
        self.active = False
        for w in (self, self.icon, self.label):
            w.bind("<Button-1>", lambda e: self.command(self.key))
            w.bind("<Enter>", lambda e: self._hover(True))
            w.bind("<Leave>", lambda e: self._hover(False))

    def _hover(self, on: bool) -> None:
        if not self.active:
            self.configure(fg_color=C["sidebar_hover"] if on else "transparent")

    def set_active(self, active: bool) -> None:
        self.active = active
        self.configure(fg_color=C["sidebar_active"] if active else "transparent")
        self.indicator.configure(fg_color=C["accent"] if active else "transparent")
        color = "#FFFFFF" if active else C["sidebar_text"]
        self.label.configure(text_color=color, font=ui.font(13, "semibold" if active else "normal"))
        self.icon.configure(image=ui.glyph_image(self._icon_name,
                                                 C["accent"] if active else C["sidebar_text"], 17))


class App(ctk.CTk):
    def __init__(self, db: DatabaseManager):
        super().__init__()
        ctk.set_appearance_mode("light")
        self.title(config.APP_FULL_NAME)
        self.configure(fg_color=C["bg"])
        self.minsize(1100, 640)
        self._set_window_icon()

        # ---- services ----------------------------------------------------
        self.db = db
        self.students = StudentManager(db)
        self.attendance = AttendanceManager(db)
        self.reports = ReportManager(db)
        self.recognizer = FaceRecognizer()
        self.recognizer.load()
        self.detector: Optional[FaceDetector] = None
        self.detector_error: Optional[str] = None
        try:
            self.detector = FaceDetector()
        except FaceDetectorError as exc:
            self.detector_error = str(exc)
            log.error(exc)

        # ---- layout ------------------------------------------------------
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        main = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        self._build_header(main)
        self.content = ctk.CTkFrame(main, fg_color=C["bg"], corner_radius=0)
        self.content.grid(row=1, column=0, sticky="nsew", padx=28, pady=(4, 22))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.pages: dict[str, Page] = {}
        self.current: Optional[str] = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.report_callback_exception = self._on_tk_error
        self._tick()
        self.show_page("dashboard")
        self.after(10, lambda: self.state("zoomed"))
        if self.detector_error:
            self.after(800, lambda: ui.show_error(self, "Face detector unavailable",
                                                  self.detector_error))

    # ------------------------------------------------------------------ #
    def _set_window_icon(self) -> None:
        ico = config.IMAGES_DIR / "facetrack.ico"
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
                self.after(300, lambda: self.iconbitmap(str(ico)))   # CTk resets it once
            except tk.TclError:
                pass

    def _build_sidebar(self) -> None:
        sb = ctk.CTkFrame(self, width=240, fg_color=C["sidebar"], corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsw")
        sb.grid_propagate(False)
        sb.pack_propagate(False)

        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.pack(fill="x", padx=20, pady=(26, 30))
        logo_path = config.IMAGES_DIR / "logo.png"
        if logo_path.exists():
            from PIL import Image
            img = Image.open(logo_path)
            ctk.CTkLabel(brand, text="", image=ctk.CTkImage(img, img, size=(38, 38))).pack(side="left")
        else:
            ctk.CTkLabel(brand, text="F", width=38, height=38, corner_radius=8,
                         fg_color=C["accent"], text_color="#FFFFFF",
                         font=ui.font(18, "bold")).pack(side="left")
        txt = ctk.CTkFrame(brand, fg_color="transparent")
        txt.pack(side="left", padx=12)
        ctk.CTkLabel(txt, text=config.APP_NAME, font=ui.font(18, "semibold"),
                     text_color="#FFFFFF", anchor="w").pack(anchor="w")
        ctk.CTkLabel(txt, text="Attendance System", font=ui.font(11),
                     text_color=C["sidebar_muted"], anchor="w").pack(anchor="w")

        ctk.CTkLabel(sb, text="MENU", font=ui.font(10, "semibold"), text_color=C["sidebar_muted"],
                     anchor="w").pack(fill="x", padx=26, pady=(0, 6))
        self.nav: dict[str, NavButton] = {}
        for key, text, ic in NAV_ITEMS:
            b = NavButton(sb, key, text, ic, self.show_page)
            b.pack(fill="x", padx=14, pady=2)
            self.nav[key] = b

        foot = ctk.CTkFrame(sb, fg_color="transparent")
        foot.pack(side="bottom", fill="x", padx=26, pady=20)
        ctk.CTkFrame(sb, height=1, fg_color=C["sidebar_hover"]).pack(side="bottom", fill="x",
                                                                    padx=20)
        self.model_status = ctk.CTkLabel(foot, text="", font=ui.font(11),
                                         text_color=C["sidebar_muted"], anchor="w")
        self.model_status.pack(anchor="w")
        ctk.CTkLabel(foot, text=f"Version {config.APP_VERSION}  ·  Offline", font=ui.font(11),
                     text_color=C["sidebar_muted"], anchor="w").pack(anchor="w", pady=(2, 0))
        self.update_model_status()

    def _build_header(self, parent) -> None:
        hd = ctk.CTkFrame(parent, fg_color="transparent", height=86)
        hd.grid(row=0, column=0, sticky="ew", padx=28, pady=(18, 8))
        hd.grid_columnconfigure(0, weight=1)
        self.title_lbl = ctk.CTkLabel(hd, text="", font=ui.font(22, "semibold"),
                                      text_color=C["text"], anchor="w")
        self.title_lbl.grid(row=0, column=0, sticky="w")
        self.subtitle_lbl = ctk.CTkLabel(hd, text="", font=ui.font(12), text_color=C["text_muted"],
                                         anchor="w")
        self.subtitle_lbl.grid(row=1, column=0, sticky="w")
        clock = ui.Card(hd, corner_radius=8)
        clock.grid(row=0, column=1, rowspan=2, sticky="e")
        ctk.CTkLabel(clock, text="", image=ui.glyph_image("calendar", C["accent"], 16)).pack(
            side="left", padx=(14, 8), pady=10)
        self.date_lbl = ctk.CTkLabel(clock, text="", font=ui.font(12, "semibold"),
                                     text_color=C["text"])
        self.date_lbl.pack(side="left")
        ctk.CTkFrame(clock, width=1, height=20, fg_color=C["border"]).pack(side="left", padx=12)
        ctk.CTkLabel(clock, text="", image=ui.glyph_image("clock", C["accent"], 16)).pack(
            side="left", padx=(0, 8))
        self.time_lbl = ctk.CTkLabel(clock, text="", font=ui.font(12, "semibold"),
                                     text_color=C["text"], width=70, anchor="w")
        self.time_lbl.pack(side="left", padx=(0, 12))

    def _tick(self) -> None:
        now = datetime.now()
        self.date_lbl.configure(text=now.strftime("%A, %d %B %Y"))
        self.time_lbl.configure(text=now.strftime("%I:%M:%S %p"))
        self.after(1000, self._tick)

    # ------------------------------------------------------------------ #
    def _create_page(self, key: str) -> Page:
        from ui.dashboard import DashboardPage
        from ui.live_attendance import LiveAttendancePage
        from ui.students import StudentsPage
        from ui.attendance_records import AttendanceRecordsPage
        from ui.reports import ReportsPage
        from ui.settings import SettingsPage
        cls = {"dashboard": DashboardPage, "live": LiveAttendancePage, "students": StudentsPage,
               "records": AttendanceRecordsPage, "reports": ReportsPage,
               "settings": SettingsPage}[key]
        return cls(self.content, self)

    def show_page(self, key: str) -> None:
        if key == self.current:
            self.pages[key].on_show()
            return
        if self.current:
            old = self.pages[self.current]
            try:
                old.on_hide()
            except Exception:          # noqa: BLE001
                log.exception("on_hide failed")
            old.grid_forget()
        if key not in self.pages:
            self.pages[key] = self._create_page(key)
        page = self.pages[key]
        page.grid(row=0, column=0, sticky="nsew")
        self.current = key
        for k, b in self.nav.items():
            b.set_active(k == key)
        t, s = PAGE_TITLES[key]
        self.title_lbl.configure(text=t)
        self.subtitle_lbl.configure(text=s)
        try:
            page.on_show()
        except Exception as exc:       # noqa: BLE001
            log.exception("on_show failed")
            self.notify(f"Could not load page data: {exc}", "error")

    # ------------------------------------------------------------------ #
    def notify(self, message: str, kind: str = "info", duration: int = 3200) -> None:
        ui.Toast.show(self, message, kind, duration)

    def run_in_background(self, func: Callable, on_done: Callable[[object, Optional[Exception]], None]):
        """Run func() on a worker thread; call on_done(result, error) on the UI thread."""
        box: dict = {}

        def worker():
            try:
                box["result"] = func()
            except Exception as exc:   # noqa: BLE001
                log.exception("Background task failed")
                box["error"] = exc

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        def poll():
            if t.is_alive():
                self.after(100, poll)
            else:
                on_done(box.get("result"), box.get("error"))
        self.after(100, poll)

    def retrain_model(self, on_done: Optional[Callable] = None) -> None:
        """Retrain LBPH in the background, reload it and report the result."""
        def done(result, error):
            if error:
                self.notify(f"Training failed: {error}", "error", 5000)
            else:
                self.recognizer.load()
                self.notify(result.message, "success" if result.success else "warning", 4000)
            self.update_model_status()
            if on_done:
                on_done(result, error)
        self.run_in_background(lambda: trainer.train_model(self.db), done)

    def update_model_status(self) -> None:
        if self.recognizer.is_ready:
            n = len(self.recognizer.labels)
            self.model_status.configure(text=f"●  Model ready · {n} enrolled",
                                        text_color="#8FBF9F")
        else:
            self.model_status.configure(text="●  Model not trained", text_color="#D9A066")

    # ------------------------------------------------------------------ #
    def _on_tk_error(self, exc_type, exc, tb) -> None:
        log.error("Unhandled UI error", exc_info=(exc_type, exc, tb))
        try:
            self.notify(f"Unexpected error: {exc}. Details were written to the log file.",
                        "error", 5000)
        except Exception:              # noqa: BLE001
            pass

    def on_close(self) -> None:
        for page in self.pages.values():
            try:
                page.on_hide()
            except Exception:          # noqa: BLE001
                log.exception("Error while closing page")
        log.info("Application closed")
        self.destroy()
