"""
Attendance Records page: search, filter by date / department / status,
view individual student history, mark manual attendance, edit/correct
existing records, delete with confirmation, and export to CSV.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog
from typing import Optional

import customtkinter as ctk

import config
from modules.attendance_manager import STATUSES
from ui import components as ui
from ui.live_attendance import ManualAttendanceDialog
from ui.main_window import Page

C = config.COLORS
log = logging.getLogger("facetrack.ui.records")


class EditAttendanceDialog(ui.Dialog):
    """Correct an existing attendance row (status, check-in time, or date)."""

    def __init__(self, parent, app, record: dict):
        super().__init__(parent, "Correct Attendance Record", 460, 380)
        self.app = app
        self.record = record
        self.result = False

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=26, pady=(20, 6))
        ctk.CTkLabel(head, text=f"{record['full_name']} ({record['roll']})",
                     font=ui.font(16, "semibold"), text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(head, text=f"Record #{record['id']}  ·  {record['department']}",
                     font=ui.font(12), text_color=C["text_muted"]).pack(anchor="w")

        card = ui.Card(self)
        card.pack(fill="both", expand=True, padx=26, pady=10)
        card.grid_columnconfigure((0, 1), weight=1)

        ui.field_label(card, "Date (YYYY-MM-DD)", True).grid(
            row=0, column=0, sticky="w", padx=18, pady=(14, 2))
        self.date_entry = ui.entry(card)
        self.date_entry.insert(0, record["attendance_date"])
        self.date_entry.grid(row=1, column=0, sticky="ew", padx=(18, 8))

        ui.field_label(card, "Check-in Time (HH:MM:SS)").grid(
            row=0, column=1, sticky="w", padx=(8, 18), pady=(14, 2))
        self.time_entry = ui.entry(card)
        self.time_entry.insert(0, record.get("check_in_time") or datetime.now().strftime("%H:%M:%S"))
        self.time_entry.grid(row=1, column=1, sticky="ew", padx=(8, 18))

        ui.field_label(card, "Attendance Status", True).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=18, pady=(12, 2))
        self.status_var = ctk.StringVar(value=record["status"])
        ui.option_menu(card, list(STATUSES), width=200, variable=self.status_var).grid(
            row=3, column=0, sticky="w", padx=18)

        self.err_lbl = ctk.CTkLabel(card, text="", font=ui.font(12), text_color=C["danger"])
        self.err_lbl.grid(row=4, column=0, columnspan=2, sticky="w", padx=18, pady=(10, 12))

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=26, pady=(0, 20))
        ui.Button(foot, "Save Correction", "save", style="primary", command=self.save).pack(side="right")
        ui.Button(foot, "Cancel", command=self.cancel).pack(side="right", padx=8)

    def save(self):
        try:
            self.app.attendance.update_record(
                self.record["id"], self.status_var.get(),
                self.time_entry.get().strip() or None,
                self.date_entry.get().strip())
        except ValueError as exc:
            self.err_lbl.configure(text=str(exc))
            return
        self.result = True
        self.destroy()


class StudentHistoryDialog(ui.Dialog):
    """Modal showing one student's complete attendance history."""

    def __init__(self, parent, app, student: dict):
        super().__init__(parent, f"Attendance History – {student['full_name']}", 760, 480)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=24, pady=(18, 8))
        ctk.CTkLabel(head, text=f"{student['full_name']}  ({student['student_id']})",
                     font=ui.font(16, "semibold"), text_color=C["text"]).pack(side="left")
        rows = app.attendance.list_records(student_pk=student["id"])
        present = sum(1 for r in rows if r["status"] in ("Present", "Late"))
        ui.Badge(head, f"{present} attended  ·  {len(rows)} record(s)", "info").pack(side="right")

        card = ui.Card(self)
        card.pack(fill="both", expand=True, padx=24, pady=6)
        table = ui.DataTable(card, [
            ("id", "ID", 60, "w"), ("date", "Date", 110, "w"), ("time", "Check-in", 100, "w"),
            ("status", "Status", 90, "w"), ("method", "Method", 90, "w"),
            ("conf", "Distance", 85, "e")], height=11,
            empty_text="No attendance records for this student yet.")
        table.pack(fill="both", expand=True, padx=1, pady=8)
        table.set_rows(rows, lambda r: (
            r["id"], r["attendance_date"], r["check_in_time"] or "—", r["status"],
            r["recognition_method"],
            f"{r['confidence']:.1f}" if r["confidence"] is not None else "—"))

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=24, pady=(4, 18))
        ui.Button(foot, "Close", command=self.cancel).pack(side="right")


class AttendanceRecordsPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.current_rows: list[dict] = []

        # ---- Filter bar ---------------------------------------------------
        bar = ui.Card(self)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        r1 = ctk.CTkFrame(bar, fg_color="transparent")
        r1.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(r1, text="", image=ui.glyph_image("search", C["text_soft"], 16)).pack(
            side="left", padx=(0, 6))
        self.search = ui.entry(r1, "Search student name or ID", width=220)
        self.search.pack(side="left")
        self.search.bind("<KeyRelease>", lambda e: self.refresh())

        ctk.CTkLabel(r1, text="From", font=ui.font(12), text_color=C["text_muted"]).pack(
            side="left", padx=(14, 4))
        self.date_from = ui.entry(r1, "YYYY-MM-DD", width=115)
        self.date_from.insert(0, date.today().isoformat())
        self.date_from.pack(side="left")

        ctk.CTkLabel(r1, text="To", font=ui.font(12), text_color=C["text_muted"]).pack(
            side="left", padx=(8, 4))
        self.date_to = ui.entry(r1, "YYYY-MM-DD", width=115)
        self.date_to.insert(0, date.today().isoformat())
        self.date_to.pack(side="left")

        ui.Button(r1, "Today", style="ghost", height=32, size=12,
                  command=self._set_today).pack(side="left", padx=(6, 0))
        ui.Button(r1, "7 Days", style="ghost", height=32, size=12,
                  command=lambda: self._set_days(7)).pack(side="left")
        ui.Button(r1, "All Dates", style="ghost", height=32, size=12,
                  command=self._set_all_dates).pack(side="left")

        ui.Button(r1, "Export CSV", "export", command=self.export_csv).pack(side="right")
        ui.Button(r1, "Manual Entry", "add", style="primary",
                  command=self.manual_entry).pack(side="right", padx=8)

        r2 = ctk.CTkFrame(bar, fg_color="transparent")
        r2.pack(fill="x", padx=16, pady=(0, 12))
        self.dept = ui.option_menu(r2, ["All Departments"], width=190,
                                   command=lambda v: self.refresh())
        self.dept.pack(side="left")
        self.status = ui.option_menu(
            r2, ["All Statuses"] + list(STATUSES), width=150, command=lambda v: self.refresh())
        self.status.pack(side="left", padx=10)

        self.show_absent = ctk.CTkCheckBox(
            r2, text="Include unmarked students as Absent (single-day view)",
            font=ui.font(12), text_color=C["text_muted"], fg_color=C["accent"],
            hover_color=C["accent_hover"], checkbox_width=18, checkbox_height=18,
            command=self.refresh)
        self.show_absent.select()
        self.show_absent.pack(side="left", padx=8)

        ui.Button(r2, "Apply Date Filter", "refresh", height=32, size=12,
                  command=self.refresh).pack(side="left", padx=8)
        self.summary_lbl = ctk.CTkLabel(r2, text="", font=ui.font(12), text_color=C["text_muted"])
        self.summary_lbl.pack(side="right")

        # ---- Table + action footer ----------------------------------------
        card = ui.Card(self)
        card.grid(row=1, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(0, weight=1)

        self.table = ui.DataTable(card, [
            ("id", "Att. ID", 70, "w"),
            ("roll", "Student ID", 100, "w"),
            ("full_name", "Student Name", 180, "w"),
            ("department", "Department", 150, "w"),
            ("date", "Date", 100, "w"),
            ("time", "Check-in Time", 100, "w"),
            ("status", "Status", 90, "w"),
            ("method", "Method", 90, "w"),
            ("conf", "Distance", 80, "e"),
        ], on_select=lambda r: self._sync_actions(),
            on_double=lambda r: self.correct_selected(),
            empty_text="No attendance records match the current filters.")
        self.table.grid(row=0, column=0, sticky="nsew", padx=1, pady=(8, 0))

        foot = ctk.CTkFrame(card, fg_color=C["surface_alt"], corner_radius=0, height=48)
        foot.grid(row=1, column=0, sticky="ew")
        self.b_history = ui.Button(foot, "Student History", "history", height=32, size=12,
                                   command=self.view_history)
        self.b_history.pack(side="left", padx=(14, 6), pady=8)
        self.b_correct = ui.Button(foot, "Correct / Mark Record", "edit", height=32, size=12,
                                   command=self.correct_selected)
        self.b_correct.pack(side="left", padx=6, pady=8)
        self.b_delete = ui.Button(foot, "Delete Record", "delete", style="danger",
                                  height=32, size=12, command=self.delete_selected)
        self.b_delete.pack(side="left", padx=6, pady=8)

    # ------------------------------------------------------------------ #
    def _set_today(self):
        t = date.today().isoformat()
        self.date_from.delete(0, "end")
        self.date_from.insert(0, t)
        self.date_to.delete(0, "end")
        self.date_to.insert(0, t)
        self.refresh()

    def _set_days(self, n: int):
        t = date.today()
        self.date_from.delete(0, "end")
        self.date_from.insert(0, (t - timedelta(days=n - 1)).isoformat())
        self.date_to.delete(0, "end")
        self.date_to.insert(0, t.isoformat())
        self.refresh()

    def _set_all_dates(self):
        self.date_from.delete(0, "end")
        self.date_to.delete(0, "end")
        self.refresh()

    def on_show(self) -> None:
        self.dept.configure(values=["All Departments"] + self.app.students.departments())
        self.refresh()

    def refresh(self) -> None:
        df = self.date_from.get().strip()
        dt = self.date_to.get().strip()
        rows = self.app.attendance.list_records(
            search=self.search.get(), date_from=df, date_to=dt,
            department=self.dept.get(), status=self.status.get(),
            include_unmarked=bool(self.show_absent.get()))
        self.current_rows = rows
        self.table.set_rows(
            rows,
            lambda r: (
                r["id"] or "—", r["roll"], r["full_name"], r["department"],
                r["attendance_date"], r["check_in_time"] or "—", r["status"],
                r["recognition_method"],
                f"{r['confidence']:.1f}" if r["confidence"] is not None else "—"),
            lambda r: ("danger" if r["status"] == "Absent"
                       else "warning" if r["status"] == "Late" else None))
        present = sum(1 for r in rows if r["status"] == "Present")
        late = sum(1 for r in rows if r["status"] == "Late")
        absent = sum(1 for r in rows if r["status"] == "Absent")
        self.summary_lbl.configure(
            text=f"{len(rows)} row(s)  ·  Present {present}  ·  Late {late}  ·  Absent {absent}")
        self._sync_actions()

    def _sync_actions(self):
        sel = self.table.selected()
        self.b_history.configure_state(sel is not None)
        self.b_correct.configure_state(sel is not None)
        self.b_delete.configure_state(bool(sel and sel.get("id")))

    # ------------------------------------------------------------------ #
    def manual_entry(self):
        sel = self.table.selected()
        d = ManualAttendanceDialog(
            self, self.app,
            preselect_pk=sel["student_pk"] if sel else None,
            default_date=self.date_from.get().strip() or None)
        self.wait_window(d)
        if d.result:
            self.app.notify(d.result.message, "success")
            self.refresh()

    def correct_selected(self):
        sel = self.table.selected()
        if not sel:
            return
        if not sel.get("id"):
            # Unmarked student row -> open manual dialog pre-filled for this student
            d = ManualAttendanceDialog(self, self.app, preselect_pk=sel["student_pk"],
                                       default_date=sel["attendance_date"])
            self.wait_window(d)
            if d.result:
                self.app.notify(d.result.message, "success")
                self.refresh()
            return
        d = EditAttendanceDialog(self, self.app, sel)
        self.wait_window(d)
        if d.result:
            self.app.notify("Attendance record updated.", "success")
            self.refresh()

    def delete_selected(self):
        sel = self.table.selected()
        if not sel or not sel.get("id"):
            return
        if not ui.ask_confirm(
                self, "Delete attendance record?",
                f"Delete record #{sel['id']} for {sel['full_name']} on {sel['attendance_date']}?",
                "Delete", danger=True):
            return
        self.app.attendance.delete_record(sel["id"])
        self.app.notify("Attendance record deleted.", "success")
        self.refresh()

    def view_history(self):
        sel = self.table.selected()
        if not sel:
            return
        student = self.app.students.get(sel["student_pk"])
        if student:
            StudentHistoryDialog(self, self.app, student)

    def export_csv(self):
        if not self.current_rows:
            ui.show_info(self, "Nothing to export", "There are no rows in the current view.")
            return
        export_dir = Path(self.app.db.get_setting("export_dir") or config.EXPORTS_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)
        default = f"attendance_{datetime.now():%Y%m%d_%H%M%S}.csv"
        path = filedialog.asksaveasfilename(
            parent=self, title="Export Attendance CSV", initialdir=str(export_dir),
            initialfile=default, defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        out = self.app.attendance.export_csv(self.current_rows, path)
        self.app.notify(f"Exported {len(self.current_rows)} rows to {out.name}", "success")
