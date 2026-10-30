"""
Settings page.

Configures:
  - Webcam device index + camera probe
  - LBPH recognition threshold (distance)
  - Recognition cooldown (seconds)
  - Consecutive confirmation frames
  - Face sample count per enrollment
  - Optional late check-in cutoff time (HH:MM)
  - Export directory
  - Retrain LBPH model button
  - Database backup & safe restore
  - Application & storage paths information
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

import config
from database.db_manager import DatabaseError
from recognition.camera import list_cameras
from ui import components as ui
from ui.main_window import Page

C = config.COLORS
log = logging.getLogger("facetrack.ui.settings")


class SettingsPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure((0, 1), weight=1, uniform="scol")
        self.grid_rowconfigure(0, weight=1)

        # ---- Left column: Recognition & Camera settings -------------------
        left = ui.Card(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        hdr = ui.SectionHeader(
            left, "Camera & Face Recognition",
            "Tune webcam index, LBPH distance threshold, cooldown and enrollment parameters")
        hdr.pack(fill="x", padx=22, pady=(18, 10))

        form = ctk.CTkFrame(left, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=22)
        form.grid_columnconfigure(1, weight=1)

        # 1. Camera index
        ui.field_label(form, "Webcam Device Index").grid(row=0, column=0, sticky="w", pady=8)
        cam_row = ctk.CTkFrame(form, fg_color="transparent")
        cam_row.grid(row=0, column=1, sticky="e", pady=8)
        self.cam_var = ctk.StringVar(value="0")
        self.cam_menu = ui.option_menu(cam_row, ["0", "1", "2", "3"], width=100,
                                       variable=self.cam_var)
        self.cam_menu.pack(side="left", padx=(0, 8))
        ui.Button(cam_row, "Detect Cameras", "camera", height=34, size=12,
                  command=self.detect_cameras).pack(side="left")

        # 2. Recognition threshold slider
        ui.field_label(form, "Recognition Distance Threshold (lower = stricter)").grid(
            row=1, column=0, sticky="w", pady=8)
        thr_row = ctk.CTkFrame(form, fg_color="transparent")
        thr_row.grid(row=1, column=1, sticky="ew", pady=8)
        self.thr_lbl = ctk.CTkLabel(thr_row, text="50", font=ui.font(13, "semibold"),
                                    text_color=C["accent"], width=36)
        self.thr_lbl.pack(side="right")
        self.thr_slider = ctk.CTkSlider(
            thr_row, from_=30, to=90, number_of_steps=60,
            button_color=C["accent"], button_hover_color=C["accent_hover"],
            progress_color=C["accent"], fg_color=C["border"],
            command=lambda v: self.thr_lbl.configure(text=str(int(round(v)))))
        self.thr_slider.pack(side="right", fill="x", expand=True, padx=(12, 8))

        # 3. Cooldown
        ui.field_label(form, "Recognition Notification Cooldown (seconds)").grid(
            row=2, column=0, sticky="w", pady=8)
        self.cooldown_entry = ui.entry(form, "5", width=120)
        self.cooldown_entry.grid(row=2, column=1, sticky="e", pady=8)

        # 4. Consecutive confirmation frames
        ui.field_label(form, "Confirmation Frames Before Marking").grid(
            row=3, column=0, sticky="w", pady=8)
        self.confirm_var = ctk.StringVar(value="3")
        ui.option_menu(form, ["1", "2", "3", "4", "5"], width=120,
                       variable=self.confirm_var).grid(row=3, column=1, sticky="e", pady=8)

        # 5. Face sample count
        ui.field_label(form, "Samples Captured per Face Enrollment").grid(
            row=4, column=0, sticky="w", pady=8)
        self.samples_var = ctk.StringVar(value="15")
        ui.option_menu(form, ["10", "12", "15", "20", "25"], width=120,
                       variable=self.samples_var).grid(row=4, column=1, sticky="e", pady=8)

        # 6. Late cutoff time
        ui.field_label(form, "Mark 'Late' After Time (HH:MM, optional)").grid(
            row=5, column=0, sticky="w", pady=8)
        self.late_entry = ui.entry(form, "e.g. 09:30 (leave blank to disable)", width=210)
        self.late_entry.grid(row=5, column=1, sticky="e", pady=8)

        # 7. Export location
        ui.field_label(form, "Default Export Folder").grid(row=6, column=0, sticky="w", pady=8)
        exp_row = ctk.CTkFrame(form, fg_color="transparent")
        exp_row.grid(row=6, column=1, columnspan=2, sticky="ew", pady=8)
        self.export_entry = ui.entry(exp_row, width=220)
        self.export_entry.pack(side="left", fill="x", expand=True, padx=(12, 6))
        ui.Button(exp_row, "Browse", "folder", height=34, size=12,
                  command=self.browse_export).pack(side="left")

        foot_left = ctk.CTkFrame(left, fg_color="transparent")
        foot_left.pack(fill="x", padx=22, pady=18)
        ui.Button(foot_left, "Save Settings", "save", style="primary",
                  command=self.save_settings).pack(side="right")
        ui.Button(foot_left, "Reset Defaults", "refresh",
                  command=self.reset_defaults).pack(side="right", padx=8)

        # ---- Right column: Model training, DB backup & app info -----------
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.grid_columnconfigure(0, weight=1)

        # Card A: Model management
        mcard = ui.Card(right)
        mcard.pack(fill="x", pady=(0, 12))
        ui.SectionHeader(
            mcard, "LBPH Face Recognition Model",
            "Rebuild the classifier from all stored student face samples").pack(
            fill="x", padx=20, pady=(16, 6))
        self.model_info = ctk.CTkLabel(
            mcard, text="", font=ui.font(12), text_color=C["text_muted"],
            justify="left", anchor="w")
        self.model_info.pack(fill="x", padx=20, pady=(0, 10))
        mbtns = ctk.CTkFrame(mcard, fg_color="transparent")
        mbtns.pack(fill="x", padx=20, pady=(0, 16))
        ui.Button(mbtns, "Retrain Face Model Now", "sync", style="primary",
                  command=self.retrain).pack(side="left")

        # Card B: Database backup & restore
        dbcard = ui.Card(right)
        dbcard.pack(fill="x", pady=(0, 12))
        ui.SectionHeader(
            dbcard, "Database Backup & Restore",
            "Create a consistent SQLite backup or restore from a previous backup").pack(
            fill="x", padx=20, pady=(16, 8))
        db_btns = ctk.CTkFrame(dbcard, fg_color="transparent")
        db_btns.pack(fill="x", padx=20, pady=(0, 16))
        ui.Button(db_btns, "Backup Database", "save", style="dark",
                  command=self.backup_db).pack(side="left", padx=(0, 8))
        ui.Button(db_btns, "Restore from Backup...", "folder",
                  command=self.restore_db).pack(side="left", padx=8)
        ui.Button(db_btns, "Open Data Folder", "folder", style="ghost",
                  command=self.open_data_folder).pack(side="right")

        # Card C: Application & storage info
        icard = ui.Card(right)
        icard.pack(fill="both", expand=True)
        ui.SectionHeader(
            icard, "Application Information",
            f"{config.APP_FULL_NAME}").pack(fill="x", padx=20, pady=(16, 8))
        info_grid = ctk.CTkFrame(icard, fg_color="transparent")
        info_grid.pack(fill="x", padx=20, pady=(0, 14))
        info_grid.grid_columnconfigure(1, weight=1)
        items = [
            ("Version", f"{config.APP_VERSION} (Offline Desktop Edition)"),
            ("Vision Pipeline", "OpenCV Haar Cascade + LBPH Face Recognizer"),
            ("Database File", str(config.DB_PATH)),
            ("Face Samples Folder", str(config.FACES_DIR)),
            ("Trained Model File", str(config.MODEL_PATH)),
            ("Backups Folder", str(config.BACKUPS_DIR)),
            ("Log File", str(config.LOG_PATH)),
        ]
        for i, (k, v) in enumerate(items):
            ctk.CTkLabel(info_grid, text=k, font=ui.font(11, "semibold"),
                         text_color=C["text_soft"], anchor="w").grid(
                row=i, column=0, sticky="w", pady=3, padx=(0, 12))
            ctk.CTkLabel(info_grid, text=v, font=ui.font(11),
                         text_color=C["text"], anchor="e", wraplength=330,
                         justify="right").grid(row=i, column=1, sticky="e", pady=3)

    # ------------------------------------------------------------------ #
    def on_show(self) -> None:
        s = self.app.db.get_all_settings()
        self.cam_var.set(s.get("camera_index", "0"))
        thr = int(float(s.get("recognition_threshold", "50")))
        self.thr_slider.set(thr)
        self.thr_lbl.configure(text=str(thr))

        self.cooldown_entry.delete(0, "end")
        self.cooldown_entry.insert(0, s.get("recognition_cooldown", "5"))
        self.confirm_var.set(s.get("confirm_frames", "3"))
        self.samples_var.set(s.get("face_sample_count", "15"))

        self.late_entry.delete(0, "end")
        self.late_entry.insert(0, s.get("late_after", ""))

        self.export_entry.delete(0, "end")
        self.export_entry.insert(0, s.get("export_dir", str(config.EXPORTS_DIR)))
        self._refresh_model_info()

    def _refresh_model_info(self) -> None:
        enrolled = self.app.db.fetch_one(
            "SELECT COUNT(*) n FROM students WHERE face_enrolled=1")["n"]
        if self.app.recognizer.is_ready:
            txt = (f"Status: Ready  ·  {len(self.app.recognizer.labels)} enrolled student(s) "
                   f"in model ({enrolled} marked enrolled in database).\n"
                   f"Model file: {config.MODEL_PATH.name}")
        else:
            txt = (f"Status: Not trained ({enrolled} student(s) enrolled in database).\n"
                   f"{self.app.recognizer.error or ''}")
        self.model_info.configure(text=txt)

    # ------------------------------------------------------------------ #
    def detect_cameras(self) -> None:
        self.app.notify("Scanning for connected cameras...", "info", 2000)

        def done(found, error):
            if error or not found:
                self.app.notify("No active cameras responded. Keeping indices 0–3 available.",
                                "warning")
                return
            vals = [str(i) for i in found]
            self.cam_menu.configure(values=vals)
            self.cam_var.set(vals[0])
            self.app.notify(f"Detected camera index(es): {', '.join(vals)}", "success")

        self.app.run_in_background(lambda: list_cameras(3), done)

    def browse_export(self) -> None:
        folder = filedialog.askdirectory(
            parent=self, title="Choose Default Export Folder",
            initialdir=self.export_entry.get().strip() or str(config.EXPORTS_DIR))
        if folder:
            self.export_entry.delete(0, "end")
            self.export_entry.insert(0, folder)

    def save_settings(self) -> None:
        try:
            cd = int(float(self.cooldown_entry.get().strip()))
            if not (0 <= cd <= 300):
                raise ValueError
        except ValueError:
            ui.show_error(self, "Invalid Cooldown",
                          "Cooldown must be a number between 0 and 300 seconds.")
            return
        late = self.late_entry.get().strip()
        if late:
            from datetime import datetime
            try:
                datetime.strptime(late, "%H:%M")
            except ValueError:
                ui.show_error(self, "Invalid Time",
                              "Late cutoff time must be in 24-hour HH:MM format (e.g. 09:30).")
                return
        export_dir = Path(self.export_entry.get().strip() or config.EXPORTS_DIR)
        try:
            export_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            ui.show_error(self, "Invalid Export Folder", str(exc))
            return

        db = self.app.db
        db.set_setting("camera_index", self.cam_var.get())
        db.set_setting("recognition_threshold", int(round(self.thr_slider.get())))
        db.set_setting("recognition_cooldown", cd)
        db.set_setting("confirm_frames", self.confirm_var.get())
        db.set_setting("face_sample_count", self.samples_var.get())
        db.set_setting("late_after", late)
        db.set_setting("export_dir", str(export_dir))
        self.app.notify("Settings saved.", "success")

    def reset_defaults(self) -> None:
        if not ui.ask_confirm(self, "Reset settings?",
                              "Restore all settings to their default values?", "Reset"):
            return
        for k, v in config.DEFAULT_SETTINGS.items():
            self.app.db.set_setting(k, v)
        self.on_show()
        self.app.notify("Default settings restored.", "info")

    def retrain(self) -> None:
        self.app.retrain_model(lambda res, err: self._refresh_model_info())

    def backup_db(self) -> None:
        try:
            dest = self.app.db.backup()
            ui.show_info(self, "Backup created",
                         f"Database backed up to:\n{dest}", "success")
        except Exception as exc:          # noqa: BLE001
            ui.show_error(self, "Backup failed", str(exc))

    def restore_db(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="Select FaceTrack Backup File",
            initialdir=str(config.BACKUPS_DIR),
            filetypes=[("SQLite Database", "*.db"), ("All files", "*.*")])
        if not path:
            return
        if not ui.ask_confirm(
                self, "Restore database?",
                f"Replace the current database with:\n{Path(path).name}?\n\n"
                "An automatic safety backup of your current database will be created first.",
                "Restore"):
            return
        try:
            safety = self.app.db.restore(path)
            self.app.recognizer.load()
            self.app.update_model_status()
            self.on_show()
            ui.show_info(self, "Database restored",
                         f"Database restored successfully.\nSafety copy saved to:\n{safety.name}",
                         "success")
        except DatabaseError as exc:
            ui.show_error(self, "Restore refused", str(exc))

    def open_data_folder(self) -> None:
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(config.DATA_DIR))
        except Exception as exc:          # noqa: BLE001
            self.app.notify(f"Data folder: {config.DATA_DIR} ({exc})", "info")
