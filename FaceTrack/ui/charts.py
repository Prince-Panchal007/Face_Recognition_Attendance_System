"""Matplotlib chart helpers embedded in Tk with the FaceTrack visual style."""
from __future__ import annotations

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

import config  # noqa: E402

C = config.COLORS
matplotlib.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"],
    "font.size": 9,
    "axes.edgecolor": C["border_strong"],
    "axes.labelcolor": C["text_muted"],
    "xtick.color": C["text_muted"],
    "ytick.color": C["text_muted"],
})


class Chart:
    """A figure + canvas pair that can be redrawn with new data."""

    def __init__(self, master, width: float = 5, height: float = 2.4):
        self.fig = Figure(figsize=(width, height), dpi=100, facecolor=C["surface"])
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=master)
        self.widget = self.canvas.get_tk_widget()
        self.widget.configure(bg=C["surface"], highlightthickness=0)

    def _style(self):
        ax = self.ax
        ax.set_facecolor(C["surface"])
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(C["border_strong"])
        ax.tick_params(length=0)
        ax.grid(axis="y", color=C["border"], linewidth=0.8)
        ax.set_axisbelow(True)

    def _empty(self, text: str):
        self.ax.clear()
        self.ax.axis("off")
        self.ax.text(0.5, 0.5, text, ha="center", va="center", color=C["text_soft"],
                     fontsize=10, transform=self.ax.transAxes)

    def bar_trend(self, labels: list[str], values: list[float], totals: list[int] | None = None,
                  ylabel: str = "Present", empty_text: str = "No attendance data yet"):
        self.ax.clear()
        if not labels or not any(values):
            self._empty(empty_text)
        else:
            self._style()
            colors = [C["accent"] if i == len(values) - 1 else "#D9A58F"
                      for i in range(len(values))]
            bars = self.ax.bar(labels, values, color=colors, width=0.55, zorder=2)
            if totals:
                self.ax.plot(labels, totals, color=C["sidebar"], linewidth=1.4, linestyle="--",
                             marker="o", markersize=3, label="Registered", zorder=3)
                self.ax.legend(frameon=False, loc="upper left", fontsize=8)
            top = max(max(values), max(totals) if totals else 0)
            self.ax.set_ylim(0, top * 1.25 + 1)
            for b, v in zip(bars, values):
                if v:
                    self.ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{v:g}",
                                 ha="center", va="bottom", fontsize=8, color=C["text"])
            self.ax.set_ylabel(ylabel)
            self.ax.yaxis.get_major_locator().set_params(integer=True)
        self.fig.tight_layout(pad=1.0)
        self.canvas.draw_idle()

    def line_trend(self, labels: list[str], values: list[float],
                   empty_text: str = "No attendance in the selected period"):
        self.ax.clear()
        if not labels:
            self._empty(empty_text)
        else:
            self._style()
            x = list(range(len(labels)))
            self.ax.plot(x, values, color=C["accent"], linewidth=2, marker="o", markersize=4)
            self.ax.fill_between(x, values, color=C["accent"], alpha=0.08)
            self.ax.set_ylim(0, 105)
            self.ax.set_ylabel("Attendance %")
            step = max(1, len(labels) // 10)
            self.ax.set_xticks(x[::step])
            self.ax.set_xticklabels(labels[::step], fontsize=8)
        self.fig.tight_layout(pad=1.0)
        self.canvas.draw_idle()

    def donut(self, present: int, absent: int, empty_text: str = "No students registered"):
        self.ax.clear()
        self.ax.axis("equal")
        total = present + absent
        if total == 0:
            self._empty(empty_text)
        else:
            self.ax.pie([present, absent] if present or absent else [1],
                        colors=[C["success"], "#E7C9BD"], startangle=90, counterclock=False,
                        wedgeprops=dict(width=0.32, edgecolor=C["surface"], linewidth=2))
            pct = round(present * 100 / total)
            self.ax.text(0, 0.08, f"{pct}%", ha="center", va="center", fontsize=18,
                         color=C["text"], fontweight="bold")
            self.ax.text(0, -0.22, "present", ha="center", va="center", fontsize=9,
                         color=C["text_muted"])
        self.fig.tight_layout(pad=0.4)
        self.canvas.draw_idle()

    def hbar(self, labels: list[str], values: list[float], empty_text: str = "No data"):
        self.ax.clear()
        if not labels:
            self._empty(empty_text)
        else:
            self._style()
            self.ax.grid(axis="x", color=C["border"], linewidth=0.8)
            self.ax.grid(axis="y", visible=False)
            y = list(range(len(labels)))
            self.ax.barh(y, values, color=C["info"], height=0.5, zorder=2)
            self.ax.set_yticks(y)
            self.ax.set_yticklabels(labels, fontsize=8)
            self.ax.invert_yaxis()
            self.ax.set_xlim(0, 105)
            self.ax.set_xlabel("Attendance %")
            for i, v in enumerate(values):
                self.ax.text(v + 1, i, f"{v:g}%", va="center", fontsize=8, color=C["text"])
        self.fig.tight_layout(pad=1.0)
        self.canvas.draw_idle()
