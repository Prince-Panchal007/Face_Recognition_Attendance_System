"""
FaceTrack – Desktop UI Layer (`ui.py`).

Consolidates the complete CustomTkinter user interface in one module:
  1. Reusable UI Components (icons, buttons, cards, stat tiles, tables, toasts, dialogs)
  2. Embedded Matplotlib Charts (`Chart`) and OpenCV Video Canvas (`VideoView`)
  3. Modal Dialogs (`StudentFormDialog`, `EnrollmentDialog`, `ManualAttendanceDialog`,
     `EditAttendanceDialog`, `StudentHistoryDialog`)
  4. Application Pages (`DashboardPage`, `LiveAttendancePage`, `StudentsPage`,
     `AttendanceRecordsPage`, `ReportsPage`, `SettingsPage`)
  5. Main Window (`App`) with sidebar navigation, live clock, and thread helper
"""
from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
import tkinter.font as tkfont
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable, Iterable, Optional

import cv2
import customtkinter as ctk
import matplotlib
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

import config  # noqa: E402
from database import (  # noqa: E402
    STATUSES,
    AttendanceManager,
    DatabaseError,
    DatabaseManager,
    ReportManager,
    StudentManager,
    ValidationError,
)
from vision import (  # noqa: E402
    CameraStream,
    EnrollmentSession,
    FaceDetector,
    FaceDetectorError,
    FaceRecognizer,
    LiveRecognitionEngine,
    list_cameras,
    train_model,
)

C = config.COLORS
log = logging.getLogger("facetrack.ui")
MIN_SAMPLES = 5

matplotlib.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"],
    "font.size": 9,
    "axes.edgecolor": C["border_strong"],
    "axes.labelcolor": C["text_muted"],
    "xtick.color": C["text_muted"],
    "ytick.color": C["text_muted"],
})

# =========================================================================== #
# 1. Fonts, Icons & Reusable UI Components
# =========================================================================== #
_ICON_FONT: Optional[str] = None
_GLYPH_CACHE: dict = {}
_STYLE_DONE = False

ICONS = {
    "dashboard": "\uE80F", "live": "\uE714", "students": "\uE716", "records": "\uE787",
    "reports": "\uE9F9", "settings": "\uE713", "add": "\uE710", "edit": "\uE70F",
    "delete": "\uE74D", "search": "\uE721", "export": "\uE896", "save": "\uE74E",
    "play": "\uE768", "pause": "\uE769", "stop": "\uE71A", "refresh": "\uE72C",
    "sync": "\uE895", "check": "\uE8FB", "close": "\uE711", "clock": "\uE917",
    "switch": "\uE8AB", "warning": "\uE7BA", "info": "\uE946", "camera": "\uE722",
    "person": "\uE77B", "folder": "\uED25", "history": "\uE81C", "card": "\uE8D4",
    "pie": "\uEB05", "pulse": "\uE9D9", "cap": "\uE7BE", "list": "\uE8FD",
    "calendar": "\uE787", "shield": "\uE7EF", "pdf": "\uE8A5", "chart": "\uE9D2",
}


def icon_font_family() -> Optional[str]:
    global _ICON_FONT
    if _ICON_FONT is None:
        fams = set(tkfont.families())
        _ICON_FONT = next(
            (f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in fams), "")
    return _ICON_FONT or None


def icon(name: str) -> str:
    return ICONS.get(name, "") if icon_font_family() else ""


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    family = config.FONT_FAMILY_SEMI if weight == "semibold" else config.FONT_FAMILY
    return ctk.CTkFont(family=family, size=size,
                       weight="bold" if weight == "bold" else "normal")


def icon_font(size: int = 14) -> ctk.CTkFont:
    return ctk.CTkFont(family=icon_font_family() or config.FONT_FAMILY, size=size)


def _glyph_image(glyph: str, color: str, size: int) -> Optional[ctk.CTkImage]:
    key = (glyph, color, size)
    if key in _GLYPH_CACHE:
        return _GLYPH_CACHE[key]
    path = next((p for p in (r"C:\Windows\Fonts\SegoeIcons.ttf",
                             r"C:\Windows\Fonts\segmdl2.ttf") if os.path.exists(p)), None)
    if path is None:
        return None
    px = size * 3
    fnt = ImageFont.truetype(path, px)
    img = Image.new("RGBA", (px + 6, px + 6), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((3, 3), glyph, font=fnt, fill=color)
    img = img.crop(img.getbbox() or (0, 0, px, px))
    w, h = img.size
    side = max(w, h)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(img, ((side - w) // 2, (side - h) // 2))
    out = ctk.CTkImage(light_image=sq, dark_image=sq, size=(size, size))
    _GLYPH_CACHE[key] = out
    return out


def glyph_image(name: str, color: str, size: int) -> Optional[ctk.CTkImage]:
    g = ICONS.get(name)
    return _glyph_image(g, color, size) if g else None


BUTTON_STYLES = {
    "primary": dict(fg_color=C["accent"], hover_color=C["accent_hover"], text_color="#FFFFFF",
                    border_width=0),
    "secondary": dict(fg_color=C["surface"], hover_color=C["surface_alt"], text_color=C["text"],
                      border_width=1, border_color=C["border_strong"]),
    "dark": dict(fg_color=C["sidebar"], hover_color=C["sidebar_active"], text_color="#FFFFFF",
                 border_width=0),
    "danger": dict(fg_color=C["surface"], hover_color=C["danger_soft"], text_color=C["danger"],
                   border_width=1, border_color="#E3B8B4"),
    "success": dict(fg_color=C["success"], hover_color="#336849", text_color="#FFFFFF",
                    border_width=0),
    "ghost": dict(fg_color="transparent", hover_color=C["accent_soft"], text_color=C["accent"],
                  border_width=0),
}


class Button(ctk.CTkFrame):
    def __init__(self, master, text: str = "", icon_name: str = "", command=None,
                 style: str = "secondary", width: int = 0, height: int = 36, size: int = 13):
        super().__init__(master, fg_color="transparent")
        st = BUTTON_STYLES[style]
        glyph = icon(icon_name) if icon_name else ""
        label = f"{glyph}   {text}" if glyph and text else (glyph or text)
        self.btn = ctk.CTkButton(self, text=label, command=command, height=height,
                                 width=width or 0, corner_radius=6, font=font(size, "semibold"),
                                 **st)
        if glyph:
            self.btn.configure(text=text if text else glyph,
                               font=font(size, "semibold") if text else icon_font(size + 1))
            if text:
                self.btn.configure(image=_glyph_image(glyph, st["text_color"], size + 1),
                                   compound="left")
        self.btn.pack(fill="both", expand=True)

    def configure_state(self, enabled: bool) -> None:
        self.btn.configure(state="normal" if enabled else "disabled")

    def set_text(self, text: str) -> None:
        self.btn.configure(text=text)


class Card(ctk.CTkFrame):
    def __init__(self, master, padding: int = 18, **kw):
        kw.setdefault("fg_color", C["surface"])
        kw.setdefault("corner_radius", 8)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", C["border"])
        super().__init__(master, **kw)
        self.padding = padding


class SectionHeader(ctk.CTkFrame):
    def __init__(self, master, title: str, subtitle: str = ""):
        super().__init__(master, fg_color="transparent")
        left = ctk.CTkFrame(self, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(left, text=title, font=font(15, "semibold"), text_color=C["text"],
                     anchor="w").pack(anchor="w")
        self.subtitle = ctk.CTkLabel(left, text=subtitle, font=font(12),
                                     text_color=C["text_muted"], anchor="w")
        if subtitle:
            self.subtitle.pack(anchor="w")
        self.actions = ctk.CTkFrame(self, fg_color="transparent")
        self.actions.pack(side="right")


class StatCard(Card):
    def __init__(self, master, label: str, icon_name: str, tint: str, tint_soft: str):
        super().__init__(master)
        self.grid_columnconfigure(1, weight=1)
        badge = ctk.CTkLabel(self, text="", width=42, height=42, corner_radius=8,
                             fg_color=tint_soft, image=glyph_image(icon_name, tint, 20))
        badge.grid(row=0, column=0, rowspan=2, padx=(18, 14), pady=18, sticky="n")
        ctk.CTkLabel(self, text=label.upper(), font=font(11, "semibold"),
                     text_color=C["text_muted"], anchor="w").grid(
            row=0, column=1, sticky="sw", pady=(16, 0))
        self.value = ctk.CTkLabel(self, text="0", font=font(26, "semibold"),
                                  text_color=C["text"], anchor="w")
        self.value.grid(row=1, column=1, sticky="nw")
        self.caption = ctk.CTkLabel(self, text="", font=font(11),
                                    text_color=C["text_soft"], anchor="w")
        self.caption.grid(row=2, column=0, columnspan=2, sticky="w", padx=18, pady=(0, 14))

    def set(self, value, caption: str = "") -> None:
        self.value.configure(text=str(value))
        self.caption.configure(text=caption)


class Badge(ctk.CTkLabel):
    STYLES = {
        "success": (C["success_soft"], C["success"]),
        "danger": (C["danger_soft"], C["danger"]),
        "warning": (C["warning_soft"], C["warning"]),
        "info": (C["info_soft"], C["info"]),
        "neutral": (C["surface_alt"], C["text_muted"]),
        "accent": (C["accent_soft"], C["accent"]),
    }

    def __init__(self, master, text: str, kind: str = "neutral"):
        bg, fg = self.STYLES[kind]
        super().__init__(master, text=f"  {text}  ", fg_color=bg, text_color=fg,
                         corner_radius=4, font=font(11, "semibold"), height=22)

    def set(self, text: str, kind: str) -> None:
        bg, fg = self.STYLES[kind]
        self.configure(text=f"  {text}  ", fg_color=bg, text_color=fg)


def setup_ttk_style(root) -> None:
    global _STYLE_DONE
    if _STYLE_DONE:
        return
    scale = ctk.ScalingTracker.get_widget_scaling(root)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("FT.Treeview", background=C["surface"], fieldbackground=C["surface"],
                    foreground=C["text"], rowheight=int(32 * scale), borderwidth=0,
                    font=(config.FONT_FAMILY, 10))
    style.configure("FT.Treeview.Heading", background=C["surface_alt"],
                    foreground=C["text_muted"], font=(config.FONT_FAMILY_SEMI, 9),
                    relief="flat", borderwidth=0, padding=(8, int(7 * scale)))
    style.map("FT.Treeview.Heading", background=[("active", C["bg"])])
    style.map("FT.Treeview", background=[("selected", C["accent_soft"])],
              foreground=[("selected", C["text"])])
    style.layout("FT.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.configure("FT.Vertical.TScrollbar", background=C["border"],
                    troughcolor=C["surface"], bordercolor=C["surface"],
                    arrowcolor=C["text_muted"], relief="flat", gripcount=0)
    _STYLE_DONE = True


class DataTable(ctk.CTkFrame):
    def __init__(self, master, columns: list[tuple], height: int = 10,
                 on_select: Optional[Callable] = None,
                 on_double: Optional[Callable] = None,
                 empty_text: str = "No records to display."):
        super().__init__(master, fg_color=C["surface"])
        setup_ttk_style(self.winfo_toplevel())
        self.columns = columns
        self.keys = [c[0] for c in columns]
        self.rows: dict[str, dict] = {}
        self.tree = ttk.Treeview(self, columns=self.keys, show="headings", height=height,
                                 style="FT.Treeview", selectmode="browse")
        scale = ctk.ScalingTracker.get_widget_scaling(self.winfo_toplevel())
        for key, heading, width, anchor in columns:
            self.tree.heading(key, text=heading.upper(), anchor=anchor,
                              command=lambda k=key: self._sort(k))
            self.tree.column(key, width=int(width * scale), minwidth=int(50 * scale),
                             anchor=anchor, stretch=True)
        self.tree.tag_configure("odd", background=C["surface_alt"])
        self.tree.tag_configure("muted", foreground=C["text_soft"])
        self.tree.tag_configure("danger", foreground=C["danger"])
        self.tree.tag_configure("success", foreground=C["success"])
        self.tree.tag_configure("warning", foreground=C["warning"])
        sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview,
                           style="FT.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.empty = ctk.CTkLabel(self, text=empty_text, font=font(12),
                                  text_color=C["text_soft"], fg_color=C["surface"])
        self._sort_desc = False
        if on_select:
            self.tree.bind("<<TreeviewSelect>>", lambda e: on_select(self.selected()))
        if on_double:
            self.tree.bind("<Double-1>", lambda e: self.selected() and on_double(self.selected()))

    def set_rows(self, rows: Iterable[dict],
                 formatter: Optional[Callable[[dict], tuple]] = None,
                 tagger: Optional[Callable[[dict], str]] = None) -> None:
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        rows = list(rows)
        for i, r in enumerate(rows):
            values = formatter(r) if formatter else tuple(r.get(k, "") for k in self.keys)
            values = tuple("—" if v is None or v == "" else v for v in values)
            tags = ["odd"] if i % 2 else []
            if tagger:
                t = tagger(r)
                if t:
                    tags.append(t)
            iid = self.tree.insert("", "end", values=values, tags=tags)
            self.rows[iid] = r
        if rows:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.55, anchor="center")

    def selected(self) -> Optional[dict]:
        sel = self.tree.selection()
        return self.rows.get(sel[0]) if sel else None

    def _sort(self, key: str) -> None:
        items = [(self.tree.set(i, key), i) for i in self.tree.get_children("")]

        def conv(v):
            try:
                return (0, float(str(v).rstrip("%")))
            except ValueError:
                return (1, str(v).lower())
        items.sort(key=lambda t: conv(t[0]), reverse=self._sort_desc)
        self._sort_desc = not self._sort_desc
        for idx, (_, iid) in enumerate(items):
            self.tree.move(iid, "", idx)
            tags = [t for t in self.tree.item(iid, "tags") if t != "odd"]
            if idx % 2:
                tags.append("odd")
            self.tree.item(iid, tags=tags)


def entry(master, placeholder: str = "", width: int = 200, **kw) -> ctk.CTkEntry:
    return ctk.CTkEntry(master, placeholder_text=placeholder, width=width, height=36,
                        corner_radius=6, border_width=1, border_color=C["border_strong"],
                        fg_color=C["surface"], text_color=C["text"],
                        placeholder_text_color=C["text_soft"], font=font(13), **kw)


def option_menu(master, values: list[str], width: int = 180, command=None,
                variable=None) -> ctk.CTkOptionMenu:
    return ctk.CTkOptionMenu(
        master, values=values, width=width, height=36, corner_radius=6,
        fg_color=C["surface"], button_color=C["surface_alt"],
        button_hover_color=C["border"], text_color=C["text"],
        dropdown_fg_color=C["surface"], dropdown_hover_color=C["accent_soft"],
        dropdown_text_color=C["text"], font=font(13), dropdown_font=font(13),
        command=command, variable=variable, dynamic_resizing=False)


def combo(master, values: list[str], width: int = 200, variable=None) -> ctk.CTkComboBox:
    return ctk.CTkComboBox(
        master, values=values, width=width, height=36, corner_radius=6,
        border_width=1, border_color=C["border_strong"], fg_color=C["surface"],
        button_color=C["surface_alt"], button_hover_color=C["border"],
        text_color=C["text"], dropdown_fg_color=C["surface"],
        dropdown_hover_color=C["accent_soft"], dropdown_text_color=C["text"],
        font=font(13), dropdown_font=font(13), variable=variable)


def field_label(master, text: str, required: bool = False) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, text=text + ("  *" if required else ""),
                        font=font(12, "semibold"), text_color=C["text_muted"], anchor="w")


class Toast:
    KINDS = {"success": (C["success"], "check"), "error": (C["danger"], "warning"),
             "warning": (C["warning"], "warning"), "info": (C["info"], "info")}
    _active: list = []

    @classmethod
    def show(cls, root, message: str, kind: str = "info", duration: int = 3200) -> None:
        color, ic = cls.KINDS.get(kind, cls.KINDS["info"])
        frame = ctk.CTkFrame(root, fg_color=C["sidebar"], corner_radius=8, border_width=0)
        bar = ctk.CTkFrame(frame, fg_color=color, width=5, corner_radius=0)
        bar.pack(side="left", fill="y")
        ctk.CTkLabel(frame, text="", image=glyph_image(ic, color, 18)).pack(
            side="left", padx=(12, 8), pady=12)
        ctk.CTkLabel(frame, text=message, font=font(12), text_color="#FFFFFF",
                     wraplength=320, justify="left", anchor="w").pack(
            side="left", padx=(0, 16), pady=12)
        cls._active.append(frame)
        cls._relayout()

        def close():
            if frame in cls._active:
                cls._active.remove(frame)
            frame.destroy()
            cls._relayout()
        root.after(duration, close)

    @classmethod
    def _relayout(cls):
        y = -24
        for f in reversed(cls._active):
            try:
                f.place(relx=1.0, rely=1.0, x=-24, y=y, anchor="se")
                f.update_idletasks()
                y -= f.winfo_height() + 10
            except tk.TclError:
                pass


class Dialog(ctk.CTkToplevel):
    def __init__(self, parent, title: str, width: int = 480, height: int = 300):
        super().__init__(parent)
        self.title(title)
        self.configure(fg_color=C["bg"])
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.result = None
        self.update_idletasks()
        top = parent.winfo_toplevel()
        scale = ctk.ScalingTracker.get_window_scaling(top)
        x = top.winfo_rootx() + (top.winfo_width() - int(width * scale)) // 2
        y = top.winfo_rooty() + (top.winfo_height() - int(height * scale)) // 2
        self.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.after(150, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
            self.lift()
        except tk.TclError:
            pass

    def cancel(self):
        self.result = None
        self.destroy()


class MessageDialog(Dialog):
    KINDS = {"confirm": ("warning", C["warning"]), "danger": ("delete", C["danger"]),
             "info": ("info", C["info"]), "error": ("warning", C["danger"]),
             "success": ("check", C["success"])}

    def __init__(self, parent, title: str, message: str, kind: str = "info",
                 ok_text: str = "OK", cancel_text: Optional[str] = None):
        lines = message.count("\n") + len(message) // 60
        super().__init__(parent, title, 460, min(200 + lines * 18, 460))
        ic, color = self.KINDS[kind]
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=26, pady=(24, 10))
        ctk.CTkLabel(
            body, text="", width=44, height=44, corner_radius=22,
            fg_color=Badge.STYLES.get({"confirm": "warning", "danger": "danger",
                                       "info": "info", "error": "danger",
                                       "success": "success"}[kind])[0],
            image=glyph_image(ic, color, 20)).pack(side="left", anchor="n", padx=(0, 16))
        txt = ctk.CTkFrame(body, fg_color="transparent")
        txt.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(txt, text=title, font=font(15, "semibold"), text_color=C["text"],
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(txt, text=message, font=font(12), text_color=C["text_muted"],
                     anchor="w", justify="left", wraplength=320).pack(anchor="w", pady=(6, 0))
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=26, pady=(0, 20))
        Button(foot, ok_text, style="danger" if kind == "danger" else "primary",
               command=self.ok, width=100).pack(side="right")
        if cancel_text:
            Button(foot, cancel_text, command=self.cancel, width=100).pack(side="right", padx=8)
        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.cancel())

    def ok(self):
        self.result = True
        self.destroy()


def ask_confirm(parent, title: str, message: str, ok_text: str = "Confirm",
                danger: bool = False) -> bool:
    d = MessageDialog(parent, title, message, "danger" if danger else "confirm", ok_text, "Cancel")
    parent.wait_window(d)
    return bool(d.result)


def show_info(parent, title: str, message: str, kind: str = "info") -> None:
    d = MessageDialog(parent, title, message, kind)
    parent.wait_window(d)


def show_error(parent, title: str, message: str) -> None:
    show_info(parent, title, message, "error")


# =========================================================================== #
# 2. Embedded Charts (`Chart`) & Video Canvas (`VideoView`)
# =========================================================================== #
class Chart:
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

    def bar_trend(self, labels: list[str], values: list[float],
                  totals: list[int] | None = None, ylabel: str = "Present",
                  empty_text: str = "No attendance data yet"):
        self.ax.clear()
        if not labels or not any(values):
            self._empty(empty_text)
        else:
            self._style()
            colors = [C["accent"] if i == len(values) - 1 else "#D9A58F"
                      for i in range(len(values))]
            bars = self.ax.bar(labels, values, color=colors, width=0.55, zorder=2)
            if totals:
                self.ax.plot(labels, totals, color=C["sidebar"], linewidth=1.4,
                             linestyle="--", marker="o", markersize=3,
                             label="Registered", zorder=3)
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


class VideoView(ctk.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, fg_color="#151B24", corner_radius=8, **kw)
        self.canvas = tk.Label(self, bg="#151B24", bd=0, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=2, pady=2)
        self._photo = None
        self.placeholder = ctk.CTkFrame(self, fg_color="#151B24")
        self.ph_icon = ctk.CTkLabel(self.placeholder, text="",
                                    image=glyph_image("camera", "#5B6676", 40))
        self.ph_icon.pack(pady=(0, 10))
        self.ph_title = ctk.CTkLabel(self.placeholder, text="Camera is off",
                                     font=font(15, "semibold"), text_color="#D5DAE1")
        self.ph_title.pack()
        self.ph_text = ctk.CTkLabel(self.placeholder, text="", font=font(12),
                                    text_color="#8C96A5", wraplength=420, justify="center")
        self.ph_text.pack(pady=(4, 0))
        self.show_placeholder("Camera is off", "")

    def show_placeholder(self, title: str, text: str = "", icon_name: str = "camera") -> None:
        self._photo = None
        self.canvas.configure(image="")
        self.ph_title.configure(text=title)
        self.ph_text.configure(text=text)
        self.ph_icon.configure(image=glyph_image(icon_name, "#5B6676", 40))
        self.placeholder.place(relx=0.5, rely=0.5, anchor="center")

    def show_frame(self, frame: np.ndarray) -> None:
        self.placeholder.place_forget()
        w = max(self.canvas.winfo_width(), 160)
        h = max(self.canvas.winfo_height(), 120)
        fh, fw = frame.shape[:2]
        scale = min(w / fw, h / fh)
        size = (max(1, int(fw * scale)), max(1, int(fh * scale)))
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb).resize(size, Image.BILINEAR)
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.configure(image=self._photo)


# =========================================================================== #
# 3. Modal Dialogs
# =========================================================================== #
class StudentFormDialog(Dialog):
    def __init__(self, parent, app, student: Optional[dict] = None):
        super().__init__(parent, "Edit Student" if student else "Register Student", 560, 560)
        self.app, self.student = app, student
        self.result: Optional[int] = None

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=28, pady=(22, 4))
        ctk.CTkLabel(head, text="Edit Student" if student else "Register New Student",
                     font=font(17, "semibold"), text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(head, text="Fields marked * are required.", font=font(12),
                     text_color=C["text_muted"]).pack(anchor="w")

        form = Card(self)
        form.pack(fill="both", expand=True, padx=28, pady=12)
        form.grid_columnconfigure((0, 1), weight=1, uniform="f")
        self.fields: dict[str, object] = {}

        def add(row, col, key, label, required=False, widget=None, span=1):
            field_label(form, label, required).grid(
                row=row * 2, column=col, columnspan=span,
                sticky="w", padx=18, pady=(14 if row == 0 else 8, 2))
            w = widget or entry(form)
            w.grid(row=row * 2 + 1, column=col, columnspan=span, sticky="ew", padx=18)
            self.fields[key] = w

        add(0, 0, "student_id", "Student ID / Roll No.", True)
        add(0, 1, "full_name", "Full Name", True)
        self.dept_var = ctk.StringVar(value="")
        add(1, 0, "department", "Department", True,
            combo(form, app.students.departments(), variable=self.dept_var))
        add(1, 1, "course", "Course / Class", True)
        add(2, 0, "email", "Email (optional)")
        add(2, 1, "phone", "Phone (optional)")
        self.error = ctk.CTkLabel(form, text="", font=font(12), text_color=C["danger"],
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
        Button(foot, "Save Changes" if student else "Register Student", "save",
               style="primary", command=self.save).pack(side="right")
        Button(foot, "Cancel", command=self.cancel).pack(side="right", padx=8)
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


class EnrollmentDialog(Dialog):
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

        side = Card(self, width=330)
        side.grid(row=0, column=1, sticky="ns", padx=(0, 22), pady=22)
        side.grid_propagate(False)
        inner = ctk.CTkFrame(side, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20, pady=18)

        ctk.CTkLabel(inner, text=student["full_name"], font=font(16, "semibold"),
                     text_color=C["text"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(inner, text=f"{student['student_id']}  ·  {student['department']}",
                     font=font(12), text_color=C["text_muted"], anchor="w").pack(anchor="w")

        tips = ctk.CTkFrame(inner, fg_color=C["surface_alt"], corner_radius=6)
        tips.pack(fill="x", pady=14)
        ctk.CTkLabel(tips, text="Instructions", font=font(12, "semibold"),
                     text_color=C["text"]).pack(anchor="w", padx=12, pady=(10, 2))
        for t in ("Sit 40–70 cm from the camera, face well lit.",
                  "Only the student should be in view.",
                  "Follow the on-screen prompts: turn slightly left/right, tilt, smile.",
                  "Remove sunglasses or masks."):
            ctk.CTkLabel(tips, text=f"•  {t}", font=font(11), text_color=C["text_muted"],
                         wraplength=270, justify="left", anchor="w").pack(anchor="w", padx=12)
        ctk.CTkLabel(tips, text="").pack(pady=1)

        self.consent = ctk.CTkCheckBox(
            inner, text="The student consents to their face images\nbeing captured and stored "
                        "locally for attendance.", font=font(11), text_color=C["text"],
            fg_color=C["accent"], hover_color=C["accent_hover"], border_color=C["border_strong"],
            checkbox_width=18, checkbox_height=18, command=self._update_buttons)
        self.consent.pack(anchor="w", pady=(0, 14))

        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text="Samples captured", font=font(12, "semibold"),
                     text_color=C["text_muted"]).pack(side="left")
        self.count_lbl = ctk.CTkLabel(row, text=f"0 / {self.session.target}",
                                      font=font(14, "semibold"), text_color=C["text"])
        self.count_lbl.pack(side="right")
        self.progress = ctk.CTkProgressBar(inner, height=8, corner_radius=4,
                                           progress_color=C["accent"], fg_color=C["border"])
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(6, 12))
        self.status = ctk.CTkLabel(inner, text="Starting camera...", font=font(12),
                                   text_color=C["info"], wraplength=280, justify="left",
                                   anchor="w")
        self.status.pack(anchor="w", fill="x")

        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.pack(side="bottom", fill="x")
        self.save_btn = Button(btns, "Save & Train Model", "check", style="success",
                               command=self.save, height=40)
        self.save_btn.pack(fill="x", pady=(8, 0))
        self.capture_btn = Button(btns, "Start Capture", "camera", style="primary",
                                  command=self.start_capture, height=40)
        self.capture_btn.pack(fill="x", pady=(8, 0))
        self.cancel_btn = Button(btns, "Cancel", command=self.cancel, height=36)
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
            show_error(self, "Not enough samples",
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
            show_error(self, "Enrollment failed", f"Could not save the face samples:\n{exc}")
            self._saving = False
            return

        def done(result, error):
            self.result = True
            n = self.session.count
            if error or not result.success:
                show_error(self, "Training problem",
                           f"Samples were saved but training failed:\n{error or result.message}"
                           "\nUse Settings → Retrain Model.")
            else:
                show_info(self, "Enrollment successful",
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


class ManualAttendanceDialog(Dialog):
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
                     font=font(16, "semibold"), text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(head, text="Record attendance manually when camera recognition is not used.",
                     font=font(12), text_color=C["text_muted"]).pack(anchor="w")

        card = Card(self)
        card.pack(fill="both", expand=True, padx=26, pady=10)
        card.grid_columnconfigure((0, 1), weight=1)

        field_label(card, "Student", True).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(14, 2))
        self.student_var = ctk.StringVar(value=selected_label or (options[0] if options else ""))
        self.student_menu = option_menu(
            card, options or ["No students registered"], width=400, variable=self.student_var)
        self.student_menu.grid(row=1, column=0, columnspan=2, sticky="ew", padx=18)

        field_label(card, "Date (YYYY-MM-DD)", True).grid(
            row=2, column=0, sticky="w", padx=18, pady=(12, 2))
        self.date_entry = entry(card)
        self.date_entry.insert(0, default_date or datetime.now().strftime("%Y-%m-%d"))
        self.date_entry.grid(row=3, column=0, sticky="ew", padx=(18, 8))

        field_label(card, "Check-in Time (HH:MM:SS)", True).grid(
            row=2, column=1, sticky="w", padx=(8, 18), pady=(12, 2))
        self.time_entry = entry(card)
        self.time_entry.insert(0, datetime.now().strftime("%H:%M:%S"))
        self.time_entry.grid(row=3, column=1, sticky="ew", padx=(8, 18))

        field_label(card, "Attendance Status", True).grid(
            row=4, column=0, columnspan=2, sticky="w", padx=18, pady=(12, 2))
        self.status_var = ctk.StringVar(value="Present")
        self.status_menu = option_menu(card, list(STATUSES), width=200, variable=self.status_var)
        self.status_menu.grid(row=5, column=0, sticky="w", padx=18)

        self.err_lbl = ctk.CTkLabel(card, text="", font=font(12), text_color=C["danger"])
        self.err_lbl.grid(row=6, column=0, columnspan=2, sticky="w", padx=18, pady=(10, 12))

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=26, pady=(0, 20))
        save_btn = Button(foot, "Mark Attendance", "check", style="primary", command=self.save)
        save_btn.pack(side="right")
        if not options:
            save_btn.configure_state(False)
        Button(foot, "Cancel", command=self.cancel).pack(side="right", padx=8)

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
        if res.status in ("duplicate", "error"):
            self.err_lbl.configure(text=res.message)
            return
        self.result = res
        self.destroy()


class EditAttendanceDialog(Dialog):
    def __init__(self, parent, app, record: dict):
        super().__init__(parent, "Correct Attendance Record", 460, 380)
        self.app = app
        self.record = record
        self.result = False

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=26, pady=(20, 6))
        ctk.CTkLabel(head, text=f"{record['full_name']} ({record['roll']})",
                     font=font(16, "semibold"), text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(head, text=f"Record #{record['id']}  ·  {record['department']}",
                     font=font(12), text_color=C["text_muted"]).pack(anchor="w")

        card = Card(self)
        card.pack(fill="both", expand=True, padx=26, pady=10)
        card.grid_columnconfigure((0, 1), weight=1)

        field_label(card, "Date (YYYY-MM-DD)", True).grid(
            row=0, column=0, sticky="w", padx=18, pady=(14, 2))
        self.date_entry = entry(card)
        self.date_entry.insert(0, record["attendance_date"])
        self.date_entry.grid(row=1, column=0, sticky="ew", padx=(18, 8))

        field_label(card, "Check-in Time (HH:MM:SS)").grid(
            row=0, column=1, sticky="w", padx=(8, 18), pady=(14, 2))
        self.time_entry = entry(card)
        self.time_entry.insert(
            0, record.get("check_in_time") or datetime.now().strftime("%H:%M:%S"))
        self.time_entry.grid(row=1, column=1, sticky="ew", padx=(8, 18))

        field_label(card, "Attendance Status", True).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=18, pady=(12, 2))
        self.status_var = ctk.StringVar(value=record["status"])
        option_menu(card, list(STATUSES), width=200, variable=self.status_var).grid(
            row=3, column=0, sticky="w", padx=18)

        self.err_lbl = ctk.CTkLabel(card, text="", font=font(12), text_color=C["danger"])
        self.err_lbl.grid(row=4, column=0, columnspan=2, sticky="w", padx=18, pady=(10, 12))

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=26, pady=(0, 20))
        Button(foot, "Save Correction", "save", style="primary", command=self.save).pack(side="right")
        Button(foot, "Cancel", command=self.cancel).pack(side="right", padx=8)

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


class StudentHistoryDialog(Dialog):
    def __init__(self, parent, app, student: dict):
        super().__init__(parent, f"Attendance History – {student['full_name']}", 760, 480)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=24, pady=(18, 8))
        ctk.CTkLabel(head, text=f"{student['full_name']}  ({student['student_id']})",
                     font=font(16, "semibold"), text_color=C["text"]).pack(side="left")
        rows = app.attendance.list_records(student_pk=student["id"])
        present = sum(1 for r in rows if r["status"] in ("Present", "Late"))
        Badge(head, f"{present} attended  ·  {len(rows)} record(s)", "info").pack(side="right")

        card = Card(self)
        card.pack(fill="both", expand=True, padx=24, pady=6)
        table = DataTable(card, [
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
        Button(foot, "Close", command=self.cancel).pack(side="right")


# =========================================================================== #
# 4. Application Pages
# =========================================================================== #
class Page(ctk.CTkFrame):
    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color=C["bg"], corner_radius=0)
        self.app = app

    def on_show(self) -> None:
        pass

    def on_hide(self) -> None:
        pass


class DashboardPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="stats")
        self.grid_rowconfigure(2, weight=5)
        self.grid_rowconfigure(3, weight=4)

        strip = Card(self)
        strip.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 16))
        left = ctk.CTkFrame(strip, fg_color="transparent")
        left.pack(side="left", padx=20, pady=14, fill="x", expand=True)
        self.greet = ctk.CTkLabel(left, text="", font=font(16, "semibold"),
                                  text_color=C["text"], anchor="w")
        self.greet.pack(anchor="w")
        self.summary = ctk.CTkLabel(left, text="", font=font(12), text_color=C["text_muted"],
                                    anchor="w")
        self.summary.pack(anchor="w")
        Button(strip, "Start Attendance", "play", style="primary", height=40,
               command=lambda: app.show_page("live")).pack(side="right", padx=(8, 20))
        Button(strip, "Register Student", "add", height=40,
               command=self._open_register_student).pack(side="right")

        self.cards = {
            "total": StatCard(self, "Registered Students", "students", C["info"], C["info_soft"]),
            "present": StatCard(self, "Present Today", "check", C["success"], C["success_soft"]),
            "absent": StatCard(self, "Absent Today", "close", C["danger"], C["danger_soft"]),
            "pct": StatCard(self, "Attendance Rate", "pie", C["accent"], C["accent_soft"]),
        }
        for i, card in enumerate(self.cards.values()):
            card.grid(row=1, column=i, sticky="nsew",
                      padx=(0 if i == 0 else 8, 0 if i == 3 else 8))

        trend = Card(self)
        trend.grid(row=2, column=0, columnspan=3, sticky="nsew", pady=16, padx=(0, 8))
        SectionHeader(trend, "Attendance Trend", "Students present over the last 7 days").pack(
            fill="x", padx=18, pady=(14, 0))
        self.trend_chart = Chart(trend, 6, 2.2)
        self.trend_chart.widget.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        split = Card(self)
        split.grid(row=2, column=3, sticky="nsew", pady=16, padx=(8, 0))
        SectionHeader(split, "Today", "Present vs absent").pack(fill="x", padx=18, pady=(14, 0))
        self.donut = Chart(split, 2.4, 2.0)
        self.donut.widget.pack(fill="both", expand=True, padx=10)
        legend = ctk.CTkFrame(split, fg_color="transparent")
        legend.pack(pady=(0, 12))
        self.leg_present = self._legend(legend, C["success"], "Present 0")
        self.leg_absent = self._legend(legend, "#E7C9BD", "Absent 0")

        recent = Card(self)
        recent.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=(0, 8))
        hdr = SectionHeader(recent, "Recent Attendance", "Latest check-ins")
        hdr.pack(fill="x", padx=18, pady=(14, 8))
        Button(hdr.actions, "View all", style="ghost", height=28, size=12,
               command=lambda: app.show_page("records")).pack()
        self.recent_table = DataTable(recent, [
            ("full_name", "Student", 170, "w"), ("roll", "ID", 90, "w"),
            ("date", "Date", 95, "w"), ("time", "Time", 80, "w"),
            ("method", "Method", 70, "w")], height=5,
            empty_text="No attendance has been recorded yet.")
        self.recent_table.pack(fill="both", expand=True, padx=1, pady=(0, 8))

        students = Card(self)
        students.grid(row=3, column=2, columnspan=2, sticky="nsew", padx=(8, 0))
        hdr2 = SectionHeader(students, "Recently Registered", "Newest students")
        hdr2.pack(fill="x", padx=18, pady=(14, 8))
        Button(hdr2.actions, "Manage", style="ghost", height=28, size=12,
               command=lambda: app.show_page("students")).pack()
        self.student_table = DataTable(students, [
            ("full_name", "Name", 160, "w"), ("department", "Department", 140, "w"),
            ("face", "Face", 80, "w")], height=5,
            empty_text="No students registered yet. Click 'Register Student'.")
        self.student_table.pack(fill="both", expand=True, padx=1, pady=(0, 8))

    def _legend(self, parent, color, text):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(side="left", padx=8)
        ctk.CTkFrame(f, width=10, height=10, corner_radius=2, fg_color=color).pack(
            side="left", padx=(0, 6))
        lbl = ctk.CTkLabel(f, text=text, font=font(11), text_color=C["text_muted"])
        lbl.pack(side="left")
        return lbl

    def _open_register_student(self):
        self.app.show_page("students")
        self.app.pages["students"].open_add_dialog()

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

        bar = Card(self)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        self.btn_start = Button(bar, "Start Camera", "play", style="primary",
                                command=self.start_camera)
        self.btn_start.pack(side="left", padx=(16, 6), pady=12)
        self.btn_stop = Button(bar, "Stop Camera", "stop", style="danger",
                               command=self.stop_camera)
        self.btn_stop.pack(side="left", padx=6, pady=12)
        self.btn_pause = Button(bar, "Pause Recognition", "pause",
                                command=self.toggle_pause)
        self.btn_pause.pack(side="left", padx=6, pady=12)
        self.btn_switch = Button(bar, "Switch Camera", "switch",
                                 command=self.switch_camera)
        self.btn_switch.pack(side="left", padx=6, pady=12)

        Button(bar, "Manual Attendance", "edit", style="dark",
               command=self.open_manual).pack(side="right", padx=(6, 16), pady=12)
        self.status_badge = Badge(bar, "Camera Stopped", "neutral")
        self.status_badge.pack(side="right", padx=10)

        left = Card(self)
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
            btxt, text="Ready for Live Attendance", font=font(13, "semibold"),
            text_color=C["text"], anchor="w")
        self.banner_title.pack(anchor="w")
        self.banner_sub = ctk.CTkLabel(
            btxt, text="Enrolled students looking at the camera are marked automatically once per day.",
            font=font(11), text_color=C["text_muted"], anchor="w")
        self.banner_sub.pack(anchor="w")
        self.fps_lbl = ctk.CTkLabel(self.banner, text="", font=font(11),
                                    text_color=C["text_soft"])
        self.fps_lbl.pack(side="right", padx=14)

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew")
        right.grid_columnconfigure((0, 1), weight=1)
        right.grid_rowconfigure(2, weight=1)

        self.tile_present = self._mini_stat(right, 0, 0, "Present Today", "0", C["success"])
        self.tile_absent = self._mini_stat(right, 0, 1, "Absent Today", "0", C["danger"])
        self.tile_frame = self._mini_stat(right, 1, 0, "Faces in Frame", "0", C["info"])
        self.tile_thr = self._mini_stat(right, 1, 1, "Threshold / Cooldown", "—", C["accent"])

        log_card = Card(right)
        log_card.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        hdr = SectionHeader(log_card, "Today's Check-ins", "Marked during today's session")
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        self.today_table = DataTable(
            log_card,
            [("time", "Time", 75, "w"), ("name", "Student", 145, "w"),
             ("roll", "ID", 80, "w"), ("method", "Method", 70, "w")],
            height=10, empty_text="No students marked present today yet.")
        self.today_table.pack(fill="both", expand=True, padx=1, pady=(0, 8))

        self._sync_buttons()

    def _mini_stat(self, parent, row: int, col: int, label: str, value: str, color: str):
        card = Card(parent)
        card.grid(row=row, column=col, sticky="nsew",
                  padx=(0 if col == 0 else 6, 6 if col == 0 else 0), pady=(0, 8))
        ctk.CTkLabel(card, text=label.upper(), font=font(10, "semibold"),
                     text_color=C["text_muted"]).pack(anchor="w", padx=14, pady=(10, 0))
        val = ctk.CTkLabel(card, text=value, font=font(20, "semibold"), text_color=color)
        val.pack(anchor="w", padx=14, pady=(0, 10))
        return val

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

    def start_camera(self) -> None:
        if self.engine is None:
            show_error(self, "Face detector unavailable", self.app.detector_error or "")
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


class StudentsPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.selected: Optional[dict] = None

        bar = Card(self)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        ctk.CTkLabel(bar, text="", image=glyph_image("search", C["text_soft"], 16)).pack(
            side="left", padx=(16, 6), pady=12)
        self.search = entry(bar, "Search by name, ID or course", width=260)
        self.search.pack(side="left", pady=12)
        self.search.bind("<KeyRelease>", lambda e: self.refresh())
        self.dept = option_menu(bar, ["All Departments"], width=200,
                                command=lambda v: self.refresh())
        self.dept.pack(side="left", padx=10)
        Button(bar, "Register Student", "add", style="primary",
               command=self.open_add_dialog).pack(side="right", padx=(6, 16))
        self.count_lbl = ctk.CTkLabel(bar, text="", font=font(12), text_color=C["text_muted"])
        self.count_lbl.pack(side="right", padx=10)

        card = Card(self)
        card.grid(row=1, column=0, sticky="nsew", padx=(0, 16))
        self.table = DataTable(card, [
            ("student_id", "Student ID", 100, "w"), ("full_name", "Full Name", 180, "w"),
            ("department", "Department", 160, "w"), ("course", "Course / Class", 150, "w"),
            ("face", "Face", 90, "w"), ("created", "Registered", 100, "w")],
            on_select=self._on_select, on_double=lambda r: self.edit(),
            empty_text="No students found. Click 'Register Student' to add one.")
        self.table.pack(fill="both", expand=True, padx=1, pady=8)

        self.panel = Card(self, width=310)
        self.panel.grid(row=1, column=1, sticky="ns")
        self.panel.grid_propagate(False)
        self.panel.pack_propagate(False)
        self._build_panel()

    def _build_panel(self):
        p = self.panel
        self.photo = ctk.CTkLabel(p, text="", width=120, height=120, corner_radius=60,
                                  fg_color=C["surface_alt"])
        self.photo.pack(pady=(24, 10))
        self.p_name = ctk.CTkLabel(p, text="No student selected", font=font(15, "semibold"),
                                   text_color=C["text"], wraplength=260)
        self.p_name.pack()
        self.p_id = ctk.CTkLabel(p, text="Select a student in the table", font=font(12),
                                 text_color=C["text_muted"])
        self.p_id.pack()
        self.p_badge = Badge(p, "—", "neutral")
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
            ctk.CTkLabel(info, text=label, font=font(11), text_color=C["text_soft"],
                         anchor="w").grid(row=i, column=0, sticky="w", pady=3)
            v = ctk.CTkLabel(info, text="—", font=font(12), text_color=C["text"], anchor="e",
                             wraplength=170, justify="right")
            v.grid(row=i, column=1, sticky="e", pady=3)
            self.p_fields[k] = v
        btns = ctk.CTkFrame(p, fg_color="transparent")
        btns.pack(side="bottom", fill="x", padx=20, pady=18)
        self.b_enroll = Button(btns, "Enroll Face", "camera", style="primary",
                               command=self.enroll)
        self.b_enroll.pack(fill="x", pady=3)
        self.b_history = Button(btns, "Attendance History", "history", command=self.history)
        self.b_history.pack(fill="x", pady=3)
        row = ctk.CTkFrame(btns, fg_color="transparent")
        row.pack(fill="x", pady=3)
        row.grid_columnconfigure((0, 1), weight=1)
        self.b_edit = Button(row, "Edit", "edit", command=self.edit)
        self.b_edit.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.b_delete = Button(row, "Delete", "delete", style="danger", command=self.delete)
        self.b_delete.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self._show_details(None)

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
            self.photo.configure(image=glyph_image("person", C["text_soft"], 46))
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
        self.photo.configure(image=img or glyph_image("person", C["text_soft"], 46))
        self.p_name.configure(text=s["full_name"])
        self.p_id.configure(text=s["student_id"])
        samples = self.app.students.sample_count(s["id"])
        self.p_badge.set("Face enrolled" if s["face_enrolled"] else "Face not enrolled",
                         "success" if s["face_enrolled"] else "warning")
        present = self.app.db.fetch_one(
            "SELECT COUNT(*) n FROM attendance WHERE student_id=? AND status IN ('Present','Late')",
            (s["id"],))["n"]
        vals = {"department": s["department"], "course": s["course"],
                "email": s["email"] or "—", "phone": s["phone"] or "—",
                "samples": str(samples), "attendance": str(present),
                "created_at": (s["created_at"] or "")[:16]}
        for k, v in vals.items():
            self.p_fields[k].configure(text=v)
        self.b_enroll.set_text("Re-enroll Face" if s["face_enrolled"] else "Enroll Face")

    def open_add_dialog(self):
        d = StudentFormDialog(self, self.app)
        self.wait_window(d)
        if d.result:
            self.app.notify("Student registered successfully.", "success")
            self.selected = self.app.students.get(d.result)
            self.on_show()
            if ask_confirm(self, "Enroll face now?",
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
                self.app.retrain_model()

    def delete(self):
        s = self.selected
        if not s:
            return
        if not ask_confirm(self, "Delete student?",
                           f"This permanently deletes {s['full_name']} ({s['student_id']}), "
                           "their face samples and ALL their attendance records.",
                           "Delete", danger=True):
            return
        try:
            had_faces = self.app.students.delete(s["id"])
        except Exception as exc:              # noqa: BLE001
            log.exception("Delete failed")
            show_error(self, "Delete failed", str(exc))
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
            show_error(self, "Face detector unavailable", self.app.detector_error or "")
            return
        live = self.app.pages.get("live")
        if live is not None:
            live.on_hide()
        d = EnrollmentDialog(self, self.app, s)
        self.wait_window(d)
        self.refresh()

    def history(self):
        if self.selected:
            StudentHistoryDialog(self, self.app, self.selected)


class AttendanceRecordsPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.current_rows: list[dict] = []

        bar = Card(self)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        r1 = ctk.CTkFrame(bar, fg_color="transparent")
        r1.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(r1, text="", image=glyph_image("search", C["text_soft"], 16)).pack(
            side="left", padx=(0, 6))
        self.search = entry(r1, "Search student name or ID", width=220)
        self.search.pack(side="left")
        self.search.bind("<KeyRelease>", lambda e: self.refresh())

        ctk.CTkLabel(r1, text="From", font=font(12), text_color=C["text_muted"]).pack(
            side="left", padx=(14, 4))
        self.date_from = entry(r1, "YYYY-MM-DD", width=115)
        self.date_from.insert(0, date.today().isoformat())
        self.date_from.pack(side="left")

        ctk.CTkLabel(r1, text="To", font=font(12), text_color=C["text_muted"]).pack(
            side="left", padx=(8, 4))
        self.date_to = entry(r1, "YYYY-MM-DD", width=115)
        self.date_to.insert(0, date.today().isoformat())
        self.date_to.pack(side="left")

        Button(r1, "Today", style="ghost", height=32, size=12,
               command=self._set_today).pack(side="left", padx=(6, 0))
        Button(r1, "7 Days", style="ghost", height=32, size=12,
               command=lambda: self._set_days(7)).pack(side="left")
        Button(r1, "All Dates", style="ghost", height=32, size=12,
               command=self._set_all_dates).pack(side="left")

        Button(r1, "Export CSV", "export", command=self.export_csv).pack(side="right")
        Button(r1, "Manual Entry", "add", style="primary",
               command=self.manual_entry).pack(side="right", padx=8)

        r2 = ctk.CTkFrame(bar, fg_color="transparent")
        r2.pack(fill="x", padx=16, pady=(0, 12))
        self.dept = option_menu(r2, ["All Departments"], width=190,
                                command=lambda v: self.refresh())
        self.dept.pack(side="left")
        self.status = option_menu(
            r2, ["All Statuses"] + list(STATUSES), width=150, command=lambda v: self.refresh())
        self.status.pack(side="left", padx=10)

        self.show_absent = ctk.CTkCheckBox(
            r2, text="Include unmarked students as Absent (single-day view)",
            font=font(12), text_color=C["text_muted"], fg_color=C["accent"],
            hover_color=C["accent_hover"], checkbox_width=18, checkbox_height=18,
            command=self.refresh)
        self.show_absent.select()
        self.show_absent.pack(side="left", padx=8)

        Button(r2, "Apply Date Filter", "refresh", height=32, size=12,
               command=self.refresh).pack(side="left", padx=8)
        self.summary_lbl = ctk.CTkLabel(r2, text="", font=font(12), text_color=C["text_muted"])
        self.summary_lbl.pack(side="right")

        card = Card(self)
        card.grid(row=1, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(0, weight=1)

        self.table = DataTable(card, [
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
        self.b_history = Button(foot, "Student History", "history", height=32, size=12,
                                command=self.view_history)
        self.b_history.pack(side="left", padx=(14, 6), pady=8)
        self.b_correct = Button(foot, "Correct / Mark Record", "edit", height=32, size=12,
                                command=self.correct_selected)
        self.b_correct.pack(side="left", padx=6, pady=8)
        self.b_delete = Button(foot, "Delete Record", "delete", style="danger",
                               height=32, size=12, command=self.delete_selected)
        self.b_delete.pack(side="left", padx=6, pady=8)

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
        if not ask_confirm(
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
            show_info(self, "Nothing to export", "There are no rows in the current view.")
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

        bar = Card(self)
        bar.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 14))

        ctk.CTkLabel(bar, text="Period", font=font(12, "semibold"),
                     text_color=C["text_muted"]).pack(side="left", padx=(16, 6), pady=12)
        today = date.today()
        self.date_from = entry(bar, "YYYY-MM-DD", width=115)
        self.date_from.insert(0, (today - timedelta(days=29)).isoformat())
        self.date_from.pack(side="left", pady=12)
        ctk.CTkLabel(bar, text="to", font=font(12), text_color=C["text_muted"]).pack(
            side="left", padx=6)
        self.date_to = entry(bar, "YYYY-MM-DD", width=115)
        self.date_to.insert(0, today.isoformat())
        self.date_to.pack(side="left", pady=12)

        for label, days in (("7D", 7), ("30D", 30), ("90D", 90)):
            Button(bar, label, style="ghost", height=32, size=12,
                   command=lambda d=days: self._set_range(d)).pack(side="left", padx=2)

        self.dept = option_menu(bar, ["All Departments"], width=190,
                                command=lambda v: self.refresh())
        self.dept.pack(side="left", padx=10)
        Button(bar, "Update", "refresh", height=34, command=self.refresh).pack(side="left")

        Button(bar, "Export PDF", "pdf", style="primary",
               command=self.export_pdf).pack(side="right", padx=(6, 16), pady=12)
        Button(bar, "Export CSV", "export",
               command=self.export_csv).pack(side="right", padx=6, pady=12)

        self.cards = {
            "pct": StatCard(self, "Overall Attendance %", "pie", C["accent"], C["accent_soft"]),
            "sessions": StatCard(self, "Session Days", "calendar", C["info"], C["info_soft"]),
            "attended": StatCard(self, "Total Present / Late", "check",
                                 C["success"], C["success_soft"]),
            "absent": StatCard(self, "Total Absent", "close", C["danger"], C["danger_soft"]),
        }
        for i, card in enumerate(self.cards.values()):
            card.grid(row=1, column=i, sticky="nsew",
                      padx=(0 if i == 0 else 8, 0 if i == 3 else 8))

        trend_card = Card(self)
        trend_card.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=14, padx=(0, 8))
        SectionHeader(trend_card, "Attendance Rate Over Time",
                      "Session-day attendance percentage").pack(fill="x", padx=18, pady=(12, 0))
        self.trend_chart = Chart(trend_card, 5.2, 2.0)
        self.trend_chart.widget.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        dept_card = Card(self)
        dept_card.grid(row=2, column=2, columnspan=2, sticky="nsew", pady=14, padx=(8, 0))
        SectionHeader(dept_card, "Department Comparison",
                      "Average attendance rate by department").pack(
            fill="x", padx=18, pady=(12, 0))
        self.dept_chart = Chart(dept_card, 5.2, 2.0)
        self.dept_chart.widget.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        table_card = Card(self)
        table_card.grid(row=3, column=0, columnspan=4, sticky="nsew")
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(1, weight=1)

        tab_bar = ctk.CTkFrame(table_card, fg_color="transparent")
        tab_bar.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        self.tab_btns: dict[str, Button] = {}
        for kind, title in REPORT_TABS:
            b = Button(
                tab_bar, title,
                style="primary" if kind == self.active_kind else "secondary",
                height=32, size=12, command=lambda k=kind: self.switch_tab(k))
            b.pack(side="left", padx=(0, 6))
            self.tab_btns[kind] = b

        self.table_holder = ctk.CTkFrame(table_card, fg_color=C["surface"])
        self.table_holder.grid(row=1, column=0, sticky="nsew", padx=1, pady=(0, 8))
        self.table_holder.grid_columnconfigure(0, weight=1)
        self.table_holder.grid_rowconfigure(0, weight=1)
        self.tables: dict[str, DataTable] = {}
        for kind, cols in TAB_COLUMNS.items():
            t = DataTable(self.table_holder, cols, height=7,
                          empty_text="No attendance data recorded in the selected date range.")
            self.tables[kind] = t
        self.tables[self.active_kind].grid(row=0, column=0, sticky="nsew")

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
            st = BUTTON_STYLES["primary" if k == kind else "secondary"]
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

    def export_csv(self) -> None:
        if not self.current_rows:
            show_info(self, "Nothing to export",
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
                show_error(self, "PDF export failed", str(error))
            else:
                self.app.notify(f"Saved PDF report to {Path(out).name}", "success")

        self.app.run_in_background(
            lambda: self.app.reports.export_pdf(path, df, dt, dept), done)


class SettingsPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure((0, 1), weight=1, uniform="scol")
        self.grid_rowconfigure(0, weight=1)

        left = Card(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        hdr = SectionHeader(
            left, "Camera & Face Recognition",
            "Tune webcam index, LBPH distance threshold, cooldown and enrollment parameters")
        hdr.pack(fill="x", padx=22, pady=(18, 10))

        form = ctk.CTkFrame(left, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=22)
        form.grid_columnconfigure(1, weight=1)

        field_label(form, "Webcam Device Index").grid(row=0, column=0, sticky="w", pady=8)
        cam_row = ctk.CTkFrame(form, fg_color="transparent")
        cam_row.grid(row=0, column=1, sticky="e", pady=8)
        self.cam_var = ctk.StringVar(value="0")
        self.cam_menu = option_menu(cam_row, ["0", "1", "2", "3"], width=100,
                                    variable=self.cam_var)
        self.cam_menu.pack(side="left", padx=(0, 8))
        Button(cam_row, "Detect Cameras", "camera", height=34, size=12,
               command=self.detect_cameras).pack(side="left")

        field_label(form, "Recognition Distance Threshold (lower = stricter)").grid(
            row=1, column=0, sticky="w", pady=8)
        thr_row = ctk.CTkFrame(form, fg_color="transparent")
        thr_row.grid(row=1, column=1, sticky="ew", pady=8)
        self.thr_lbl = ctk.CTkLabel(thr_row, text="50", font=font(13, "semibold"),
                                    text_color=C["accent"], width=36)
        self.thr_lbl.pack(side="right")
        self.thr_slider = ctk.CTkSlider(
            thr_row, from_=30, to=90, number_of_steps=60,
            button_color=C["accent"], button_hover_color=C["accent_hover"],
            progress_color=C["accent"], fg_color=C["border"],
            command=lambda v: self.thr_lbl.configure(text=str(int(round(v)))))
        self.thr_slider.pack(side="right", fill="x", expand=True, padx=(12, 8))

        field_label(form, "Recognition Notification Cooldown (seconds)").grid(
            row=2, column=0, sticky="w", pady=8)
        self.cooldown_entry = entry(form, "5", width=120)
        self.cooldown_entry.grid(row=2, column=1, sticky="e", pady=8)

        field_label(form, "Confirmation Frames Before Marking").grid(
            row=3, column=0, sticky="w", pady=8)
        self.confirm_var = ctk.StringVar(value="3")
        option_menu(form, ["1", "2", "3", "4", "5"], width=120,
                    variable=self.confirm_var).grid(row=3, column=1, sticky="e", pady=8)

        field_label(form, "Samples Captured per Face Enrollment").grid(
            row=4, column=0, sticky="w", pady=8)
        self.samples_var = ctk.StringVar(value="15")
        option_menu(form, ["10", "12", "15", "20", "25"], width=120,
                    variable=self.samples_var).grid(row=4, column=1, sticky="e", pady=8)

        field_label(form, "Mark 'Late' After Time (HH:MM, optional)").grid(
            row=5, column=0, sticky="w", pady=8)
        self.late_entry = entry(form, "e.g. 09:30 (leave blank to disable)", width=210)
        self.late_entry.grid(row=5, column=1, sticky="e", pady=8)

        field_label(form, "Default Export Folder").grid(row=6, column=0, sticky="w", pady=8)
        exp_row = ctk.CTkFrame(form, fg_color="transparent")
        exp_row.grid(row=6, column=1, columnspan=2, sticky="ew", pady=8)
        self.export_entry = entry(exp_row, width=220)
        self.export_entry.pack(side="left", fill="x", expand=True, padx=(12, 6))
        Button(exp_row, "Browse", "folder", height=34, size=12,
               command=self.browse_export).pack(side="left")

        foot_left = ctk.CTkFrame(left, fg_color="transparent")
        foot_left.pack(fill="x", padx=22, pady=18)
        Button(foot_left, "Save Settings", "save", style="primary",
               command=self.save_settings).pack(side="right")
        Button(foot_left, "Reset Defaults", "refresh",
               command=self.reset_defaults).pack(side="right", padx=8)

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.grid_columnconfigure(0, weight=1)

        mcard = Card(right)
        mcard.pack(fill="x", pady=(0, 12))
        SectionHeader(
            mcard, "LBPH Face Recognition Model",
            "Rebuild the classifier from all stored student face samples").pack(
            fill="x", padx=20, pady=(16, 6))
        self.model_info = ctk.CTkLabel(
            mcard, text="", font=font(12), text_color=C["text_muted"],
            justify="left", anchor="w")
        self.model_info.pack(fill="x", padx=20, pady=(0, 10))
        mbtns = ctk.CTkFrame(mcard, fg_color="transparent")
        mbtns.pack(fill="x", padx=20, pady=(0, 16))
        Button(mbtns, "Retrain Face Model Now", "sync", style="primary",
               command=self.retrain).pack(side="left")

        dbcard = Card(right)
        dbcard.pack(fill="x", pady=(0, 12))
        SectionHeader(
            dbcard, "Database Backup & Restore",
            "Create a consistent SQLite backup or restore from a previous backup").pack(
            fill="x", padx=20, pady=(16, 8))
        db_btns = ctk.CTkFrame(dbcard, fg_color="transparent")
        db_btns.pack(fill="x", padx=20, pady=(0, 16))
        Button(db_btns, "Backup Database", "save", style="dark",
               command=self.backup_db).pack(side="left", padx=(0, 8))
        Button(db_btns, "Restore from Backup...", "folder",
               command=self.restore_db).pack(side="left", padx=8)
        Button(db_btns, "Open Data Folder", "folder", style="ghost",
               command=self.open_data_folder).pack(side="right")

        icard = Card(right)
        icard.pack(fill="both", expand=True)
        SectionHeader(
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
            ctk.CTkLabel(info_grid, text=k, font=font(11, "semibold"),
                         text_color=C["text_soft"], anchor="w").grid(
                row=i, column=0, sticky="w", pady=3, padx=(0, 12))
            ctk.CTkLabel(info_grid, text=v, font=font(11),
                         text_color=C["text"], anchor="e", wraplength=330,
                         justify="right").grid(row=i, column=1, sticky="e", pady=3)

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
            show_error(self, "Invalid Cooldown",
                       "Cooldown must be a number between 0 and 300 seconds.")
            return
        late = self.late_entry.get().strip()
        if late:
            try:
                datetime.strptime(late, "%H:%M")
            except ValueError:
                show_error(self, "Invalid Time",
                           "Late cutoff time must be in 24-hour HH:MM format (e.g. 09:30).")
                return
        export_dir = Path(self.export_entry.get().strip() or config.EXPORTS_DIR)
        try:
            export_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            show_error(self, "Invalid Export Folder", str(exc))
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
        if not ask_confirm(self, "Reset settings?",
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
            show_info(self, "Backup created",
                      f"Database backed up to:\n{dest}", "success")
        except Exception as exc:          # noqa: BLE001
            show_error(self, "Backup failed", str(exc))

    def restore_db(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="Select FaceTrack Backup File",
            initialdir=str(config.BACKUPS_DIR),
            filetypes=[("SQLite Database", "*.db"), ("All files", "*.*")])
        if not path:
            return
        if not ask_confirm(
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
            show_info(self, "Database restored",
                      f"Database restored successfully.\nSafety copy saved to:\n{safety.name}",
                      "success")
        except DatabaseError as exc:
            show_error(self, "Restore refused", str(exc))

    def open_data_folder(self) -> None:
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(config.DATA_DIR))
        except Exception as exc:          # noqa: BLE001
            self.app.notify(f"Data folder: {config.DATA_DIR} ({exc})", "info")


# =========================================================================== #
# 5. Main Window (`App`)
# =========================================================================== #
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


class NavButton(ctk.CTkFrame):
    def __init__(self, master, key: str, text: str, icon_name: str, command: Callable):
        super().__init__(master, fg_color="transparent", corner_radius=6, height=42, cursor="hand2")
        self.key, self.command = key, command
        self.pack_propagate(False)
        self.indicator = ctk.CTkFrame(self, width=3, fg_color="transparent", corner_radius=2)
        self.indicator.pack(side="left", fill="y", pady=9)
        self.icon = ctk.CTkLabel(self, text="", width=24,
                                 image=glyph_image(icon_name, C["sidebar_text"], 17))
        self.icon.pack(side="left", padx=(12, 10))
        self.label = ctk.CTkLabel(self, text=text, font=font(13), text_color=C["sidebar_text"],
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
        self.label.configure(text_color=color, font=font(13, "semibold" if active else "normal"))
        self.icon.configure(image=glyph_image(
            self._icon_name, C["accent"] if active else C["sidebar_text"], 17))


class App(ctk.CTk):
    def __init__(self, db: DatabaseManager):
        super().__init__()
        ctk.set_appearance_mode("light")
        self.title(config.APP_FULL_NAME)
        self.configure(fg_color=C["bg"])
        self.minsize(1100, 640)
        self._set_window_icon()

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
        self._tick_job: Optional[str] = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.report_callback_exception = self._on_tk_error
        self._tick()
        self.show_page("dashboard")
        self.after(10, lambda: self.state("zoomed"))
        if self.detector_error:
            self.after(800, lambda: show_error(self, "Face detector unavailable",
                                               self.detector_error))

    def _set_window_icon(self) -> None:
        try:
            self._icon_img = ImageTk.PhotoImage(config.build_logo_image(64))
            self.iconphoto(True, self._icon_img)
        except Exception:              # noqa: BLE001
            pass

    def _build_sidebar(self) -> None:
        sb = ctk.CTkFrame(self, width=240, fg_color=C["sidebar"], corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsw")
        sb.grid_propagate(False)
        sb.pack_propagate(False)

        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.pack(fill="x", padx=20, pady=(26, 30))
        logo_pil = config.build_logo_image(76)
        ctk.CTkLabel(brand, text="", image=ctk.CTkImage(logo_pil, logo_pil, size=(38, 38))).pack(
            side="left")
        txt = ctk.CTkFrame(brand, fg_color="transparent")
        txt.pack(side="left", padx=12)
        ctk.CTkLabel(txt, text=config.APP_NAME, font=font(18, "semibold"),
                     text_color="#FFFFFF", anchor="w").pack(anchor="w")
        ctk.CTkLabel(txt, text="Attendance System", font=font(11),
                     text_color=C["sidebar_muted"], anchor="w").pack(anchor="w")

        ctk.CTkLabel(sb, text="MENU", font=font(10, "semibold"), text_color=C["sidebar_muted"],
                     anchor="w").pack(fill="x", padx=26, pady=(0, 6))
        self.nav: dict[str, NavButton] = {}
        for key, text, ic in NAV_ITEMS:
            b = NavButton(sb, key, text, ic, self.show_page)
            b.pack(fill="x", padx=14, pady=2)
            self.nav[key] = b

        foot = ctk.CTkFrame(sb, fg_color="transparent")
        foot.pack(side="bottom", fill="x", padx=26, pady=20)
        ctk.CTkFrame(sb, height=1, fg_color=C["sidebar_hover"]).pack(
            side="bottom", fill="x", padx=20)
        self.model_status = ctk.CTkLabel(foot, text="", font=font(11),
                                         text_color=C["sidebar_muted"], anchor="w")
        self.model_status.pack(anchor="w")
        ctk.CTkLabel(foot, text=f"Version {config.APP_VERSION}  ·  Offline", font=font(11),
                     text_color=C["sidebar_muted"], anchor="w").pack(anchor="w", pady=(2, 0))
        self.update_model_status()

    def _build_header(self, parent) -> None:
        hd = ctk.CTkFrame(parent, fg_color="transparent", height=86)
        hd.grid(row=0, column=0, sticky="ew", padx=28, pady=(18, 8))
        hd.grid_columnconfigure(0, weight=1)
        self.title_lbl = ctk.CTkLabel(hd, text="", font=font(22, "semibold"),
                                      text_color=C["text"], anchor="w")
        self.title_lbl.grid(row=0, column=0, sticky="w")
        self.subtitle_lbl = ctk.CTkLabel(hd, text="", font=font(12),
                                         text_color=C["text_muted"], anchor="w")
        self.subtitle_lbl.grid(row=1, column=0, sticky="w")
        clock = Card(hd, corner_radius=8)
        clock.grid(row=0, column=1, rowspan=2, sticky="e")
        ctk.CTkLabel(clock, text="", image=glyph_image("calendar", C["accent"], 16)).pack(
            side="left", padx=(14, 8), pady=10)
        self.date_lbl = ctk.CTkLabel(clock, text="", font=font(12, "semibold"),
                                     text_color=C["text"])
        self.date_lbl.pack(side="left")
        ctk.CTkFrame(clock, width=1, height=20, fg_color=C["border"]).pack(side="left", padx=12)
        ctk.CTkLabel(clock, text="", image=glyph_image("clock", C["accent"], 16)).pack(
            side="left", padx=(0, 8))
        self.time_lbl = ctk.CTkLabel(clock, text="", font=font(12, "semibold"),
                                     text_color=C["text"], width=70, anchor="w")
        self.time_lbl.pack(side="left", padx=(0, 12))

    def _tick(self) -> None:
        if not self.winfo_exists():
            return
        now = datetime.now()
        self.date_lbl.configure(text=now.strftime("%A, %d %B %Y"))
        self.time_lbl.configure(text=now.strftime("%I:%M:%S %p"))
        self._tick_job = self.after(1000, self._tick)

    def _create_page(self, key: str) -> Page:
        cls = {
            "dashboard": DashboardPage,
            "live": LiveAttendancePage,
            "students": StudentsPage,
            "records": AttendanceRecordsPage,
            "reports": ReportsPage,
            "settings": SettingsPage,
        }[key]
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

    def notify(self, message: str, kind: str = "info", duration: int = 3200) -> None:
        Toast.show(self, message, kind, duration)

    def run_in_background(self, func: Callable,
                          on_done: Callable[[object, Optional[Exception]], None]):
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
        def done(result, error):
            if error:
                self.notify(f"Training failed: {error}", "error", 5000)
            else:
                self.recognizer.load()
                self.notify(result.message, "success" if result.success else "warning", 4000)
            self.update_model_status()
            if on_done:
                on_done(result, error)
        self.run_in_background(lambda: train_model(self.db), done)

    def update_model_status(self) -> None:
        if self.recognizer.is_ready:
            n = len(self.recognizer.labels)
            self.model_status.configure(text=f"●  Model ready · {n} enrolled",
                                        text_color="#8FBF9F")
        else:
            self.model_status.configure(text="●  Model not trained", text_color="#D9A066")

    def _on_tk_error(self, exc_type, exc, tb) -> None:
        log.error("Unhandled UI error", exc_info=(exc_type, exc, tb))
        try:
            self.notify(f"Unexpected error: {exc}. Details were written to the log file.",
                        "error", 5000)
        except Exception:              # noqa: BLE001
            pass

    def on_close(self) -> None:
        if self._tick_job:
            try:
                self.after_cancel(self._tick_job)
            except Exception:          # noqa: BLE001
                pass
            self._tick_job = None
        for page in self.pages.values():
            try:
                page.on_hide()
            except Exception:          # noqa: BLE001
                log.exception("Error while closing page")
        log.info("Application closed")
        self.destroy()
