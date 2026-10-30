"""
Reports & Analytics page.

Provides overall attendance percentage, Daily / Weekly / Monthly /
Student-wise / Department-wise reports, attendance trend & department charts,
date-range selection, CSV export, and PDF report generation.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

import config
from ui import components as ui
from ui.charts import Chart
from ui.main_window import Page

C = config.COLORS
log = logging.getLogger("facetrack.ui.reports")

REPORT_TABS = [
    ("daily", "Daily Report"),
    ("weekly", "Weekly Report"),
    ("monthly", "Monthly Report"),
    ("student", "Student-wise"),
    ("department", "Department-wise"),
]

TAB_COLUMNS = {
    "daily": [
        ("period", "Date", 120, "w"), ("expected", "Expected", 95, "e"),
        ("present", "Present", 95, "e"), ("late", "Late", 85, "e"),
        ("absent", "Absent", 95, "e"), ("percentage", "Attendance %", 120, "e"),
    ],
    "weekly": [
        ("period", "Week", 180, "w"), ("sessions", "Session Days", 100, "e"),
        ("expected", "Expected", 95, "e"), ("attended", "Attended", 95, "e"),
        ("absent", "Absent", 95, "e"), ("percentage", "Attendance %", 120, "e"),
    ],
    "monthly": [
        ("period", "Month", 160, "w"), ("sessions", "Session Days", 100, "e"),
        ("expected", "Expected", 95, "e"), ("attended", "Attended", 95, "e"),
        ("absent", "Absent", 95, "e"), ("percentage", "Attendance %", 120, "e"),
    ],
    "student": [
        ("roll", "Student ID", 100, "w"), ("full_name", "Student Name", 170, "w"),
        ("department", "Department", 150, "w"), ("sessions", "Sessions", 85, "e"),
        ("attended", "Attended", 85, "e"), ("late", "Late", 75, "e"),
        ("absent", "Absent", 85, "e"), ("percentage", "Attendance %", 110, "e"),
    ],
    "department": [
        ("department", "Department", 200, "w"), ("students", "Students", 95, "e"),
        ("expected", "Expected", 100, "e"), ("attended", "Attended", 100, "e"),
        ("absent", "Absent", 100, "e"), ("percentage", "Attendance %", 120, "e"),
    ],
}


class ReportsPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="rstat")
        self.grid_rowconfigure(2, weight=4)
        self.grid_rowconfigure(3, weight=5)

        self.active_kind = "daily"
        self.current_rows: list[dict] = []

        # ---- Top filter & export bar --------------------------------------
        bar = ui.Card(self)
        bar.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 14))

        ctk.CTkLabel(bar, text="Period", font=ui.font(12, "semibold"),
                     text_color=C["text_muted"]).pack(side="left", padx=(16, 6), pady=12)
        today = date.today()
        self.date_from = ui.entry(bar, "YYYY-MM-DD", width=115)
        self.date_from.insert(0, (today - timedelta(days=29)).isoformat())
        self.date_from.pack(side="left", pady=12)
        ctk.CTkLabel(bar, text="to", font=ui.font(12), text_color=C["text_muted"]).pack(
            side="left", padx=6)
        self.date_to = ui.entry(bar, "YYYY-MM-DD", width=115)
        self.date_to.insert(0, today.isoformat())
        self.date_to.pack(side="left", pady=12)

        for label, days in (("7D", 7), ("30D", 30), ("90D", 90)):
            ui.Button(bar, label, style="ghost", height=32, size=12,
                      command=lambda d=days: self._set_range(d)).pack(side="left", padx=2)

        self.dept = ui.option_menu(bar, ["All Departments"], width=190,
                                   command=lambda v: self.refresh())
        self.dept.pack(side="left", padx=10)
        ui.Button(bar, "Update", "refresh", height=34, command=self.refresh).pack(side="left")

        ui.Button(bar, "Export PDF", "pdf", style="primary",
                  command=self.export_pdf).pack(side="right", padx=(6, 16), pady=12)
        ui.Button(bar, "Export CSV", "export",
                  command=self.export_csv).pack(side="right", padx=6, pady=12)

        # ---- Summary cards ------------------------------------------------
        self.cards = {
            "pct": ui.StatCard(self, "Overall Attendance %", "pie", C["accent"], C["accent_soft"]),
            "sessions": ui.StatCard(self, "Session Days", "calendar", C["info"], C["info_soft"]),
            "attended": ui.StatCard(self, "Total Present / Late", "check",
                                    C["success"], C["success_soft"]),
            "absent": ui.StatCard(self, "Total Absent", "close", C["danger"], C["danger_soft"]),
        }
        for i, card in enumerate(self.cards.values()):
            card.grid(row=1, column=i, sticky="nsew",
                      padx=(0 if i == 0 else 8, 0 if i == 3 else 8))

        # ---- Charts -------------------------------------------------------
        trend_card = ui.Card(self)
        trend_card.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=14, padx=(0, 8))
        ui.SectionHeader(trend_card, "Attendance Rate Over Time",
                         "Session-day attendance percentage").pack(
            fill="x", padx=18, pady=(12, 0))
        self.trend_chart = Chart(trend_card, 5.2, 2.0)
        self.trend_chart.widget.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        dept_card = ui.Card(self)
        dept_card.grid(row=2, column=2, columnspan=2, sticky="nsew", pady=14, padx=(8, 0))
        ui.SectionHeader(dept_card, "Department Comparison",
                         "Average attendance rate by department").pack(
            fill="x", padx=18, pady=(12, 0))
        self.dept_chart = Chart(dept_card, 5.2, 2.0)
        self.dept_chart.widget.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        # ---- Tabbed report table ------------------------------------------
        table_card = ui.Card(self)
        table_card.grid(row=3, column=0, columnspan=4, sticky="nsew")
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(1, weight=1)

        tab_bar = ctk.CTkFrame(table_card, fg_color="transparent")
        tab_bar.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        self.tab_btns: dict[str, ui.Button] = {}
        for kind, title in REPORT_TABS:
            b = ui.Button(
                tab_bar, title,
                style="primary" if kind == self.active_kind else "secondary",
                height=32, size=12, command=lambda k=kind: self.switch_tab(k))
            b.pack(side="left", padx=(0, 6))
            self.tab_btns[kind] = b

        self.table_holder = ctk.CTkFrame(table_card, fg_color=C["surface"])
        self.table_holder.grid(row=1, column=0, sticky="nsew", padx=1, pady=(0, 8))
        self.table_holder.grid_columnconfigure(0, weight=1)
        self.table_holder.grid_rowconfigure(0, weight=1)
        self.tables: dict[str, ui.DataTable] = {}
        for kind, cols in TAB_COLUMNS.items():
            t = ui.DataTable(self.table_holder, cols, height=7,
                             empty_text="No attendance data recorded in the selected date range.")
            self.tables[kind] = t
        self.tables[self.active_kind].grid(row=0, column=0, sticky="nsew")

    # ------------------------------------------------------------------ #
    def _set_range(self, days: int):
        today = date.today()
        self.date_from.delete(0, "end")
        self.date_from.insert(0, (today - timedelta(days=days - 1)).isoformat())
        self.date_to.delete(0, "end")
        self.date_to.insert(0, today.isoformat())
        self.refresh()

    def _validated_dates(self) -> tuple[str, str]:
        df = self.date_from.get().strip() or (date.today() - timedelta(days=29)).isoformat()
        dt = self.date_to.get().strip() or date.today().isoformat()
        try:
            d1 = datetime.strptime(df, "%Y-%m-%d").date()
            d2 = datetime.strptime(dt, "%Y-%m-%d").date()
            if d1 > d2:
                d1, d2 = d2, d1
            return d1.isoformat(), d2.isoformat()
        except ValueError:
            today = date.today()
            return (today - timedelta(days=29)).isoformat(), today.isoformat()

    def switch_tab(self, kind: str) -> None:
        self.tables[self.active_kind].grid_forget()
        self.active_kind = kind
        self.tables[kind].grid(row=0, column=0, sticky="nsew")
        for k, b in self.tab_btns.items():
            st = ui.BUTTON_STYLES["primary" if k == kind else "secondary"]
            b.btn.configure(**st)
        self._load_active_table()

    def on_show(self) -> None:
        self.dept.configure(values=["All Departments"] + self.app.students.departments())
        self.refresh()

    def refresh(self) -> None:
        df, dt = self._validated_dates()
        dept = self.dept.get()
        ov = self.app.reports.overall(df, dt, dept)
        self.cards["pct"].set(f"{ov['percentage']:g}%", f"{df} to {dt}")
        self.cards["sessions"].set(ov["sessions"], f"{ov['expected']} student-sessions expected")
        self.cards["attended"].set(ov["attended"],
                                   f"{ov['present']} present · {ov['late']} late")
        self.cards["absent"].set(ov["absent"], "Across session days")

        daily = self.app.reports.daily(df, dt, dept)
        self.trend_chart.line_trend(
            [r["period"][5:] for r in daily],
            [r["percentage"] for r in daily],
            empty_text="No attendance sessions in this period")

        dept_rows = self.app.reports.department_wise(df, dt)
        self.dept_chart.hbar(
            [r["department"] for r in dept_rows],
            [r["percentage"] for r in dept_rows],
            empty_text="No department attendance data yet")

        self._load_active_table()

    def _load_active_table(self) -> None:
        df, dt = self._validated_dates()
        dept = self.dept.get()
        rows = self.app.reports.build(self.active_kind, df, dt, dept)
        self.current_rows = rows
        cols = TAB_COLUMNS[self.active_kind]
        keys = [c[0] for c in cols]

        def fmt(r):
            out = []
            for k in keys:
                val = r.get(k, "")
                out.append(f"{val:g}%" if k == "percentage" else val)
            return tuple(out)

        self.tables[self.active_kind].set_rows(
            rows, fmt,
            lambda r: "danger" if r.get("percentage", 100) < 75 else None)

    # ------------------------------------------------------------------ #
    def export_csv(self) -> None:
        if not self.current_rows:
            ui.show_info(self, "Nothing to export",
                         "There is no data for the current report tab and date range.")
            return
        df, dt = self._validated_dates()
        export_dir = Path(self.app.db.get_setting("export_dir") or config.EXPORTS_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)
        default = f"report_{self.active_kind}_{df}_to_{dt}.csv"
        path = filedialog.asksaveasfilename(
            parent=self, title="Export Report CSV", initialdir=str(export_dir),
            initialfile=default, defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        out = self.app.reports.export_csv(self.active_kind, self.current_rows, path, df, dt)
        self.app.notify(f"Saved CSV report to {out.name}", "success")

    def export_pdf(self) -> None:
        df, dt = self._validated_dates()
        export_dir = Path(self.app.db.get_setting("export_dir") or config.EXPORTS_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)
        default = f"FaceTrack_Report_{df}_to_{dt}.pdf"
        path = filedialog.asksaveasfilename(
            parent=self, title="Export PDF Report", initialdir=str(export_dir),
            initialfile=default, defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")])
        if not path:
            return
        dept = self.dept.get()

        def done(out, error):
            if error:
                ui.show_error(self, "PDF export failed", str(error))
            else:
                self.app.notify(f"Saved PDF report to {Path(out).name}", "success")

        self.app.run_in_background(
            lambda: self.app.reports.export_pdf(path, df, dt, dept), done)
