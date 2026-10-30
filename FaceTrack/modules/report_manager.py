"""
Reports & analytics computed from real attendance data.

DEFINITIONS (used consistently everywhere)
------------------------------------------
* Session day  : a date in the selected range on which attendance was taken
                 (at least one attendance record exists for that date).
* Expected     : number of students who were registered on that day
                 (registration date <= day, or who have a record that day).
* Attended     : records with status Present or Late.
* Absent       : Expected - Attended (includes students never marked).
* Percentage   : Attended / Expected * 100.
"""
from __future__ import annotations

import csv
import logging
from collections import OrderedDict, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import config
from database.db_manager import DatabaseManager

log = logging.getLogger("facetrack.reports")


def _pct(a: int, b: int) -> float:
    return round(a * 100.0 / b, 1) if b else 0.0


def _daterange(d1: date, d2: date):
    for i in range((d2 - d1).days + 1):
        yield d1 + timedelta(days=i)


class ReportManager:
    def __init__(self, db: DatabaseManager):
        self.db = db

    # ------------------------------------------------------------------ #
    def _load(self, date_from: str, date_to: str, department: str = ""):
        sql = "SELECT id, student_id, full_name, department, course, date(created_at) AS reg FROM students"
        params: list = []
        if department and department != "All Departments":
            sql += " WHERE department = ?"
            params.append(department)
        students = self.db.fetch_all(sql + " ORDER BY full_name COLLATE NOCASE", params)
        ids = {s["id"] for s in students}
        recs = [r for r in self.db.fetch_all(
            "SELECT student_id, attendance_date, status FROM attendance "
            "WHERE attendance_date BETWEEN ? AND ?", (date_from, date_to))
            if r["student_id"] in ids]
        by_day: dict[str, dict[int, str]] = defaultdict(dict)
        for r in recs:
            by_day[r["attendance_date"]][r["student_id"]] = r["status"]
        return students, by_day

    @staticmethod
    def _expected(students, day: str, day_recs: dict) -> list[dict]:
        return [s for s in students if (s["reg"] or day) <= day or s["id"] in day_recs]

    # ------------------------------------------------------------------ #
    def daily(self, date_from: str, date_to: str, department: str = "",
              all_days: bool = False) -> list[dict]:
        """One row per session day (or per calendar day when all_days=True)."""
        students, by_day = self._load(date_from, date_to, department)
        if all_days:
            d1 = datetime.strptime(date_from, "%Y-%m-%d").date()
            d2 = datetime.strptime(date_to, "%Y-%m-%d").date()
            days = [d.isoformat() for d in _daterange(d1, d2)]
        else:
            days = sorted(by_day)
        rows = []
        for day in days:
            recs = by_day.get(day, {})
            expected = len(self._expected(students, day, recs))
            present = sum(1 for s in recs.values() if s == "Present")
            late = sum(1 for s in recs.values() if s == "Late")
            attended = present + late
            rows.append({"period": day, "sessions": 1 if recs else 0, "expected": expected,
                         "present": present, "late": late, "attended": attended,
                         "absent": max(expected - attended, 0),
                         "percentage": _pct(attended, expected) if recs else 0.0})
        return rows

    def _grouped(self, date_from, date_to, department, key_fn) -> list[dict]:
        groups: "OrderedDict[str, dict]" = OrderedDict()
        for r in self.daily(date_from, date_to, department):
            k = key_fn(datetime.strptime(r["period"], "%Y-%m-%d").date())
            g = groups.setdefault(k, {"period": k, "sessions": 0, "expected": 0, "present": 0,
                                      "late": 0, "attended": 0, "absent": 0})
            for f in ("sessions", "expected", "present", "late", "attended", "absent"):
                g[f] += r[f]
        for g in groups.values():
            g["percentage"] = _pct(g["attended"], g["expected"])
        return list(groups.values())

    def weekly(self, date_from, date_to, department=""):
        def key(d: date):
            start = d - timedelta(days=d.weekday())
            return f"{start:%d %b} – {start + timedelta(days=6):%d %b %Y}"
        return self._grouped(date_from, date_to, department, key)

    def monthly(self, date_from, date_to, department=""):
        return self._grouped(date_from, date_to, department, lambda d: d.strftime("%B %Y"))

    def student_wise(self, date_from, date_to, department="") -> list[dict]:
        students, by_day = self._load(date_from, date_to, department)
        rows = []
        for s in students:
            eligible = attended = late = 0
            for day, recs in by_day.items():
                if (s["reg"] or day) <= day or s["id"] in recs:
                    eligible += 1
                    st = recs.get(s["id"])
                    if st in ("Present", "Late"):
                        attended += 1
                    if st == "Late":
                        late += 1
            rows.append({"roll": s["student_id"], "full_name": s["full_name"],
                         "department": s["department"], "course": s["course"],
                         "sessions": eligible, "attended": attended, "late": late,
                         "absent": eligible - attended, "percentage": _pct(attended, eligible)})
        rows.sort(key=lambda r: (-r["percentage"], r["full_name"]))
        return rows

    def department_wise(self, date_from, date_to) -> list[dict]:
        per: dict[str, dict] = {}
        for r in self.student_wise(date_from, date_to):
            d = per.setdefault(r["department"], {"department": r["department"], "students": 0,
                                                 "expected": 0, "attended": 0, "absent": 0})
            d["students"] += 1
            d["expected"] += r["sessions"]
            d["attended"] += r["attended"]
            d["absent"] += r["absent"]
        rows = list(per.values())
        for d in rows:
            d["percentage"] = _pct(d["attended"], d["expected"])
        rows.sort(key=lambda r: r["department"])
        return rows

    def overall(self, date_from, date_to, department="") -> dict:
        daily = self.daily(date_from, date_to, department)
        expected = sum(r["expected"] for r in daily)
        attended = sum(r["attended"] for r in daily)
        return {"sessions": len(daily), "expected": expected, "attended": attended,
                "present": sum(r["present"] for r in daily),
                "late": sum(r["late"] for r in daily),
                "absent": expected - attended, "percentage": _pct(attended, expected)}

    def last_n_days_trend(self, n: int = 7) -> list[dict]:
        """Calendar-day trend for the dashboard (days without records show 0)."""
        today = date.today()
        start = today - timedelta(days=n - 1)
        return self.daily(start.isoformat(), today.isoformat(), all_days=True)

    # ------------------------------------------------------------------ #
    # Export
    # ------------------------------------------------------------------ #
    REPORT_COLUMNS = {
        "daily": [("period", "Date"), ("expected", "Expected"), ("present", "Present"),
                  ("late", "Late"), ("absent", "Absent"), ("percentage", "Attendance %")],
        "weekly": [("period", "Week"), ("sessions", "Sessions"), ("expected", "Expected"),
                   ("attended", "Attended"), ("absent", "Absent"), ("percentage", "Attendance %")],
        "monthly": [("period", "Month"), ("sessions", "Sessions"), ("expected", "Expected"),
                    ("attended", "Attended"), ("absent", "Absent"), ("percentage", "Attendance %")],
        "student": [("roll", "Student ID"), ("full_name", "Name"), ("department", "Department"),
                    ("sessions", "Sessions"), ("attended", "Attended"), ("late", "Late"),
                    ("absent", "Absent"), ("percentage", "Attendance %")],
        "department": [("department", "Department"), ("students", "Students"),
                       ("expected", "Expected"), ("attended", "Attended"),
                       ("absent", "Absent"), ("percentage", "Attendance %")],
    }

    def build(self, kind: str, date_from: str, date_to: str, department: str = "") -> list[dict]:
        if kind == "daily":
            return self.daily(date_from, date_to, department)
        if kind == "weekly":
            return self.weekly(date_from, date_to, department)
        if kind == "monthly":
            return self.monthly(date_from, date_to, department)
        if kind == "student":
            return self.student_wise(date_from, date_to, department)
        if kind == "department":
            return self.department_wise(date_from, date_to)
        raise ValueError(kind)

    def export_csv(self, kind: str, rows: list[dict], path: Path | str,
                   date_from: str, date_to: str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = self.REPORT_COLUMNS[kind]
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow([f"FaceTrack {kind.title()} Attendance Report", f"{date_from} to {date_to}"])
            w.writerow([])
            w.writerow([c[1] for c in cols])
            for r in rows:
                w.writerow([r.get(k, "") for k, _ in cols])
        log.info("Exported %s report to %s", kind, path)
        return path

    def export_pdf(self, path: Path | str, date_from: str, date_to: str,
                   department: str = "") -> Path:
        """Summary PDF: overview, trend chart, daily, department and student tables."""
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                        Table, TableStyle)
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.figure import Figure
        import tempfile

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        ov = self.overall(date_from, date_to, department)
        daily = self.daily(date_from, date_to, department)
        dept = self.department_wise(date_from, date_to)
        students = self.student_wise(date_from, date_to, department)

        styles = getSampleStyleSheet()
        accent = colors.HexColor(config.COLORS["accent"])
        navy = colors.HexColor(config.COLORS["sidebar"])
        h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=navy, fontSize=18)
        h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=accent)
        body = styles["BodyText"]

        def table(data, widths=None):
            t = Table(data, colWidths=widths, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), navy),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAF8F5")]),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E4DED5")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            return t

        story = [Paragraph("FaceTrack – Attendance Report", h1),
                 Paragraph(f"Period: <b>{date_from}</b> to <b>{date_to}</b>"
                           f"{' &nbsp; Department: <b>' + department + '</b>' if department and department != 'All Departments' else ''}"
                           f" &nbsp; Generated: {datetime.now():%Y-%m-%d %H:%M}", body),
                 Spacer(1, 10), Paragraph("Overview", h2),
                 table([["Session days", "Expected", "Present", "Late", "Absent", "Attendance %"],
                        [ov["sessions"], ov["expected"], ov["present"], ov["late"], ov["absent"],
                         f'{ov["percentage"]}%']])]

        tmp_png = None
        if daily:
            fig = Figure(figsize=(7, 2.6), dpi=150)
            ax = fig.add_subplot(111)
            ax.plot([r["period"][5:] for r in daily], [r["percentage"] for r in daily],
                    color=config.COLORS["accent"], marker="o", linewidth=2)
            ax.set_ylim(0, 105)
            ax.set_ylabel("Attendance %")
            ax.grid(axis="y", alpha=0.3)
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
            ax.tick_params(axis="x", labelrotation=45, labelsize=7)
            fig.tight_layout()
            tmp_png = Path(tempfile.gettempdir()) / f"facetrack_chart_{datetime.now():%H%M%S%f}.png"
            fig.savefig(tmp_png)
            story += [Spacer(1, 8), Paragraph("Attendance Trend", h2),
                      Image(str(tmp_png), width=17 * cm, height=6.3 * cm)]

        def add_section(title, kind, rows):
            story.append(Spacer(1, 8))
            story.append(Paragraph(title, h2))
            if not rows:
                story.append(Paragraph("No data for the selected period.", body))
                return
            cols = self.REPORT_COLUMNS[kind]
            data = [[c[1] for c in cols]] + [[r.get(k, "") for k, _ in cols] for r in rows]
            story.append(table(data))

        add_section("Daily Attendance", "daily", daily)
        add_section("Department-wise Attendance", "department", dept)
        add_section("Student-wise Attendance", "student", students)

        doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=1.6 * cm,
                                rightMargin=1.6 * cm, topMargin=1.4 * cm, bottomMargin=1.4 * cm,
                                title="FaceTrack Attendance Report")
        doc.build(story)
        if tmp_png and tmp_png.exists():
            tmp_png.unlink()
        log.info("PDF report written to %s", path)
        return path
