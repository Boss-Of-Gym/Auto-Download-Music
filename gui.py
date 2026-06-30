"""
gui.py — десктопный интерфейс AutoDownload.

Единственная ответственность: отобразить настройки, запустить загрузку
в фоновом потоке и показать прогресс в реальном времени.
Взаимодействие с main() — через queue.SimpleQueue, без разделяемого состояния.
"""

import asyncio
import collections
import json
import os
import queue
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from threading import Event
from tkinter import filedialog, messagebox

import customtkinter as ctk

from config import AppConfig, DEFAULT_DOWNLOAD_DIR, MAX_CONCURRENT
from utils import app_dir, safe_filename

# ── Palette ───────────────────────────────────────────────────────────────────
_BG      = "#09090f"
_PANEL   = "#0f0f1a"
_SURFACE = "#161623"
_BORDER  = "#252535"
_ACCENT  = "#7c3aed"
_ACCENT2 = "#4c1d95"
_TEXT    = "#eeeef5"
_MUTED   = "#56567a"
_SUCCESS = "#2dd4bf"
_ERROR   = "#f87171"
_WARN    = "#fbbf24"

_SETTINGS_FILE  = "gui_settings.json"
_MAX_VISIBLE    = 100   # макс. строк треков в списке (rolling window)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ── Tooltip ───────────────────────────────────────────────────────────────────

class _Tooltip:
    """Простой тултип: появляется через 500 мс после наведения, исчезает при уходе."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self._widget = widget
        self._text   = text
        self._win: tk.Toplevel | None = None
        self._job: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide,     add="+")

    def _schedule(self, event=None) -> None:
        self._job = self._widget.after(500, self._show)

    def _show(self) -> None:
        if self._win:
            return
        x = self._widget.winfo_rootx() + self._widget.winfo_width() // 2 - 70
        y = self._widget.winfo_rooty() - 36
        self._win = tk.Toplevel(self._widget)
        self._win.wm_overrideredirect(True)
        self._win.wm_geometry(f"+{x}+{y}")
        self._win.configure(background=_BORDER)
        tk.Label(
            self._win, text=self._text,
            background=_SURFACE, foreground=_TEXT,
            font=("Segoe UI", 9), padx=10, pady=5,
        ).pack(padx=1, pady=1)

    def _hide(self, event=None) -> None:
        if self._job:
            self._widget.after_cancel(self._job)
            self._job = None
        if self._win:
            self._win.destroy()
            self._win = None


# ── Track row widget ──────────────────────────────────────────────────────────

class _TrackRow(ctk.CTkFrame):
    """Одна строка трека в списке прогресса."""

    _SPIN = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
    _STRIPE_COL = {"searching": _WARN, "downloaded": _SUCCESS, "not_found": _ERROR}

    def __init__(self, master, track: str, **kwargs):
        super().__init__(master, fg_color=_SURFACE, corner_radius=8, **kwargs)
        self.grid_columnconfigure(0, weight=0, minsize=3)
        self.grid_columnconfigure(2, weight=1)

        self._spin_idx = 0
        self._spin_job = None

        self._stripe = tk.Frame(self, width=3, bg=_BORDER, bd=0, highlightthickness=0)
        self._stripe.grid(row=0, column=0, sticky="ns", padx=0, pady=2)

        self._icon = ctk.CTkLabel(
            self, text="·", width=24,
            font=ctk.CTkFont(size=14), text_color=_MUTED,
        )
        self._icon.grid(row=0, column=1, padx=(8, 0), pady=10)

        self._name = ctk.CTkLabel(
            self, text=track, anchor="w",
            font=ctk.CTkFont(size=12), text_color=_MUTED,
            wraplength=380,
        )
        self._name.grid(row=0, column=2, padx=(6, 14), pady=10, sticky="ew")

        for w in (self, self._stripe, self._icon, self._name):
            w.bind("<Button-1>", self._copy_name, add="+")
            w.bind("<Enter>",    self._on_hover_enter, add="+")
            w.bind("<Leave>",    self._on_hover_leave, add="+")
        for w in (self._stripe, self._icon, self._name):
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass

    def _copy_name(self, event=None) -> None:
        name = self._name.cget("text")
        self.clipboard_clear()
        self.clipboard_append(name)
        orig = self._stripe.cget("bg")
        self._stripe.configure(bg="#a78bfa")
        self.after(400, lambda b=orig: self._stripe.configure(bg=b))

    def _on_hover_enter(self, event=None) -> None:
        self.configure(fg_color="#1c1c2e")

    def _on_hover_leave(self, event=None) -> None:
        x, y = self.winfo_pointerxy()
        rx, ry = self.winfo_rootx(), self.winfo_rooty()
        if not (rx <= x <= rx + self.winfo_width() and ry <= y <= ry + self.winfo_height()):
            self.configure(fg_color=_SURFACE)

    def set_status(self, status: str) -> None:
        if self._spin_job:
            self.after_cancel(self._spin_job)
            self._spin_job = None

        self._stripe.configure(bg=self._STRIPE_COL.get(status, _BORDER))

        if status == "searching":
            self._name.configure(text_color=_TEXT)
            self._spin()
        elif status == "downloaded":
            self._icon.configure(text="✓", text_color=_SUCCESS)
            self._name.configure(text_color=_TEXT)
        elif status == "not_found":
            self._icon.configure(text="✗", text_color=_ERROR)
            self._name.configure(text_color=_MUTED)

    def set_wrap(self, container_width: int) -> None:
        """Обновляет wraplength под текущую ширину контейнера."""
        wrap = max(100, container_width - 70)
        self._name.configure(wraplength=wrap)

    def get_name(self) -> str:
        return self._name.cget("text")

    def _spin(self) -> None:
        self._icon.configure(text=self._SPIN[self._spin_idx], text_color=_WARN)
        self._spin_idx = (self._spin_idx + 1) % len(self._SPIN)
        self._spin_job = self.after(80, self._spin)


# ── Main window ───────────────────────────────────────────────────────────────

class AutoDownloadApp(ctk.CTk):

    def __init__(self) -> None:
        super().__init__()
        self.title("AutoDownload")
        self.geometry("960x640")
        self.minsize(820, 520)
        self.configure(fg_color=_BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._q: queue.SimpleQueue = queue.SimpleQueue()
        self._rows: dict[int, _TrackRow] = {}
        self._rows_status: dict[int, str] = {}  # точное состояние каждого трека
        self._running = False
        self._cancelled = False
        self._thread: threading.Thread | None = None
        self._threads_val = MAX_CONCURRENT
        self._counts = {"downloaded": 0, "not_found": 0, "searching": 0}
        self._total = 0
        self._otp_event: Event = Event()
        self._otp_code: str = ""
        self._download_dir: Path = DEFAULT_DOWNLOAD_DIR

        # Parsing progress animation state
        self._parsing = False
        self._anim_job: str | None = None
        self._parse_val = 0.0
        self._parse_dir = 1

        # Yandex inline error labels
        self._yx_err: dict[str, ctk.CTkLabel] = {}

        # Asyncio loop/task для отмены из GUI-потока
        self._async_loop: asyncio.AbstractEventLoop | None = None
        self._async_task = None
        self._task_ready: threading.Event | None = None

        # Rolling window — счётчик строк и очереди видимости
        self._next_row: int = 0
        self._display_queue: collections.deque = collections.deque()
        self._removed_from_view: set = set()

        # ETA — монотонное время начала первой загрузки
        self._start_time: float | None = None

        self.bind("<Return>", self._on_return_key)
        self.bind("<Escape>", self._on_escape_key)

        self._build()
        self._load_settings()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=300)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self, fg_color=_PANEL, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew")
        self._build_left(left)

        right = ctk.CTkFrame(self, fg_color=_BG, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        self._build_right(right)

    def _build_left(self, p: ctk.CTkFrame) -> None:
        p.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(0, weight=1)

        settings = ctk.CTkScrollableFrame(
            p, fg_color="transparent",
            scrollbar_button_color=_BORDER,
            scrollbar_button_hover_color=_ACCENT,
        )
        settings.grid(row=0, column=0, sticky="nsew")
        settings.grid_columnconfigure(0, weight=1)

        r = 0

        _logo_f = ctk.CTkFrame(settings, fg_color="transparent")
        _logo_f.grid(row=r, column=0, padx=24, pady=(28, 2), sticky="w"); r += 1
        _logo_box = ctk.CTkFrame(_logo_f, width=28, height=28, corner_radius=7, fg_color=_ACCENT)
        _logo_box.pack_propagate(False)
        _logo_box.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(_logo_box, text="↓", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=_TEXT, fg_color="transparent").pack(expand=True)
        ctk.CTkLabel(_logo_f, text="AutoDownload",
                     font=ctk.CTkFont(size=19, weight="bold"), text_color=_TEXT,
                     ).pack(side="left")
        ctk.CTkLabel(settings, text="Поиск и загрузка MP3",
                     font=ctk.CTkFont(size=11), text_color=_MUTED,
                     ).grid(row=r, column=0, padx=24, pady=(0, 18), sticky="w"); r += 1

        ctk.CTkFrame(settings, height=1, fg_color=_BORDER
                     ).grid(row=r, column=0, padx=20, pady=(0, 18), sticky="ew"); r += 1

        # Source mode
        self._lbl(settings, r, "ИСТОЧНИК"); r += 1
        self._src = ctk.CTkSegmentedButton(
            settings, values=["JSON файл", "Яндекс.Музыка"],
            command=self._on_src,
            fg_color=_SURFACE,
            selected_color=_ACCENT, selected_hover_color=_ACCENT2,
            unselected_color=_SURFACE, unselected_hover_color=_BORDER,
            text_color=_TEXT, font=ctk.CTkFont(size=12),
        )
        self._src.set("JSON файл")
        self._src.grid(row=r, column=0, padx=24, pady=(5, 6), sticky="ew"); r += 1
        self._src_hint = ctk.CTkLabel(
            settings, text="Загрузка списка треков из .json-файла",
            font=ctk.CTkFont(size=10), text_color=_MUTED, anchor="w",
        )
        self._src_hint.grid(row=r, column=0, padx=24, pady=(0, 10), sticky="w"); r += 1

        # JSON frame
        self._json_f = ctk.CTkFrame(settings, fg_color="transparent")
        self._json_f.grid(row=r, column=0, padx=24, sticky="ew")
        self._json_f.grid_columnconfigure(0, weight=1)
        self._json_entry = self._entry_row(
            self._json_f, "Файл .json или имя плейлиста", "playlist_name", self._browse_json
        )

        # Yandex frame (hidden initially)
        self._yx_f = ctk.CTkFrame(settings, fg_color="transparent")
        self._yx_f.grid(row=r, column=0, padx=24, sticky="ew")
        self._yx_f.grid_columnconfigure(0, weight=1)
        self._yx_f.grid_remove()

        self._yx = {}
        _REQUIRED = {"phone", "login", "account", "playlist"}
        yx_fields = [
            ("phone",    "Телефон *",     "+7 999 000-00-00"),
            ("login",    "Логин *",       "ник из music.yandex.ru/users/НИК"),
            ("account",  "Имя в шапке *", "Иван Иванов"),
            ("playlist", "Плейлист *",    "Мне нравится"),
        ]
        for i, (key, label, ph) in enumerate(yx_fields):
            base = i * 3
            ctk.CTkLabel(self._yx_f, text=label, font=ctk.CTkFont(size=11),
                         text_color=_MUTED,
                         ).grid(row=base, column=0, sticky="w",
                                pady=(0 if i == 0 else 10, 0))
            e = ctk.CTkEntry(self._yx_f, placeholder_text=ph,
                             fg_color=_SURFACE, border_color=_BORDER,
                             text_color=_TEXT, height=34)
            e.grid(row=base + 1, column=0, sticky="ew", pady=(3, 0))
            self._yx[key] = e

            err = ctk.CTkLabel(self._yx_f, text="",
                               font=ctk.CTkFont(size=10), text_color=_ERROR, anchor="w")
            err.grid(row=base + 2, column=0, sticky="w", padx=2, pady=0)
            self._yx_err[key] = err

            if key in _REQUIRED:
                e.bind("<Key>", lambda ev, k=key: self._clear_yx_error(k))

        r += 1

        ctk.CTkFrame(settings, height=1, fg_color=_BORDER
                     ).grid(row=r, column=0, padx=20, pady=(16, 16), sticky="ew"); r += 1

        # Download dir
        self._lbl(settings, r, "ПАПКА ЗАГРУЗОК"); r += 1
        dl_f = ctk.CTkFrame(settings, fg_color="transparent")
        dl_f.grid(row=r, column=0, padx=24, pady=(5, 0), sticky="ew")
        dl_f.grid_columnconfigure(0, weight=1)
        self._dl_entry = self._entry_row(dl_f, None, str(DEFAULT_DOWNLOAD_DIR),
                                         self._browse_dir, insert=str(DEFAULT_DOWNLOAD_DIR))
        r += 1

        # Threads slider
        self._lbl(settings, r, "ПАРАЛЛЕЛЬНЫХ ПОТОКОВ"); r += 1
        sl_f = ctk.CTkFrame(settings, fg_color="transparent")
        sl_f.grid(row=r, column=0, padx=24, pady=(5, 0), sticky="ew")
        sl_f.grid_columnconfigure(0, weight=1)

        self._thr_lbl = ctk.CTkLabel(sl_f, text=str(MAX_CONCURRENT), width=28,
                                     font=ctk.CTkFont(size=15, weight="bold"),
                                     text_color=_ACCENT)
        self._thr_lbl.grid(row=0, column=1, padx=(10, 0))

        self._slider = ctk.CTkSlider(
            sl_f, from_=1, to=10, number_of_steps=9,
            button_color=_ACCENT, button_hover_color=_ACCENT2,
            progress_color=_ACCENT, fg_color=_SURFACE,
            command=self._on_threads,
        )
        self._slider.set(MAX_CONCURRENT)
        self._slider.grid(row=0, column=0, sticky="ew")
        r += 1

        # Headless checkbox
        self._headless_var = tk.BooleanVar(value=False)
        self._headless_cb = ctk.CTkCheckBox(
            settings, text="Запускать браузер в фоне",
            variable=self._headless_var,
            font=ctk.CTkFont(size=12), text_color=_TEXT,
            fg_color=_ACCENT, hover_color=_ACCENT2,
            border_color=_BORDER, checkmark_color=_TEXT,
        )
        self._headless_cb.grid(row=r, column=0, padx=24, pady=(14, 0), sticky="w"); r += 1

        # Track limit
        self._lbl(settings, r, "МАКСИМУМ ТРЕКОВ"); r += 1
        self._limit = ctk.CTkEntry(settings, placeholder_text="Все",
                                   fg_color=_SURFACE, border_color=_BORDER,
                                   text_color=_TEXT, height=34)
        self._limit.grid(row=r, column=0, padx=24, pady=(5, 20), sticky="ew")

        # Список виджетов, блокируемых во время работы
        self._lockable = [
            self._src, self._json_entry, self._dl_entry,
            self._slider, self._limit, self._headless_cb,
            *self._yx.values(),
        ]

        # Fixed bottom — всегда виден, не зависит от высоты настроек
        bot = ctk.CTkFrame(p, fg_color=_PANEL, corner_radius=0)
        bot.grid(row=1, column=0, sticky="ew")
        bot.grid_columnconfigure(0, weight=1)
        bot.grid_columnconfigure(1, weight=0)

        ctk.CTkFrame(bot, height=1, fg_color=_BORDER
                     ).grid(row=0, column=0, columnspan=2, padx=20, sticky="ew")

        self._start_btn = ctk.CTkButton(
            bot, text="▶  Запустить",
            fg_color=_ACCENT, hover_color=_ACCENT2, text_color=_TEXT,
            height=44, font=ctk.CTkFont(size=14, weight="bold"), corner_radius=12,
            border_color="#a78bfa", border_width=1,
            cursor="hand2",
            command=self._on_start,
        )
        self._start_btn.grid(row=1, column=0, padx=(24, 6), pady=20, sticky="ew")

        # Кнопка "Открыть папку" — появляется только после завершения
        self._open_btn = ctk.CTkButton(
            bot, text="📂",
            fg_color=_SURFACE, hover_color=_BORDER, text_color=_TEXT,
            height=44, width=48, font=ctk.CTkFont(size=16), corner_radius=12,
            border_color=_BORDER, border_width=1,
            cursor="hand2",
            command=self._open_folder,
        )
        self._open_btn.grid(row=1, column=1, padx=(0, 24), pady=20)
        self._open_btn.grid_remove()
        _Tooltip(self._open_btn, "Открыть папку загрузок")

        ctk.CTkLabel(
            bot, text="Enter — запустить  ·  Esc — стоп",
            font=ctk.CTkFont(size=10), text_color=_MUTED,
        ).grid(row=2, column=0, columnspan=2, pady=(0, 14))

    def _build_right(self, p: ctk.CTkFrame) -> None:
        p.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(p, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=24, pady=(24, 0), sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)

        title_f = ctk.CTkFrame(hdr, fg_color="transparent")
        title_f.grid(row=0, column=0, sticky="ew")
        title_f.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(title_f, text="Прогресс",
                     font=ctk.CTkFont(size=15, weight="bold"), text_color=_TEXT,
                     ).grid(row=0, column=0, sticky="w")

        # Счётчик "N / M" справа от заголовка
        self._counter_lbl = ctk.CTkLabel(
            title_f, text="",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=_ACCENT,
        )
        self._counter_lbl.grid(row=0, column=1, sticky="e")

        self._status_lbl = ctk.CTkLabel(hdr, text="Ожидание запуска",
                                        font=ctk.CTkFont(size=11), text_color=_MUTED)
        self._status_lbl.grid(row=1, column=0, sticky="w")

        self._scroll = ctk.CTkScrollableFrame(
            p, fg_color=_PANEL, corner_radius=12,
            scrollbar_button_color=_SURFACE,
            scrollbar_button_hover_color=_ACCENT,
        )
        self._scroll.grid(row=1, column=0, padx=24, pady=16, sticky="nsew")
        self._scroll.grid_columnconfigure(0, weight=1)
        self._scroll.bind("<Configure>", self._on_scroll_resize)

        self._empty_lbl = ctk.CTkLabel(
            self._scroll,
            text="Треки появятся здесь после запуска\n\nНастройте источник слева и нажмите  ▶  Запустить",
            font=ctk.CTkFont(size=12), text_color=_MUTED,
            justify="center",
        )
        self._empty_lbl.grid(row=0, column=0, pady=64)

        # Stats bar
        bar = ctk.CTkFrame(p, fg_color=_PANEL, corner_radius=12)
        bar.grid(row=2, column=0, padx=24, pady=(0, 20), sticky="ew")
        bar.grid_columnconfigure(1, weight=1)

        self._pb = ctk.CTkProgressBar(bar, height=6,
                                      progress_color=_ACCENT, fg_color=_SURFACE)
        self._pb.set(0)
        self._pb.grid(row=0, column=0, columnspan=4, padx=16, pady=(12, 6), sticky="ew")

        self._lbl_ok = ctk.CTkLabel(
            bar, text="✓  0", font=ctk.CTkFont(size=11, weight="bold"),
            text_color=_SUCCESS, fg_color="#0d3533", corner_radius=20,
            padx=10, pady=4,
        )
        self._lbl_ok.grid(row=1, column=0, padx=(16, 4), pady=(0, 12), sticky="w")

        self._lbl_srch = ctk.CTkLabel(
            bar, text="◌  0", font=ctk.CTkFont(size=11, weight="bold"),
            text_color=_WARN, fg_color="#3d2b0a", corner_radius=20,
            padx=10, pady=4,
        )
        self._lbl_srch.grid(row=1, column=1, padx=4, pady=(0, 12))

        self._lbl_nf = ctk.CTkLabel(
            bar, text="✗  0", font=ctk.CTkFont(size=11, weight="bold"),
            text_color=_ERROR, fg_color="#3a1111", corner_radius=20,
            padx=10, pady=4,
        )
        self._lbl_nf.grid(row=1, column=2, padx=4, pady=(0, 12))

        # Кнопка "Скопировать ненайденные" — появляется после завершения если nf > 0.
        # Копирует в буфер обмена список треков, которые не удалось найти ни на одном сайте.
        self._copy_btn = ctk.CTkButton(
            bar, text="Скопировать ненайденные в буфер", height=28,
            font=ctk.CTkFont(size=10),
            fg_color=_SURFACE, hover_color=_BORDER,
            border_color=_BORDER, border_width=1,
            text_color=_MUTED, corner_radius=6,
            cursor="hand2",
            command=self._copy_not_found,
        )
        self._copy_btn.grid(row=2, column=0, columnspan=4, padx=16, pady=(0, 12), sticky="e")
        self._copy_btn.grid_remove()
        _Tooltip(self._copy_btn, "Скопировать в буфер список ненайденных треков")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _lbl(self, parent, row: int, text: str) -> None:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=row, column=0, padx=24, pady=(14, 0), sticky="w")
        tk.Frame(f, width=3, height=10, bg=_ACCENT, bd=0, highlightthickness=0
                 ).pack(side="left", padx=(0, 7), pady=1)
        ctk.CTkLabel(f, text=text, font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=_MUTED,
                     ).pack(side="left")

    def _entry_row(self, parent, label, placeholder, browse_cmd,
                   insert: str | None = None) -> ctk.CTkEntry:
        if label:
            ctk.CTkLabel(parent, text=label, font=ctk.CTkFont(size=11),
                         text_color=_MUTED,
                         ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 3))
            entry_row = 1
        else:
            entry_row = 0

        entry = ctk.CTkEntry(parent, placeholder_text=placeholder,
                             fg_color=_SURFACE, border_color=_BORDER,
                             text_color=_TEXT, height=36)
        entry.grid(row=entry_row, column=0, sticky="ew")
        if insert:
            entry.insert(0, insert)

        ctk.CTkButton(parent, text="…", width=36, height=36,
                      fg_color=_SURFACE, hover_color=_ACCENT2,
                      border_color=_BORDER, border_width=1,
                      text_color=_TEXT, command=browse_cmd,
                      ).grid(row=entry_row, column=1, padx=(6, 0))
        return entry

    # ── Settings persistence ──────────────────────────────────────────────────

    def _settings_path(self) -> Path:
        return app_dir() / _SETTINGS_FILE

    def _load_settings(self) -> None:
        try:
            data = json.loads(self._settings_path().read_text(encoding="utf-8"))
        except Exception:
            return

        if data.get("source_mode") == "yandex":
            self._src.set("Яндекс.Музыка")
            self._on_src("Яндекс.Музыка")

        if v := data.get("json_path"):
            self._json_entry.delete(0, "end")
            self._json_entry.insert(0, v)

        for key in ("phone", "login", "account", "playlist"):
            if v := data.get(f"yandex_{key}"):
                self._yx[key].delete(0, "end")
                self._yx[key].insert(0, v)

        if v := data.get("download_dir"):
            self._dl_entry.delete(0, "end")
            self._dl_entry.insert(0, v)

        if v := data.get("threads"):
            self._threads_val = int(v)
            self._slider.set(self._threads_val)
            self._thr_lbl.configure(text=str(self._threads_val))

        self._headless_var.set(bool(data.get("headless", False)))

        if v := data.get("geometry"):
            try:
                self.geometry(v)
            except Exception:
                pass

        if v := data.get("track_limit"):
            self._limit.delete(0, "end")
            self._limit.insert(0, str(v))

    def _save_settings(self) -> None:
        data = {
            "source_mode": "yandex" if self._src.get() == "Яндекс.Музыка" else "json",
            "json_path": self._json_entry.get().strip(),
            "yandex_phone": self._yx["phone"].get().strip(),
            "yandex_login": self._yx["login"].get().strip(),
            "yandex_account": self._yx["account"].get().strip(),
            "yandex_playlist": self._yx["playlist"].get().strip(),
            "download_dir": self._dl_entry.get().strip(),
            "threads": self._threads_val,
            "headless": self._headless_var.get(),
            "track_limit": self._limit.get().strip(),
            "geometry": self.geometry(),
        }
        try:
            self._settings_path().write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_src(self, value: str) -> None:
        if value == "JSON файл":
            self._yx_f.grid_remove()
            self._json_f.grid()
            self._src_hint.configure(text="Загрузка списка треков из .json-файла")
        else:
            self._json_f.grid_remove()
            self._yx_f.grid()
            self._src_hint.configure(text="Авторизация и парсинг плейлиста Яндекс.Музыки")

    def _on_threads(self, val: float) -> None:
        self._threads_val = int(val)
        self._thr_lbl.configure(text=str(self._threads_val))

    def _on_scroll_resize(self, event=None) -> None:
        """Обновляет wraplength всех строк при изменении ширины прокручиваемой области."""
        w = self._scroll.winfo_width()
        if w > 60:
            for row in self._rows.values():
                row.set_wrap(w)

    def _browse_json(self) -> None:
        path = filedialog.askopenfilename(
            title="Выберите JSON файл",
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")],
        )
        if path:
            self._json_entry.delete(0, "end")
            self._json_entry.insert(0, path)

    def _browse_dir(self) -> None:
        path = filedialog.askdirectory(title="Папка загрузок")
        if path:
            self._dl_entry.delete(0, "end")
            self._dl_entry.insert(0, path)

    def _open_folder(self) -> None:
        try:
            os.startfile(self._download_dir)
        except Exception:
            pass

    def _copy_not_found(self) -> None:
        nf_tracks = [
            self._rows[idx].get_name()
            for idx, st in self._rows_status.items()
            if st == "not_found"
        ]
        if nf_tracks:
            self.clipboard_clear()
            self.clipboard_append("\n".join(nf_tracks))

    def _on_close(self) -> None:
        if self._running:
            if not messagebox.askyesno(
                "Выход",
                "Скачивание ещё идёт. Остановить и выйти?",
                icon="warning",
            ):
                return
            self._cancel_run()
            # Даём потоку 5 сек завершиться (закрыть браузер) перед уничтожением окна
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=5)
        self._save_settings()
        self.destroy()

    # ── Yandex field validation ───────────────────────────────────────────────

    def _validate_yandex(self) -> bool:
        checks = {
            "phone":    "Введите номер телефона",
            "login":    "Введите логин (URL-ник)",
            "account":  "Введите имя аккаунта в шапке сайта",
            "playlist": "Введите название плейлиста",
        }
        for key in checks:
            self._clear_yx_error(key)
        valid = True
        for key, msg in checks.items():
            if not self._yx[key].get().strip():
                self._yx_err[key].configure(text=f"↑  {msg}")
                self._yx[key].configure(border_color=_ERROR)
                valid = False
        return valid

    def _clear_yx_error(self, key: str) -> None:
        self._yx_err[key].configure(text="")
        self._yx[key].configure(border_color=_BORDER)

    # ── Start / Stop / config ─────────────────────────────────────────────────

    def _set_inputs_state(self, state: str) -> None:
        for w in self._lockable:
            try:
                w.configure(state=state)
            except Exception:
                pass

    def _on_start(self) -> None:
        if self._running:
            return

        try:
            config = self._build_config()
        except ValueError as exc:
            if str(exc):
                self._status_lbl.configure(text=str(exc), text_color=_ERROR)
            return

        self._download_dir = config.download_dir
        self._reset_progress()
        self._running = True
        self._cancelled = False

        self._start_btn.configure(
            text="■  Стоп",
            fg_color="#7f1d1d", hover_color="#991b1b",
            border_color="#f87171",
            command=self._on_stop,
        )
        self._open_btn.grid_remove()
        self._copy_btn.grid_remove()
        self._set_inputs_state("disabled")

        self._counts = {"downloaded": 0, "not_found": 0, "searching": 0}
        self._total = 0
        self._rows.clear()
        self._rows_status.clear()
        self.title("AutoDownload — Запуск")

        # Новая очередь исключает остатки от прошлого запуска
        self._q = queue.SimpleQueue()
        self._async_loop = None
        self._async_task = None
        self._task_ready = threading.Event()

        self._thread = threading.Thread(
            target=self._run, args=(config,), daemon=True,
        )
        self._thread.start()
        self.after(100, self._poll)

    def _on_stop(self) -> None:
        if not self._running:
            return
        self._cancelled = True
        self._start_btn.configure(state="disabled", text="Остановка…")
        self._cancel_run()

    def _cancel_run(self) -> None:
        """Отменяет текущий asyncio-таск из GUI-потока."""
        # Ждём пока _wrapper установит _async_task (защита от гонки при быстрой отмене)
        if self._task_ready:
            self._task_ready.wait(timeout=3)
        loop = self._async_loop
        task = self._async_task
        if loop and task:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except Exception:
                pass

    def _build_config(self) -> AppConfig:
        src = "json" if self._src.get() == "JSON файл" else "yandex"

        dl_raw = self._dl_entry.get().strip()
        download_dir = Path(dl_raw) if dl_raw else DEFAULT_DOWNLOAD_DIR

        limit_raw = self._limit.get().strip()
        if limit_raw:
            if not limit_raw.isdigit() or int(limit_raw) <= 0:
                raise ValueError("Максимум треков: введите целое положительное число")
            track_limit: int | None = int(limit_raw)
        else:
            track_limit = None

        headless = self._headless_var.get()

        if src == "json":
            raw = self._json_entry.get().strip()
            if not raw:
                raise ValueError("Укажите путь к JSON-файлу или имя плейлиста")
            p = Path(raw)
            if p.suffix.lower() != ".json":
                p = app_dir() / (safe_filename(raw) + "_tracks.json")
            return AppConfig(
                source_mode="json",
                download_dir=download_dir,
                track_limit=track_limit,
                max_concurrent=self._threads_val,
                headless=headless,
                track_file_path=p,
            )

        if not self._validate_yandex():
            raise ValueError("")

        return AppConfig(
            source_mode="yandex",
            download_dir=download_dir,
            track_limit=track_limit,
            max_concurrent=self._threads_val,
            headless=headless,
            yandex_phone=self._yx["phone"].get().strip(),
            yandex_login=self._yx["login"].get().strip(),
            yandex_account_name=self._yx["account"].get().strip(),
            name_playlist=self._yx["playlist"].get().strip(),
        )

    # ── Background thread ─────────────────────────────────────────────────────

    def _run(self, config: AppConfig) -> None:
        from main import main as _async_main

        def _cb(index: int, track: str, status: str) -> None:
            self._q.put_nowait((index, track, status))

        def _code_cb() -> str:
            self._otp_event.clear()
            self._q.put_nowait((-2, "", "otp_request"))
            # Таймаут 120 с: если пользователь закрыл диалог — не висим вечно
            if not self._otp_event.wait(timeout=120):
                return ""
            return self._otp_code

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._async_loop = loop

        async def _wrapper() -> None:
            self._async_task = asyncio.current_task()
            # Сигнализируем GUI-потоку, что задача готова к отмене
            if self._task_ready:
                self._task_ready.set()
            try:
                await _async_main(config, on_progress=_cb, code_callback=_code_cb)
            except asyncio.CancelledError:
                _cb(-1, "Остановлено пользователем", "cancelled")
            except Exception as exc:
                _cb(-1, f"Ошибка: {exc}", "error")

        try:
            loop.run_until_complete(_wrapper())
        finally:
            loop.close()
            self._async_loop = None

    # ── Progress polling (tkinter main thread) ────────────────────────────────

    def _poll(self) -> None:
        new_rows = False
        try:
            while True:
                item = self._q.get_nowait()
                if self._handle(*item):
                    new_rows = True
        except queue.Empty:
            pass

        # После добавления новых строк принудительно обновляем scrollregion canvas —
        # иначе CTkScrollableFrame не показывает все строки при быстром добавлении
        if new_rows:
            self.after(30, self._fix_scroll_region)

        if self._thread and self._thread.is_alive():
            self.after(100, self._poll)
        else:
            self._on_done()

    def _handle(self, index: int, track: str, status: str) -> bool:
        """Обрабатывает одно событие из очереди. Возвращает True если добавлена новая строка."""
        if index == -2:
            self._show_otp_dialog()
            return False

        if index == -1:
            if status == "parsing":
                # Пытаемся извлечь "X / Y" из сообщения — переходим на детерминированный прогресс
                m = re.search(r'(\d+)\s*/\s*(\d+)', track)
                if m:
                    cur, total = int(m.group(1)), int(m.group(2))
                    if total > 0:
                        self._stop_parse_anim()
                        self._pb.set(cur / total)
                    self._status_lbl.configure(
                        text=f"Сбор треков: {cur} / {total or '?'}",
                        text_color=_WARN,
                    )
                    self._counter_lbl.configure(text=f"{cur} / {total or '?'}")
                else:
                    # Нет данных о прогрессе — используем анимацию
                    if self._empty_lbl and self._empty_lbl.winfo_exists():
                        self._empty_lbl.configure(text=track)
                    self._status_lbl.configure(text=track, text_color=_WARN)
                    self._start_parse_anim()
            elif status == "error":
                self._stop_parse_anim()
                self._pb.set(0)
                self._status_lbl.configure(text=track, text_color=_ERROR)
            elif status == "cancelled":
                self._stop_parse_anim()
                self._status_lbl.configure(text=track, text_color=_WARN)
            else:
                self._stop_parse_anim()
                self._status_lbl.configure(text=track, text_color=_MUTED)
            return False

        # Трек убран из отображения (rolling window) — только счётчики
        if index in self._removed_from_view:
            prev = self._rows_status.get(index, "pending")
            self._rows_status[index] = status
            self._update_counts(prev, status)
            self._refresh_stats()
            return False

        new_row = False

        if index not in self._rows:
            if self._parsing:
                self._stop_parse_anim()
                self._pb.set(0)
            if self._empty_lbl and self._empty_lbl.winfo_exists():
                self._empty_lbl.destroy()

            row = _TrackRow(self._scroll, track)
            row.grid(row=self._next_row, column=0, sticky="ew", padx=6, pady=3)
            self._next_row += 1
            w = self._scroll.winfo_width()
            if w > 60:
                row.set_wrap(w)
            self._rows[index] = row
            self._rows_status[index] = "pending"
            self._total += 1
            self._display_queue.append(index)
            new_row = True

            # Rolling window: если строк больше лимита — скрываем самую старую
            if len(self._display_queue) > _MAX_VISIBLE:
                old_idx = self._display_queue.popleft()
                if old_idx in self._rows:
                    self._rows[old_idx].destroy()
                    del self._rows[old_idx]
                    self._removed_from_view.add(old_idx)

            self.after(10, self._scroll_to_bottom)
        elif self._parsing:
            self._stop_parse_anim()
            self._pb.set(0)

        prev = self._rows_status.get(index, "pending")
        if index in self._rows:
            self._rows[index].set_status(status)
        self._rows_status[index] = status
        self._update_counts(prev, status)
        self._refresh_stats()
        return new_row

    def _update_counts(self, prev: str, status: str) -> None:
        """Точный подсчёт через переходы состояний (без дрейфа счётчика)."""
        if prev == "searching" and status in ("downloaded", "not_found"):
            self._counts["searching"] = max(0, self._counts["searching"] - 1)
        if status == "searching" and prev != "searching":
            self._counts["searching"] += 1
            if self._start_time is None:
                self._start_time = time.monotonic()
        elif status == "downloaded" and prev != "downloaded":
            self._counts["downloaded"] += 1
        elif status == "not_found" and prev != "not_found":
            self._counts["not_found"] += 1

    def _on_return_key(self, event=None) -> None:
        if not self._running and not isinstance(self.focus_get(), (tk.Entry, ctk.CTkEntry)):
            self._on_start()

    def _on_escape_key(self, event=None) -> None:
        if self._running:
            self._on_stop()

    def _fix_scroll_region(self) -> None:
        """Обновляет scrollregion canvas после добавления строк — исправляет баг CTkScrollableFrame
        где последние строки не отображаются при быстром пакетном добавлении."""
        try:
            canvas = getattr(self._scroll, "_parent_canvas", None)
            if canvas:
                self._scroll.update_idletasks()
                canvas.configure(scrollregion=canvas.bbox("all"))
        except Exception:
            pass

    def _scroll_to_bottom(self) -> None:
        try:
            canvas = getattr(self._scroll, "_parent_canvas", None)
            if canvas:
                canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _show_otp_dialog(self) -> None:
        self._status_lbl.configure(
            text="Введите код из push-уведомления Яндекс", text_color=_WARN,
        )
        dialog = ctk.CTkInputDialog(
            title="Яндекс ID — подтверждение",
            text=(
                "Push-уведомление отправлено на номер телефона.\n\n"
                "Введите 6-значный код подтверждения:"
            ),
        )
        code = dialog.get_input()
        self._otp_code = (code or "").strip()
        self._status_lbl.configure(text="Авторизация...", text_color=_MUTED)
        self._otp_event.set()

    def _refresh_stats(self) -> None:
        d  = self._counts["downloaded"]
        nf = self._counts["not_found"]
        s  = self._counts["searching"]
        done = d + nf

        self._lbl_ok.configure(text=f"✓  {d}")
        self._lbl_srch.configure(text=f"◌  {s}")
        self._lbl_nf.configure(text=f"✗  {nf}")

        if self._total:
            self._pb.set(done / self._total)
            self._counter_lbl.configure(text=f"{done} / {self._total}")
            self.title(f"AutoDownload — {done} / {self._total}")

        if not self._parsing:
            status_text = f"Обработано {done} из {self._total}"
            if self._start_time and done > 0 and self._total and done < self._total:
                elapsed = time.monotonic() - self._start_time
                if elapsed > 3:
                    remaining = self._total - done
                    rate = done / elapsed
                    if rate > 0:
                        eta = remaining / rate
                        eta_str = f"~{max(1, int(eta))} сек" if eta < 90 else f"~{int(eta / 60) + 1} мин"
                        status_text += f"  ·  {eta_str}"
            self._status_lbl.configure(text=status_text, text_color=_MUTED)

    def _reset_progress(self) -> None:
        self._stop_parse_anim()
        for w in self._scroll.winfo_children():
            w.destroy()
        self._empty_lbl = ctk.CTkLabel(
            self._scroll, text="Загрузка...",
            font=ctk.CTkFont(size=12), text_color=_MUTED,
        )
        self._empty_lbl.grid(row=0, column=0, pady=48)

        # Сброс rolling window
        self._next_row = 0
        self._display_queue.clear()
        self._removed_from_view.clear()
        self._start_time = None

        self._pb.set(0)
        self._pb.configure(progress_color=_ACCENT)
        self._lbl_ok.configure(text="✓  0", text_color=_SUCCESS, fg_color="#0d3533")
        self._lbl_srch.configure(text="◌  0", text_color=_WARN, fg_color="#3d2b0a")
        self._lbl_nf.configure(text="✗  0", text_color=_ERROR, fg_color="#3a1111")
        self._counter_lbl.configure(text="")
        self._status_lbl.configure(text="Запуск…", text_color=_MUTED)
        self._copy_btn.grid_remove()

    def _on_done(self) -> None:
        self._stop_parse_anim()
        self._running = False
        d  = self._counts["downloaded"]
        nf = self._counts["not_found"]

        self._pb.set(1 if self._total else 0)

        # Цвет прогресс-бара отражает итог
        if nf == 0 and d > 0:
            self._pb.configure(progress_color=_SUCCESS)
            status_color = _SUCCESS
        elif nf > 0 and d == 0:
            self._pb.configure(progress_color=_ERROR)
            status_color = _TEXT
        else:
            status_color = _TEXT

        actually_done = self._total > 0 and (d + nf) >= self._total
        prefix = "Готово" if (not self._cancelled or actually_done) else "Остановлено"
        self._status_lbl.configure(
            text=f"{prefix}  •  Скачано: {d}  •  Не найдено: {nf}",
            text_color=status_color,
        )

        # Поиск завершён — ◌ переходит в серый
        self._lbl_srch.configure(text="◌  0", text_color=_MUTED, fg_color=_SURFACE)

        if self._total:
            self._counter_lbl.configure(text=f"{d + nf} / {self._total}")
        self.title("AutoDownload — Готово" if (not self._cancelled or actually_done) else "AutoDownload — Остановлено")

        self._start_btn.configure(
            state="normal", text="▶  Запустить ещё раз",
            fg_color=_ACCENT, hover_color=_ACCENT2,
            border_color="#a78bfa",
            command=self._on_start,
        )
        self._set_inputs_state("normal")
        self._open_btn.grid()

        if nf > 0:
            self._copy_btn.grid()
            self._flash_copy_btn()

        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass
        if not self.focus_displayof():
            self.wm_attributes("-topmost", True)
            self.after(3000, lambda: self.wm_attributes("-topmost", False))

    def _flash_copy_btn(self, n: int = 4) -> None:
        if n <= 0:
            self._copy_btn.configure(fg_color=_SURFACE, text_color=_MUTED)
            return
        on = n % 2 == 1
        self._copy_btn.configure(
            fg_color=_ACCENT if on else _SURFACE,
            text_color=_TEXT if on else _MUTED,
        )
        self.after(350, lambda: self._flash_copy_btn(n - 1))

    # ── Parse animation (indeterminate progress bar) ──────────────────────────

    def _start_parse_anim(self) -> None:
        if self._parsing:
            return
        self._parsing = True
        self._parse_val = 0.0
        self._parse_dir = 1
        self._animate_pb()

    def _stop_parse_anim(self) -> None:
        self._parsing = False
        if self._anim_job:
            self.after_cancel(self._anim_job)
            self._anim_job = None

    def _animate_pb(self) -> None:
        if not self._parsing:
            return
        self._parse_val += self._parse_dir * 0.04
        if self._parse_val >= 1.0:
            self._parse_val = 1.0
            self._parse_dir = -1
        elif self._parse_val <= 0.0:
            self._parse_val = 0.0
            self._parse_dir = 1
        self._pb.set(self._parse_val)
        self._anim_job = self.after(25, self._animate_pb)


# ── Entry point ───────────────────────────────────────────────────────────────

def launch() -> None:
    app = AutoDownloadApp()
    app.mainloop()
