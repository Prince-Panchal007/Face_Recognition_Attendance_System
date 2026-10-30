"""
Reusable UI building blocks so every page looks consistent:
fonts, icons, buttons, cards, stat tiles, styled tables, form fields,
toast notifications, empty states and modal dialogs.
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Callable, Iterable, Optional

import customtkinter as ctk

import config

C = config.COLORS

# --------------------------------------------------------------------------- #
# Fonts & icons
# --------------------------------------------------------------------------- #
_ICON_FONT: Optional[str] = None

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
    """Segoe Fluent Icons (Win 11) or Segoe MDL2 Assets (Win 10), else None."""
    global _ICON_FONT
    if _ICON_FONT is None:
        fams = set(tkfont.families())
        _ICON_FONT = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in fams), "")
    return _ICON_FONT or None


def icon(name: str) -> str:
    return ICONS.get(name, "") if icon_font_family() else ""


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    family = config.FONT_FAMILY_SEMI if weight == "semibold" else config.FONT_FAMILY
    return ctk.CTkFont(family=family, size=size,
                       weight="bold" if weight == "bold" else "normal")


def icon_font(size: int = 14) -> ctk.CTkFont:
    return ctk.CTkFont(family=icon_font_family() or config.FONT_FAMILY, size=size)


# --------------------------------------------------------------------------- #
# Buttons
# --------------------------------------------------------------------------- #
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
    """Button with an optional Fluent icon to the left of the text."""

    def __init__(self, master, text: str = "", icon_name: str = "", command=None,
                 style: str = "secondary", width: int = 0, height: int = 36, size: int = 13):
        super().__init__(master, fg_color="transparent")
        st = BUTTON_STYLES[style]
        glyph = icon(icon_name) if icon_name else ""
        label = f"{glyph}   {text}" if glyph and text else (glyph or text)
        self.btn = ctk.CTkButton(self, text=label, command=command, height=height,
                                 width=width or 0, corner_radius=6, font=font(size, "semibold"),
                                 **st)
        # Icon glyphs live in a different font; render them via a mixed-font trick:
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

    def set_command(self, command) -> None:
        self.btn.configure(command=command)


_GLYPH_CACHE: dict = {}


def _glyph_image(glyph: str, color: str, size: int) -> Optional[ctk.CTkImage]:
    """Render an icon glyph to a CTkImage (so it can sit beside normal text)."""
    from PIL import Image, ImageDraw, ImageFont
    key = (glyph, color, size)
    if key in _GLYPH_CACHE:
        return _GLYPH_CACHE[key]
    path = None
    for p in (r"C:\Windows\Fonts\SegoeIcons.ttf", r"C:\Windows\Fonts\segmdl2.ttf"):
        import os
        if os.path.exists(p):
            path = p
            break
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


# --------------------------------------------------------------------------- #
# Containers
# --------------------------------------------------------------------------- #
class Card(ctk.CTkFrame):
    """White surface with a subtle border."""

    def __init__(self, master, padding: int = 18, **kw):
        kw.setdefault("fg_color", C["surface"])
        kw.setdefault("corner_radius", 8)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", C["border"])
        super().__init__(master, **kw)
        self.padding = padding


class SectionHeader(ctk.CTkFrame):
    """Card title row: title + optional subtitle on the left, actions on the right."""

    def __init__(self, master, title: str, subtitle: str = ""):
        super().__init__(master, fg_color="transparent")
        left = ctk.CTkFrame(self, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(left, text=title, font=font(15, "semibold"), text_color=C["text"],
                     anchor="w").pack(anchor="w")
        self.subtitle = ctk.CTkLabel(left, text=subtitle, font=font(12), text_color=C["text_muted"],
                                     anchor="w")
        if subtitle:
            self.subtitle.pack(anchor="w")
        self.actions = ctk.CTkFrame(self, fg_color="transparent")
        self.actions.pack(side="right")


class StatCard(Card):
    """Statistic tile: icon badge, label, big value, caption."""

    def __init__(self, master, label: str, icon_name: str, tint: str, tint_soft: str):
        super().__init__(master)
        self.grid_columnconfigure(1, weight=1)
        badge = ctk.CTkLabel(self, text="", width=42, height=42, corner_radius=8,
                             fg_color=tint_soft, image=glyph_image(icon_name, tint, 20))
        badge.grid(row=0, column=0, rowspan=2, padx=(18, 14), pady=18, sticky="n")
        ctk.CTkLabel(self, text=label.upper(), font=font(11, "semibold"),
                     text_color=C["text_muted"], anchor="w").grid(row=0, column=1, sticky="sw",
                                                                  pady=(16, 0))
        self.value = ctk.CTkLabel(self, text="0", font=font(26, "semibold"), text_color=C["text"],
                                  anchor="w")
        self.value.grid(row=1, column=1, sticky="nw")
        self.caption = ctk.CTkLabel(self, text="", font=font(11), text_color=C["text_soft"],
                                    anchor="w")
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
        super().__init__(master, text=f"  {text}  ", fg_color=bg, text_color=fg, corner_radius=4,
                         font=font(11, "semibold"), height=22)

    def set(self, text: str, kind: str) -> None:
        bg, fg = self.STYLES[kind]
        self.configure(text=f"  {text}  ", fg_color=bg, text_color=fg)


class EmptyState(ctk.CTkFrame):
    def __init__(self, master, title: str, message: str, icon_name: str = "info"):
        super().__init__(master, fg_color="transparent")
        ctk.CTkLabel(self, text="", image=glyph_image(icon_name, C["text_soft"], 30)).pack(pady=(10, 6))
        ctk.CTkLabel(self, text=title, font=font(13, "semibold"), text_color=C["text"]).pack()
        ctk.CTkLabel(self, text=message, font=font(12), text_color=C["text_muted"],
                     wraplength=360, justify="center").pack(pady=(2, 10))


# --------------------------------------------------------------------------- #
# Styled table (ttk.Treeview)
# --------------------------------------------------------------------------- #
_STYLE_DONE = False


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
    style.configure("FT.Treeview.Heading", background=C["surface_alt"], foreground=C["text_muted"],
                    font=(config.FONT_FAMILY_SEMI, 9), relief="flat", borderwidth=0,
                    padding=(8, int(7 * scale)))
    style.map("FT.Treeview.Heading", background=[("active", C["bg"])])
    style.map("FT.Treeview", background=[("selected", C["accent_soft"])],
              foreground=[("selected", C["text"])])
    style.layout("FT.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.configure("FT.Vertical.TScrollbar", background=C["border"], troughcolor=C["surface"],
                    bordercolor=C["surface"], arrowcolor=C["text_muted"], relief="flat",
                    gripcount=0)
    _STYLE_DONE = True


class DataTable(ctk.CTkFrame):
    """
    Treeview wrapper.
    columns: list of (key, heading, width, anchor)
    """

    def __init__(self, master, columns: list[tuple], height: int = 10,
                 on_select: Optional[Callable] = None, on_double: Optional[Callable] = None,
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
        self.empty = ctk.CTkLabel(self, text=empty_text, font=font(12), text_color=C["text_soft"],
                                  fg_color=C["surface"])
        self._sort_desc = False
        if on_select:
            self.tree.bind("<<TreeviewSelect>>", lambda e: on_select(self.selected()))
        if on_double:
            self.tree.bind("<Double-1>", lambda e: self.selected() and on_double(self.selected()))

    def set_rows(self, rows: Iterable[dict], formatter: Optional[Callable[[dict], tuple]] = None,
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


# --------------------------------------------------------------------------- #
# Form fields
# --------------------------------------------------------------------------- #
def entry(master, placeholder: str = "", width: int = 200, **kw) -> ctk.CTkEntry:
    return ctk.CTkEntry(master, placeholder_text=placeholder, width=width, height=36,
                        corner_radius=6, border_width=1, border_color=C["border_strong"],
                        fg_color=C["surface"], text_color=C["text"],
                        placeholder_text_color=C["text_soft"], font=font(13), **kw)


def option_menu(master, values: list[str], width: int = 180, command=None,
                variable=None) -> ctk.CTkOptionMenu:
    return ctk.CTkOptionMenu(master, values=values, width=width, height=36, corner_radius=6,
                             fg_color=C["surface"], button_color=C["surface_alt"],
                             button_hover_color=C["border"], text_color=C["text"],
                             dropdown_fg_color=C["surface"], dropdown_hover_color=C["accent_soft"],
                             dropdown_text_color=C["text"], font=font(13),
                             dropdown_font=font(13), command=command, variable=variable,
                             dynamic_resizing=False)


def combo(master, values: list[str], width: int = 200, variable=None) -> ctk.CTkComboBox:
    return ctk.CTkComboBox(master, values=values, width=width, height=36, corner_radius=6,
                           border_width=1, border_color=C["border_strong"], fg_color=C["surface"],
                           button_color=C["surface_alt"], button_hover_color=C["border"],
                           text_color=C["text"], dropdown_fg_color=C["surface"],
                           dropdown_hover_color=C["accent_soft"], dropdown_text_color=C["text"],
                           font=font(13), dropdown_font=font(13), variable=variable)


def field_label(master, text: str, required: bool = False) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, text=text + ("  *" if required else ""), font=font(12, "semibold"),
                        text_color=C["text_muted"], anchor="w")


# --------------------------------------------------------------------------- #
# Toast notifications & dialogs
# --------------------------------------------------------------------------- #
class Toast:
    """Small notification that slides in at the bottom-right of the window."""
    KINDS = {"success": (C["success"], "check"), "error": (C["danger"], "warning"),
             "warning": (C["warning"], "warning"), "info": (C["info"], "info")}

    _active: list = []

    @classmethod
    def show(cls, root, message: str, kind: str = "info", duration: int = 3200) -> None:
        color, ic = cls.KINDS.get(kind, cls.KINDS["info"])
        frame = ctk.CTkFrame(root, fg_color=C["sidebar"], corner_radius=8, border_width=0)
        bar = ctk.CTkFrame(frame, fg_color=color, width=5, corner_radius=0)
        bar.pack(side="left", fill="y")
        ctk.CTkLabel(frame, text="", image=glyph_image(ic, color, 18)).pack(side="left",
                                                                           padx=(12, 8), pady=12)
        ctk.CTkLabel(frame, text=message, font=font(12), text_color="#FFFFFF", wraplength=320,
                     justify="left", anchor="w").pack(side="left", padx=(0, 16), pady=12)
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
    """Modal dialog base: centered over the parent, blocks interaction."""

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
        ctk.CTkLabel(body, text="", width=44, height=44, corner_radius=22,
                     fg_color=Badge.STYLES.get({"confirm": "warning", "danger": "danger",
                                                "info": "info", "error": "danger",
                                                "success": "success"}[kind])[0],
                     image=glyph_image(ic, color, 20)).pack(side="left", anchor="n", padx=(0, 16))
        txt = ctk.CTkFrame(body, fg_color="transparent")
        txt.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(txt, text=title, font=font(15, "semibold"), text_color=C["text"],
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(txt, text=message, font=font(12), text_color=C["text_muted"], anchor="w",
                     justify="left", wraplength=320).pack(anchor="w", pady=(6, 0))
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
