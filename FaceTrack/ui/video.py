"""Widget that displays OpenCV frames inside Tk, scaled to fit, with a placeholder."""
from __future__ import annotations

import tkinter as tk

import cv2
import customtkinter as ctk
import numpy as np
from PIL import Image, ImageTk

import config
from ui import components as ui

C = config.COLORS


class VideoView(ctk.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, fg_color="#151B24", corner_radius=8, **kw)
        self.canvas = tk.Label(self, bg="#151B24", bd=0, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=2, pady=2)
        self._photo = None
        self.placeholder = ctk.CTkFrame(self, fg_color="#151B24")
        self.ph_icon = ctk.CTkLabel(self.placeholder, text="",
                                    image=ui.glyph_image("camera", "#5B6676", 40))
        self.ph_icon.pack(pady=(0, 10))
        self.ph_title = ctk.CTkLabel(self.placeholder, text="Camera is off",
                                     font=ui.font(15, "semibold"), text_color="#D5DAE1")
        self.ph_title.pack()
        self.ph_text = ctk.CTkLabel(self.placeholder, text="", font=ui.font(12),
                                    text_color="#8C96A5", wraplength=420, justify="center")
        self.ph_text.pack(pady=(4, 0))
        self.show_placeholder("Camera is off", "")

    def show_placeholder(self, title: str, text: str = "", icon_name: str = "camera") -> None:
        self._photo = None
        self.canvas.configure(image="")
        self.ph_title.configure(text=title)
        self.ph_text.configure(text=text)
        self.ph_icon.configure(image=ui.glyph_image(icon_name, "#5B6676", 40))
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
