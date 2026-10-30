"""Dashboard: live statistics, 7-day trend, present/absent split and recent activity."""
from __future__ import annotations

from datetime import datetime

import customtkinter as ctk

import config
from ui import components as ui
from ui.charts import Chart
from ui.main_window import Page

C = config.COLORS


class DashboardPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="stats")
        self.grid_rowconfigure(2, weight=5)
        self.grid_rowconfigure(3, weight=4)

        # ---- welcome strip with primary call-to-action -------------------
        strip = ui.Card(self)
        strip.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 16))
        left = ctk.CTkFrame(strip, fg_color="transparent")
        left.pack(side="left", padx=20, pady=14, fill="x", expand=True)
        self.greet = ctk.CTkLabel(left, text="", font=ui.font(16, "semibold"),
                                  text_color=C["text"], anchor="w")
        self.greet.pack(anchor="w")
        self.summary = ctk.CTkLabel(left, text="", font=ui.font(12), text_color=C["text_muted"],
                                    anchor="w")
        self.summary.pack(anchor="w")
        ui.Button(strip, "Start Attendance", "play", style="primary", height=40,
                  command=lambda: app.show_page("live")).pack(side="right", padx=(8, 20))
        ui.Button(strip, "Register Student", "add", height=40,
                  command=self._open_register_student).pack(side="right")

        # ---- stat cards ---------------------------------------------------
        self.cards = {
            "total": ui.StatCard(self, "Registered Students", "students", C["info"], C["info_soft"]),
            "present": ui.StatCard(self, "Present Today", "check", C["success"], C["success_soft"]),
            "absent": ui.StatCard(self, "Absent Today", "close", C["danger"], C["danger_soft"]),
            "pct": ui.StatCard(self, "Attendance Rate", "pie", C["accent"], C["accent_soft"]),
        }
        for i, card in enumerate(self.cards.values()):
            card.grid(row=1, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0 if i == 3 else 8))

        # ---- charts -------------------------------------------------------
        trend = ui.Card(self)
        trend.grid(row=2, column=0, columnspan=3, sticky="nsew", pady=16, padx=(0, 8))
        ui.SectionHeader(trend, "Attendance Trend", "Students present over the last 7 days").pack(
            fill="x", padx=18, pady=(14, 0))
        self.trend_chart = Chart(trend, 6, 2.2)
        self.trend_chart.widget.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        split = ui.Card(self)
        split.grid(row=2, column=3, sticky="nsew", pady=16, padx=(8, 0))
        ui.SectionHeader(split, "Today", "Present vs absent").pack(fill="x", padx=18, pady=(14, 0))
        self.donut = Chart(split, 2.4, 2.0)
        self.donut.widget.pack(fill="both", expand=True, padx=10)
        legend = ctk.CTkFrame(split, fg_color="transparent")
        legend.pack(pady=(0, 12))
        self.leg_present = self._legend(legend, C["success"], "Present 0")
        self.leg_absent = self._legend(legend, "#E7C9BD", "Absent 0")

        # ---- tables -------------------------------------------------------
        recent = ui.Card(self)
        recent.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=(0, 8))
        hdr = ui.SectionHeader(recent, "Recent Attendance", "Latest check-ins")
        hdr.pack(fill="x", padx=18, pady=(14, 8))
        ui.Button(hdr.actions, "View all", style="ghost", height=28, size=12,
                  command=lambda: app.show_page("records")).pack()
        self.recent_table = ui.DataTable(recent, [
            ("full_name", "Student", 170, "w"), ("roll", "ID", 90, "w"),
            ("date", "Date", 95, "w"), ("time", "Time", 80, "w"),
            ("method", "Method", 70, "w")], height=5,
            empty_text="No attendance has been recorded yet.")
        self.recent_table.pack(fill="both", expand=True, padx=1, pady=(0, 8))

        students = ui.Card(self)
        students.grid(row=3, column=2, columnspan=2, sticky="nsew", padx=(8, 0))
        hdr2 = ui.SectionHeader(students, "Recently Registered", "Newest students")
        hdr2.pack(fill="x", padx=18, pady=(14, 8))
        ui.Button(hdr2.actions, "Manage", style="ghost", height=28, size=12,
                  command=lambda: app.show_page("students")).pack()
        self.student_table = ui.DataTable(students, [
            ("full_name", "Name", 160, "w"), ("department", "Department", 140, "w"),
            ("face", "Face", 80, "w")], height=5,
            empty_text="No students registered yet. Click 'Register Student'.")
        self.student_table.pack(fill="both", expand=True, padx=1, pady=(0, 8))

    def _legend(self, parent, color, text):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(side="left", padx=8)
        ctk.CTkFrame(f, width=10, height=10, corner_radius=2, fg_color=color).pack(side="left", padx=(0, 6))
        lbl = ctk.CTkLabel(f, text=text, font=ui.font(11), text_color=C["text_muted"])
        lbl.pack(side="left")
        return lbl

    def _open_register_student(self):
        self.app.show_page("students")
        self.app.pages["students"].open_add_dialog()

    # ------------------------------------------------------------------ #
    def on_show(self) -> None:
        s = self.app.attendance.today_summary()
        h = datetime.now().hour
        part = "morning" if h < 12 else "afternoon" if h < 17 else "evening"
        self.greet.configure(text=f"Good {part}")
        enrolled = self.app.db.fetch_one(
            "SELECT COUNT(*) n FROM students WHERE face_enrolled=1")["n"]
        if s["total"] == 0:
            msg = "No students registered yet – register a student and enroll their face to begin."
        else:
            msg = (f"{s['present']} of {s['total']} students have checked in today  ·  "
                   f"{enrolled} face-enrolled  ·  "
                   f"model {'ready' if self.app.recognizer.is_ready else 'not trained'}")
        self.summary.configure(text=msg)

        self.cards["total"].set(s["total"], f"{enrolled} with face enrolled")
        self.cards["present"].set(s["present"], f"{s['face']} by face · {s['late']} late")
        self.cards["absent"].set(s["absent"], "Not yet checked in" if s["total"] else "—")
        self.cards["pct"].set(f"{s['percentage']:g}%", "Of registered students")

        trend = self.app.reports.last_n_days_trend(7)
        labels = [datetime.strptime(r["period"], "%Y-%m-%d").strftime("%a %d") for r in trend]
        self.trend_chart.bar_trend(labels, [r["attended"] for r in trend],
                                   [r["expected"] for r in trend] if s["total"] else None,
                                   empty_text="No attendance recorded in the last 7 days")
        self.donut.donut(s["present"], s["absent"])
        self.leg_present.configure(text=f"Present {s['present']}")
        self.leg_absent.configure(text=f"Absent {s['absent']}")

        self.recent_table.set_rows(
            self.app.attendance.recent(12),
            lambda r: (r["full_name"], r["roll"], r["attendance_date"], r["check_in_time"],
                       r["recognition_method"]))
        self.student_table.set_rows(
            self.app.students.recent(12),
            lambda r: (r["full_name"], r["department"],
                       "Enrolled" if r["face_enrolled"] else "Pending"),
            lambda r: "success" if r["face_enrolled"] else "warning")
