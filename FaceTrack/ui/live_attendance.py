"""
Live Face Recognition Attendance page.

Displays the real-time webcam feed, draws face detection boxes and recognized
student labels, shows live statistics, logs recognition notifications, and
supports Start/Stop Camera, Pause/Resume Recognition, Switch Camera, and
Manual Attendance fallback.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import customtkinter as ctk

import config
from modules.attendance_manager import STATUSES
from recognition.camera import CameraStream, list_cameras
from recognition.live_engine import LiveRecognitionEngine
from ui import components as ui
from ui.main_window import Page
from ui.video import VideoView

C = config.COLORS
log = logging.getLogger("facetrack.ui.live")


class ManualAttendanceDialog(ui.Dialog):
    """Fallback dialog to mark attendance manually for a selected student."""

    def __init__(self, parent, app, preselect_pk: Optional[int] = None,
                 default_date: Optional[str] = None):
        super().__init__(parent, "Manual Attendance", 480, 420)
        self.app = app
        self.result = None

        students = app.students.list()
        self.students_map: dict[str, dict] = {}
        options = []
        selected_label = ""
        for s in students:
            label = f"{s['student_id']} – {s['full_name']} ({s['department']})"
            self.students_map[label] = s
            options.append(label)
            if preselect_pk and s["id"] == preselect_pk:
                selected_label = label

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=26, pady=(20, 6))
        ctk.CTkLabel(head, text="Mark Manual Attendance",
                     font=ui.font(16, "semibold"), text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(head, text="Record attendance manually when camera recognition is not used.",
                     font=ui.font(12), text_color=C["text_muted"]).pack(anchor="w")

        card = ui.Card(self)
        card.pack(fill="both", expand=True, padx=26, pady=10)
        card.grid_columnconfigure((0, 1), weight=1)

        ui.field_label(card, "Student", True).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(14, 2))
        self.student_var = ctk.StringVar(value=selected_label or (options[0] if options else ""))
        self.student_menu = ui.option_menu(
            card, options or ["No students registered"], width=400, variable=self.student_var)
        self.student_menu.grid(row=1, column=0, columnspan=2, sticky="ew", padx=18)

        ui.field_label(card, "Date (YYYY-MM-DD)", True).grid(
            row=2, column=0, sticky="w", padx=18, pady=(12, 2))
        self.date_entry = ui.entry(card)
        self.date_entry.insert(0, default_date or datetime.now().strftime("%Y-%m-%d"))
        self.date_entry.grid(row=3, column=0, sticky="ew", padx=(18, 8))

        ui.field_label(card, "Check-in Time (HH:MM:SS)", True).grid(
            row=2, column=1, sticky="w", padx=(8, 18), pady=(12, 2))
        self.time_entry = ui.entry(card)
        self.time_entry.insert(0, datetime.now().strftime("%H:%M:%S"))
        self.time_entry.grid(row=3, column=1, sticky="ew", padx=(8, 18))

        ui.field_label(card, "Attendance Status", True).grid(
            row=4, column=0, columnspan=2, sticky="w", padx=18, pady=(12, 2))
        self.status_var = ctk.StringVar(value="Present")
        self.status_menu = ui.option_menu(card, list(STATUSES), width=200, variable=self.status_var)
        self.status_menu.grid(row=5, column=0, sticky="w", padx=18)

        self.err_lbl = ctk.CTkLabel(card, text="", font=ui.font(12), text_color=C["danger"])
        self.err_lbl.grid(row=6, column=0, columnspan=2, sticky="w", padx=18, pady=(10, 12))

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=26, pady=(0, 20))
        save_btn = ui.Button(foot, "Mark Attendance", "check", style="primary", command=self.save)
        save_btn.pack(side="right")
        if not options:
            save_btn.configure_state(False)
        ui.Button(foot, "Cancel", command=self.cancel).pack(side="right", padx=8)

    def save(self):
        student = self.students_map.get(self.student_var.get())
        if not student:
            self.err_lbl.configure(text="Please select a registered student.")
            return
        day = self.date_entry.get().strip()
        check_in = self.time_entry.get().strip()
        try:
            datetime.strptime(day, "%Y-%m-%d")
            datetime.strptime(check_in, "%H:%M:%S")
        except ValueError:
            self.err_lbl.configure(text="Use YYYY-MM-DD for date and HH:MM:SS for time.")
            return
        res = self.app.attendance.mark(
            student["id"], method="Manual", status=self.status_var.get(),
            day=day, check_in=check_in)
        if res.status == "duplicate":
            self.err_lbl.configure(text=res.message)
            return
        if res.status == "error":
            self.err_lbl.configure(text=res.message)
            return
        self.result = res
        self.destroy()


class LiveAttendancePage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure(0, weight=7)
        self.grid_columnconfigure(1, weight=4)
        self.grid_rowconfigure(1, weight=1)

        self.engine: Optional[LiveRecognitionEngine] = None
        if app.detector is not None:
            self.engine = LiveRecognitionEngine(app.detector, app.recognizer, app.attendance)
        self.stream = CameraStream(self.engine.process if self.engine else None)
        self._cam_indices: list[int] = [app.db.get_setting_int("camera_index")]
        self._poll_job: Optional[str] = None

        # ---- Top control bar ----------------------------------------------
        bar = ui.Card(self)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        self.btn_start = ui.Button(bar, "Start Camera", "play", style="primary",
                                   command=self.start_camera)
        self.btn_start.pack(side="left", padx=(16, 6), pady=12)
        self.btn_stop = ui.Button(bar, "Stop Camera", "stop", style="danger",
                                  command=self.stop_camera)
        self.btn_stop.pack(side="left", padx=6, pady=12)
        self.btn_pause = ui.Button(bar, "Pause Recognition", "pause",
                                   command=self.toggle_pause)
        self.btn_pause.pack(side="left", padx=6, pady=12)
        self.btn_switch = ui.Button(bar, "Switch Camera", "switch",
                                    command=self.switch_camera)
        self.btn_switch.pack(side="left", padx=6, pady=12)

        ui.Button(bar, "Manual Attendance", "edit", style="dark",
                  command=self.open_manual).pack(side="right", padx=(6, 16), pady=12)
        self.status_badge = ui.Badge(bar, "Camera Stopped", "neutral")
        self.status_badge.pack(side="right", padx=10)

        # ---- Left: video + live banner ------------------------------------
        left = ui.Card(self)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 14))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(0, weight=1)

        self.video = VideoView(left)
        self.video.grid(row=0, column=0, sticky="nsew", padx=14, pady=(14, 10))
        self.video.show_placeholder(
            "Camera is off",
            "Click 'Start Camera' above to begin real-time face detection and attendance marking.")

        self.banner = ctk.CTkFrame(left, fg_color=C["surface_alt"], corner_radius=6, height=58)
        self.banner.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 14))
        self.banner.grid_propagate(False)
        self.banner_bar = ctk.CTkFrame(self.banner, width=5, fg_color=C["info"], corner_radius=0)
        self.banner_bar.pack(side="left", fill="y")
        btxt = ctk.CTkFrame(self.banner, fg_color="transparent")
        btxt.pack(side="left", fill="both", expand=True, padx=14, pady=8)
        self.banner_title = ctk.CTkLabel(
            btxt, text="Ready for Live Attendance", font=ui.font(13, "semibold"),
            text_color=C["text"], anchor="w")
        self.banner_title.pack(anchor="w")
        self.banner_sub = ctk.CTkLabel(
            btxt, text="Enrolled students looking at the camera are marked automatically once per day.",
            font=ui.font(11), text_color=C["text_muted"], anchor="w")
        self.banner_sub.pack(anchor="w")
        self.fps_lbl = ctk.CTkLabel(self.banner, text="", font=ui.font(11),
                                    text_color=C["text_soft"])
        self.fps_lbl.pack(side="right", padx=14)

        # ---- Right: live stats & today's check-ins ------------------------
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew")
        right.grid_columnconfigure((0, 1), weight=1)
        right.grid_rowconfigure(2, weight=1)

        # Mini stat tiles
        self.tile_present = self._mini_stat(right, 0, 0, "Present Today", "0", C["success"])
        self.tile_absent = self._mini_stat(right, 0, 1, "Absent Today", "0", C["danger"])
        self.tile_frame = self._mini_stat(right, 1, 0, "Faces in Frame", "0", C["info"])
        self.tile_thr = self._mini_stat(right, 1, 1, "Threshold / Cooldown", "—", C["accent"])

        log_card = ui.Card(right)
        log_card.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        hdr = ui.SectionHeader(log_card, "Today's Check-ins", "Marked during today's session")
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        self.today_table = ui.DataTable(
            log_card,
            [("time", "Time", 75, "w"), ("name", "Student", 145, "w"),
             ("roll", "ID", 80, "w"), ("method", "Method", 70, "w")],
            height=10, empty_text="No students marked present today yet.")
        self.today_table.pack(fill="both", expand=True, padx=1, pady=(0, 8))

        self._sync_buttons()

    def _mini_stat(self, parent, row: int, col: int, label: str, value: str, color: str):
        card = ui.Card(parent)
        card.grid(row=row, column=col, sticky="nsew",
                  padx=(0 if col == 0 else 6, 6 if col == 0 else 0), pady=(0, 8))
        ctk.CTkLabel(card, text=label.upper(), font=ui.font(10, "semibold"),
                     text_color=C["text_muted"]).pack(anchor="w", padx=14, pady=(10, 0))
        val = ctk.CTkLabel(card, text=value, font=ui.font(20, "semibold"), text_color=color)
        val.pack(anchor="w", padx=14, pady=(0, 10))
        return val

    # ------------------------------------------------------------------ #
    def on_show(self) -> None:
        self.app.recognizer.load()
        self.app.update_model_status()
        if self.engine:
            self.engine.reload()
        self.refresh_stats()
        self._sync_buttons()

    def on_hide(self) -> None:
        self.stop_camera()

    def refresh_stats(self) -> None:
        s = self.app.attendance.today_summary()
        self.tile_present.configure(text=f"{s['present']} / {s['total']}")
        self.tile_absent.configure(text=str(s["absent"]))
        thr = self.app.db.get_setting_int("recognition_threshold")
        cd = self.app.db.get_setting_int("recognition_cooldown")
        self.tile_thr.configure(text=f"≤ {thr}  ·  {cd}s")
        rows = self.app.attendance.recent(25, today_only=True)
        self.today_table.set_rows(
            rows, lambda r: (r["check_in_time"], r["full_name"], r["roll"], r["recognition_method"]),
            lambda r: "success" if r["recognition_method"] == "Face" else None)

    def _sync_buttons(self) -> None:
        running = self.stream.running
        self.btn_start.configure_state(not running and self.engine is not None)
        self.btn_stop.configure_state(running)
        self.btn_pause.configure_state(running)
        self.btn_switch.configure_state(running)
        if not running:
            self.btn_pause.set_text("Pause Recognition")

    # ------------------------------------------------------------------ #
    def start_camera(self) -> None:
        if self.engine is None:
            ui.show_error(self, "Face detector unavailable", self.app.detector_error or "")
            return
        self.app.recognizer.load()
        self.app.update_model_status()
        self.engine.reload()
        self.engine.paused = False

        if self.app.students.count() == 0:
            self._set_banner("No students registered yet",
                             "Camera will detect faces as UNKNOWN. Register & enroll students first.",
                             C["warning"])
        elif not self.app.recognizer.is_ready:
            self._set_banner("No trained face model",
                             self.app.recognizer.error or "Enroll a student's face to enable recognition.",
                             C["warning"])
        else:
            self._set_banner("Live recognition active",
                             f"Loaded {len(self.app.recognizer.labels)} enrolled student(s). "
                             f"Threshold ≤ {self.engine.threshold:.0f}.", C["success"])

        cam_idx = self.app.db.get_setting_int("camera_index")
        self.video.show_placeholder("Opening camera...", f"Connecting to camera {cam_idx}...")
        self.status_badge.set(f"Camera {cam_idx} Starting", "info")
        self.stream.start(cam_idx)
        self._sync_buttons()
        self._schedule_poll()

    def stop_camera(self) -> None:
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:          # noqa: BLE001
                pass
            self._poll_job = None
        if self.stream.running or self.stream.state == "error":
            self.stream.stop()
        self.video.show_placeholder(
            "Camera is off",
            "Click 'Start Camera' above to begin real-time face detection and attendance marking.")
        self.status_badge.set("Camera Stopped", "neutral")
        self.tile_frame.configure(text="0")
        self.fps_lbl.configure(text="")
        self._sync_buttons()

    def toggle_pause(self) -> None:
        if not self.engine or not self.stream.running:
            return
        self.engine.paused = not self.engine.paused
        if self.engine.paused:
            self.btn_pause.set_text("Resume Recognition")
            self.status_badge.set("Recognition Paused", "warning")
            self._set_banner("Recognition paused",
                             "Video feed is live, but attendance marking is paused.", C["warning"])
        else:
            self.btn_pause.set_text("Pause Recognition")
            self.status_badge.set(f"Camera {self.stream.camera_index} Live", "success")
            self._set_banner("Recognition resumed",
                             "Faces are being matched against enrolled students.", C["success"])

    def switch_camera(self) -> None:
        if not self.stream.running:
            return
        self.status_badge.set("Probing cameras...", "info")

        def probe():
            found = list_cameras(3)
            cur = self.stream.camera_index or 0
            if cur not in found:
                found = sorted(set(found + [cur]))
            return found

        def done(found, error):
            if error or not found or len(found) < 2:
                self.app.notify("No second camera detected on this system.", "warning")
                self.status_badge.set(f"Camera {self.stream.camera_index} Live", "success")
                return
            self._cam_indices = found
            cur = self.stream.camera_index or 0
            nxt = found[(found.index(cur) + 1) % len(found)]
            self.app.db.set_setting("camera_index", nxt)
            self.stream.start(nxt)
            self.app.notify(f"Switched to camera {nxt}.", "info")

        self.app.run_in_background(probe, done)

    def open_manual(self) -> None:
        d = ManualAttendanceDialog(self, self.app)
        self.wait_window(d)
        if d.result:
            self.app.notify(d.result.message, "success")
            self._set_banner("Manual attendance recorded", d.result.message, C["success"])
            self.refresh_stats()

    # ------------------------------------------------------------------ #
    def _set_banner(self, title: str, sub: str, color: str) -> None:
        self.banner_bar.configure(fg_color=color)
        self.banner_title.configure(text=title)
        self.banner_sub.configure(text=sub)

    def _schedule_poll(self) -> None:
        self._poll_job = self.after(30, self._poll)

    def _poll(self) -> None:
        self._poll_job = None
        if not self.winfo_exists():
            return
        st = self.stream.state
        if st == "error":
            self.video.show_placeholder("Camera Unavailable", self.stream.error or "", "warning")
            self.status_badge.set("Camera Error", "danger")
            self._set_banner("Webcam could not be opened",
                             "Use 'Manual Attendance' on the top right if you have no camera attached.",
                             C["danger"])
            self._sync_buttons()
            return
        if st == "running":
            if not (self.engine and self.engine.paused):
                self.status_badge.set(f"Camera {self.stream.camera_index} Live", "success")
            _, frame = self.stream.get_frame()
            if frame is not None:
                self.video.show_frame(frame)
            if self.engine:
                f_total = self.engine.faces_in_frame
                f_known = self.engine.known_in_frame
                f_unk = self.engine.unknown_in_frame
                self.tile_frame.configure(text=f"{f_total}  ({f_known}✓ {f_unk}?)")
                while not self.engine.events.empty():
                    kind, student, dist, msg = self.engine.events.get_nowait()
                    if kind == "marked":
                        self._set_banner(
                            f"Attendance Marked: {student['full_name']} ({student['student_id']})",
                            f"{msg}  ·  LBPH distance {dist:.1f}", C["success"])
                        self.app.notify(msg, "success")
                        self.refresh_stats()
                    elif kind == "duplicate":
                        self._set_banner(
                            f"Already Marked Today: {student['full_name']}",
                            msg, C["info"])
                    else:
                        self._set_banner("Attendance Error", msg, C["danger"])
                        self.app.notify(msg, "error")
            self.fps_lbl.configure(text=f"{self.stream.fps:.0f} FPS" if self.stream.fps else "")
        if self.stream.running:
            self._schedule_poll()
