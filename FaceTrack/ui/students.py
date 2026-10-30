"""Students page: register / edit / delete students, face enrollment and details."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import customtkinter as ctk
from PIL import Image

import config
from modules.student_manager import ValidationError
from recognition.camera import CameraStream
from recognition.enrollment import EnrollmentSession
from ui import components as ui
from ui.main_window import Page
from ui.video import VideoView

C = config.COLORS
log = logging.getLogger("facetrack.ui.students")
MIN_SAMPLES = 5


# =========================================================================== #
# Add / edit form
# =========================================================================== #
class StudentFormDialog(ui.Dialog):
    def __init__(self, parent, app, student: Optional[dict] = None):
        super().__init__(parent, "Edit Student" if student else "Register Student", 560, 560)
        self.app, self.student = app, student
        self.result: Optional[int] = None

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=28, pady=(22, 4))
        ctk.CTkLabel(head, text="Edit Student" if student else "Register New Student",
                     font=ui.font(17, "semibold"), text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(head, text="Fields marked * are required.", font=ui.font(12),
                     text_color=C["text_muted"]).pack(anchor="w")

        form = ui.Card(self)
        form.pack(fill="both", expand=True, padx=28, pady=12)
        form.grid_columnconfigure((0, 1), weight=1, uniform="f")
        self.fields: dict[str, object] = {}

        def add(row, col, key, label, required=False, widget=None, span=1):
            ui.field_label(form, label, required).grid(row=row * 2, column=col, columnspan=span,
                                                       sticky="w", padx=18, pady=(14 if row == 0 else 8, 2))
            w = widget or ui.entry(form)
            w.grid(row=row * 2 + 1, column=col, columnspan=span, sticky="ew", padx=18)
            self.fields[key] = w

        add(0, 0, "student_id", "Student ID / Roll No.", True)
        add(0, 1, "full_name", "Full Name", True)
        self.dept_var = ctk.StringVar(value="")
        add(1, 0, "department", "Department", True,
            ui.combo(form, app.students.departments(), variable=self.dept_var))
        add(1, 1, "course", "Course / Class", True)
        add(2, 0, "email", "Email (optional)")
        add(2, 1, "phone", "Phone (optional)")
        self.error = ctk.CTkLabel(form, text="", font=ui.font(12), text_color=C["danger"],
                                  wraplength=440, justify="left")
        self.error.grid(row=6, column=0, columnspan=2, sticky="w", padx=18, pady=(14, 14))

        if student:
            for k in ("student_id", "full_name", "course", "email", "phone"):
                if student.get(k):
                    self.fields[k].insert(0, student[k])
            self.dept_var.set(student["department"])
        else:
            self.dept_var.set("")

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=28, pady=(0, 22))
        ui.Button(foot, "Save Changes" if student else "Register Student", "save",
                  style="primary", command=self.save).pack(side="right")
        ui.Button(foot, "Cancel", command=self.cancel).pack(side="right", padx=8)
        self.bind("<Return>", lambda e: self.save())
        self.after(200, lambda: self.fields["student_id"].focus_set())

    def save(self):
        data = {k: (w.get() if k != "department" else self.dept_var.get())
                for k, w in self.fields.items()}
        try:
            if self.student:
                self.app.students.update(self.student["id"], data)
                self.result = self.student["id"]
            else:
                self.result = self.app.students.add(data)
        except ValidationError as exc:
            self.error.configure(text=str(exc))
            return
        except Exception as exc:      # noqa: BLE001
            log.exception("Saving student failed")
            self.error.configure(text=f"Could not save the student: {exc}")
            return
        self.destroy()


# =========================================================================== #
# Face enrollment
# =========================================================================== #
class EnrollmentDialog(ui.Dialog):
    def __init__(self, parent, app, student: dict):
        super().__init__(parent, f"Face Enrollment – {student['full_name']}", 1040, 640)
        self.app, self.student = app, student
        self.result = False
        target = app.db.get_setting_int("face_sample_count")
        self.session = EnrollmentSession(app.detector, student["id"], target)
        self.stream = CameraStream(self.session.process)
        self._saving = False
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.video = VideoView(self)
        self.video.grid(row=0, column=0, sticky="nsew", padx=(22, 12), pady=22)

        side = ui.Card(self, width=330)
        side.grid(row=0, column=1, sticky="ns", padx=(0, 22), pady=22)
        side.grid_propagate(False)
        inner = ctk.CTkFrame(side, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20, pady=18)

        ctk.CTkLabel(inner, text=student["full_name"], font=ui.font(16, "semibold"),
                     text_color=C["text"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(inner, text=f"{student['student_id']}  ·  {student['department']}",
                     font=ui.font(12), text_color=C["text_muted"], anchor="w").pack(anchor="w")

        tips = ctk.CTkFrame(inner, fg_color=C["surface_alt"], corner_radius=6)
        tips.pack(fill="x", pady=14)
        ctk.CTkLabel(tips, text="Instructions", font=ui.font(12, "semibold"),
                     text_color=C["text"]).pack(anchor="w", padx=12, pady=(10, 2))
        for t in ("Sit 40–70 cm from the camera, face well lit.",
                  "Only the student should be in view.",
                  "Follow the on-screen prompts: turn slightly left/right, tilt, smile.",
                  "Remove sunglasses or masks."):
            ctk.CTkLabel(tips, text=f"•  {t}", font=ui.font(11), text_color=C["text_muted"],
                         wraplength=270, justify="left", anchor="w").pack(anchor="w", padx=12)
        ctk.CTkLabel(tips, text="").pack(pady=1)

        self.consent = ctk.CTkCheckBox(
            inner, text="The student consents to their face images\nbeing captured and stored "
                        "locally for attendance.", font=ui.font(11), text_color=C["text"],
            fg_color=C["accent"], hover_color=C["accent_hover"], border_color=C["border_strong"],
            checkbox_width=18, checkbox_height=18, command=self._update_buttons)
        self.consent.pack(anchor="w", pady=(0, 14))

        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text="Samples captured", font=ui.font(12, "semibold"),
                     text_color=C["text_muted"]).pack(side="left")
        self.count_lbl = ctk.CTkLabel(row, text=f"0 / {self.session.target}",
                                      font=ui.font(14, "semibold"), text_color=C["text"])
        self.count_lbl.pack(side="right")
        self.progress = ctk.CTkProgressBar(inner, height=8, corner_radius=4,
                                           progress_color=C["accent"], fg_color=C["border"])
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(6, 12))
        self.status = ctk.CTkLabel(inner, text="Starting camera...", font=ui.font(12),
                                   text_color=C["info"], wraplength=280, justify="left",
                                   anchor="w")
        self.status.pack(anchor="w", fill="x")

        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.pack(side="bottom", fill="x")
        self.save_btn = ui.Button(btns, "Save & Train Model", "check", style="success",
                                  command=self.save, height=40)
        self.save_btn.pack(fill="x", pady=(8, 0))
        self.capture_btn = ui.Button(btns, "Start Capture", "camera", style="primary",
                                     command=self.start_capture, height=40)
        self.capture_btn.pack(fill="x", pady=(8, 0))
        self.cancel_btn = ui.Button(btns, "Cancel", command=self.cancel, height=36)
        self.cancel_btn.pack(fill="x", pady=(8, 0))
        self._update_buttons()

        self.stream.start(app.db.get_setting_int("camera_index"))
        self._poll()

    def _update_buttons(self):
        consent = bool(self.consent.get())
        cam_ok = self.stream.state == "running"
        self.capture_btn.configure_state(consent and cam_ok and not self._saving)
        self.save_btn.configure_state(self.session.count >= MIN_SAMPLES and not
                                      self.session.capturing and not self._saving)

    def start_capture(self):
        self.session.begin()
        self.capture_btn.set_text("Restart Capture")
        self._update_buttons()

    def _poll(self):
        if not self.winfo_exists():
            return
        st = self.stream.state
        if st == "error":
            self.video.show_placeholder("Camera unavailable", self.stream.error, "warning")
            self.status.configure(text="Camera could not be opened. Check Settings → Camera.",
                                  text_color=C["danger"])
            self._update_buttons()
            return
        if st == "opening":
            self.video.show_placeholder("Opening camera...", "This can take a few seconds.")
        _, frame = self.stream.get_frame()
        if frame is not None:
            self.video.show_frame(frame)
            s = self.session
            self.count_lbl.configure(text=f"{s.count} / {s.target}")
            self.progress.set(s.count / s.target)
            color = {"ok": C["success"], "warn": C["warning"], "error": C["danger"],
                     "info": C["info"]}[s.level]
            msg = s.message
            if not self.consent.get() and not s.capturing and not s.done:
                msg = "Tick the consent box to enable capture.\n" + msg
            self.status.configure(text=msg, text_color=color)
        self._update_buttons()
        if not self._saving:
            self.after(30, self._poll)

    def save(self):
        if self.session.count < MIN_SAMPLES:
            ui.show_error(self, "Not enough samples",
                          f"At least {MIN_SAMPLES} usable face samples are required.")
            return
        self._saving = True
        self.stream.stop()
        self._update_buttons()
        self.video.show_placeholder("Training recognition model...",
                                    "Please wait a moment.", "sync")
        try:
            photo = self.session.commit()
            self.app.students.mark_enrolled(self.student["id"], photo)
        except Exception as exc:          # noqa: BLE001
            log.exception("Saving enrollment failed")
            ui.show_error(self, "Enrollment failed", f"Could not save the face samples:\n{exc}")
            self._saving = False
            return

        def done(result, error):
            self.result = True
            n = self.session.count
            if error or not result.success:
                ui.show_error(self, "Training problem",
                              f"Samples were saved but training failed:\n{error or result.message}"
                              "\nUse Settings → Retrain Model.")
            else:
                ui.show_info(self, "Enrollment successful",
                             f"{self.student['full_name']} has been enrolled with {n} face "
                             f"samples.\n\n{result.message}\nThe student can now be recognized "
                             "on the Live Attendance screen.", "success")
            self.destroy()
        self.app.retrain_model(done)

    def cancel(self):
        if self._saving:
            return
        self.stream.stop()
        self.session.discard()
        self.destroy()

    def destroy(self):
        self.stream.stop()
        super().destroy()


# =========================================================================== #
# Page
# =========================================================================== #
class StudentsPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.selected: Optional[dict] = None

        # ---- toolbar ------------------------------------------------------
        bar = ui.Card(self)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        ctk.CTkLabel(bar, text="", image=ui.glyph_image("search", C["text_soft"], 16)).pack(
            side="left", padx=(16, 6), pady=12)
        self.search = ui.entry(bar, "Search by name, ID or course", width=260)
        self.search.pack(side="left", pady=12)
        self.search.bind("<KeyRelease>", lambda e: self.refresh())
        self.dept = ui.option_menu(bar, ["All Departments"], width=200,
                                   command=lambda v: self.refresh())
        self.dept.pack(side="left", padx=10)
        ui.Button(bar, "Register Student", "add", style="primary",
                  command=self.open_add_dialog).pack(side="right", padx=(6, 16))
        self.count_lbl = ctk.CTkLabel(bar, text="", font=ui.font(12), text_color=C["text_muted"])
        self.count_lbl.pack(side="right", padx=10)

        # ---- table --------------------------------------------------------
        card = ui.Card(self)
        card.grid(row=1, column=0, sticky="nsew", padx=(0, 16))
        self.table = ui.DataTable(card, [
            ("student_id", "Student ID", 100, "w"), ("full_name", "Full Name", 180, "w"),
            ("department", "Department", 160, "w"), ("course", "Course / Class", 150, "w"),
            ("face", "Face", 90, "w"), ("created", "Registered", 100, "w")],
            on_select=self._on_select, on_double=lambda r: self.edit(),
            empty_text="No students found. Click 'Register Student' to add one.")
        self.table.pack(fill="both", expand=True, padx=1, pady=8)

        # ---- details panel ------------------------------------------------
        self.panel = ui.Card(self, width=310)
        self.panel.grid(row=1, column=1, sticky="ns")
        self.panel.grid_propagate(False)
        self.panel.pack_propagate(False)
        self._build_panel()

    def _build_panel(self):
        p = self.panel
        self.photo = ctk.CTkLabel(p, text="", width=120, height=120, corner_radius=60,
                                  fg_color=C["surface_alt"])
        self.photo.pack(pady=(24, 10))
        self.p_name = ctk.CTkLabel(p, text="No student selected", font=ui.font(15, "semibold"),
                                   text_color=C["text"], wraplength=260)
        self.p_name.pack()
        self.p_id = ctk.CTkLabel(p, text="Select a student in the table", font=ui.font(12),
                                 text_color=C["text_muted"])
        self.p_id.pack()
        self.p_badge = ui.Badge(p, "—", "neutral")
        self.p_badge.pack(pady=(8, 12))
        ctk.CTkFrame(p, height=1, fg_color=C["border"]).pack(fill="x", padx=20)
        info = ctk.CTkFrame(p, fg_color="transparent")
        info.pack(fill="x", padx=22, pady=10)
        info.grid_columnconfigure(1, weight=1)
        self.p_fields = {}
        for i, (k, label) in enumerate([("department", "Department"), ("course", "Course"),
                                        ("email", "Email"), ("phone", "Phone"),
                                        ("samples", "Face samples"), ("attendance", "Days present"),
                                        ("created_at", "Registered")]):
            ctk.CTkLabel(info, text=label, font=ui.font(11), text_color=C["text_soft"],
                         anchor="w").grid(row=i, column=0, sticky="w", pady=3)
            v = ctk.CTkLabel(info, text="—", font=ui.font(12), text_color=C["text"], anchor="e",
                             wraplength=170, justify="right")
            v.grid(row=i, column=1, sticky="e", pady=3)
            self.p_fields[k] = v
        btns = ctk.CTkFrame(p, fg_color="transparent")
        btns.pack(side="bottom", fill="x", padx=20, pady=18)
        self.b_enroll = ui.Button(btns, "Enroll Face", "camera", style="primary",
                                  command=self.enroll)
        self.b_enroll.pack(fill="x", pady=3)
        self.b_history = ui.Button(btns, "Attendance History", "history", command=self.history)
        self.b_history.pack(fill="x", pady=3)
        row = ctk.CTkFrame(btns, fg_color="transparent")
        row.pack(fill="x", pady=3)
        row.grid_columnconfigure((0, 1), weight=1)
        self.b_edit = ui.Button(row, "Edit", "edit", command=self.edit)
        self.b_edit.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.b_delete = ui.Button(row, "Delete", "delete", style="danger", command=self.delete)
        self.b_delete.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self._show_details(None)

    # ------------------------------------------------------------------ #
    def on_show(self):
        self.dept.configure(values=["All Departments"] + self.app.students.departments())
        self.refresh()

    def refresh(self):
        rows = self.app.students.list(self.search.get(), self.dept.get())
        self.table.set_rows(rows, lambda r: (
            r["student_id"], r["full_name"], r["department"], r["course"],
            "Enrolled" if r["face_enrolled"] else "Not enrolled", (r["created_at"] or "")[:10]),
            lambda r: None if r["face_enrolled"] else "warning")
        self.count_lbl.configure(text=f"{len(rows)} student(s)")
        if self.selected:
            self.selected = self.app.students.get(self.selected["id"])
        self._show_details(self.selected)

    def _on_select(self, row):
        self.selected = row
        self._show_details(row)

    def _show_details(self, s: Optional[dict]):
        has = s is not None
        for b in (self.b_enroll, self.b_history, self.b_edit, self.b_delete):
            b.configure_state(has)
        if not has:
            self.photo.configure(image=ui.glyph_image("person", C["text_soft"], 46))
            self.p_name.configure(text="No student selected")
            self.p_id.configure(text="Select a student in the table")
            self.p_badge.set("—", "neutral")
            for v in self.p_fields.values():
                v.configure(text="—")
            return
        img = None
        if s.get("photo_path") and Path(s["photo_path"]).exists():
            try:
                pil = Image.open(s["photo_path"])
                img = ctk.CTkImage(pil, pil, size=(120, 120))
            except Exception:                 # noqa: BLE001
                img = None
        self.photo.configure(image=img or ui.glyph_image("person", C["text_soft"], 46))
        self.p_name.configure(text=s["full_name"])
        self.p_id.configure(text=s["student_id"])
        samples = self.app.students.sample_count(s["id"])
        self.p_badge.set("Face enrolled" if s["face_enrolled"] else "Face not enrolled",
                         "success" if s["face_enrolled"] else "warning")
        present = self.app.db.fetch_one(
            "SELECT COUNT(*) n FROM attendance WHERE student_id=? AND status IN ('Present','Late')",
            (s["id"],))["n"]
        vals = {"department": s["department"], "course": s["course"], "email": s["email"] or "—",
                "phone": s["phone"] or "—", "samples": str(samples), "attendance": str(present),
                "created_at": (s["created_at"] or "")[:16]}
        for k, v in vals.items():
            self.p_fields[k].configure(text=v)
        self.b_enroll.set_text("Re-enroll Face" if s["face_enrolled"] else "Enroll Face")

    # ------------------------------------------------------------------ #
    def open_add_dialog(self):
        d = StudentFormDialog(self, self.app)
        self.wait_window(d)
        if d.result:
            self.app.notify("Student registered successfully.", "success")
            self.selected = self.app.students.get(d.result)
            self.on_show()
            if ui.ask_confirm(self, "Enroll face now?",
                              "Would you like to capture this student's face samples now? "
                              "Face enrollment is required for automatic attendance.",
                              "Enroll Now"):
                self.enroll()

    def edit(self):
        if not self.selected:
            return
        d = StudentFormDialog(self, self.app, self.selected)
        self.wait_window(d)
        if d.result:
            self.app.notify("Student details updated.", "success")
            self.on_show()
            if self.selected["face_enrolled"]:
                self.app.retrain_model()       # refresh names stored with the model

    def delete(self):
        s = self.selected
        if not s:
            return
        if not ui.ask_confirm(self, "Delete student?",
                              f"This permanently deletes {s['full_name']} ({s['student_id']}), "
                              "their face samples and ALL their attendance records.",
                              "Delete", danger=True):
            return
        try:
            had_faces = self.app.students.delete(s["id"])
        except Exception as exc:              # noqa: BLE001
            log.exception("Delete failed")
            ui.show_error(self, "Delete failed", str(exc))
            return
        self.selected = None
        self.app.notify(f"{s['full_name']} was deleted.", "success")
        self.on_show()
        if had_faces:
            self.app.retrain_model()

    def enroll(self):
        s = self.selected
        if not s:
            return
        if self.app.detector is None:
            ui.show_error(self, "Face detector unavailable", self.app.detector_error or "")
            return
        live = self.app.pages.get("live")
        if live is not None:
            live.on_hide()                      # make sure the webcam is free
        d = EnrollmentDialog(self, self.app, s)
        self.wait_window(d)
        self.refresh()

    def history(self):
        if self.selected:
            from ui.attendance_records import StudentHistoryDialog
            StudentHistoryDialog(self, self.app, self.selected)
