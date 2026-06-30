"""
gui.py — десктопный интерфейс AutoDownload.

Единственная ответственность: отобразить настройки, запустить загрузку
в фоновом потоке и показать прогресс в реальном времени.
Взаимодействие с main() — через queue.SimpleQueue, без разделяемого состояния.
"""

import asyncio
import queue
import threading
import tkinter as tk
from pathlib import Path
from threading import Event
from tkinter import filedialog

import customtkinter as ctk

from config import AppConfig, DEFAULT_DOWNLOAD_DIR, MAX_CONCURRENT
from utils import app_dir, safe_filename

# ── Palette ───────────────────────────────────────────────────────────────────
_BG      = "#0d0d0d"
_PANEL   = "#141414"
_SURFACE = "#1c1c1c"
_BORDER  = "#2a2a2a"
_ACCENT  = "#7c3aed"
_ACCENT2 = "#5b21b6"
_TEXT    = "#efefef"
_MUTED   = "#525262"
_SUCCESS = "#34d399"
_ERROR   = "#f87171"
_WARN    = "#fbbf24"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ── Track row widget ──────────────────────────────────────────────────────────

class _TrackRow(ctk.CTkFrame):
    """Одна строка трека в списке прогресса."""

    _SPIN = ["◐", "◓", "◑", "◒"]

    def __init__(self, master, track: str, **kwargs):
        super().__init__(master, fg_color=_SURFACE, corner_radius=8, **kwargs)
        self.grid_columnconfigure(1, weight=1)

        self._spin_idx = 0
        self._spin_job = None

        self._icon = ctk.CTkLabel(
            self, text="·", width=24,
            font=ctk.CTkFont(size=14), text_color=_MUTED,
        )
        self._icon.grid(row=0, column=0, padx=(12, 0), pady=10)

        self._name = ctk.CTkLabel(
            self, text=track, anchor="w",
            font=ctk.CTkFont(size=12), text_color=_MUTED,
            wraplength=380,
        )
        self._name.grid(row=0, column=1, padx=(8, 14), pady=10, sticky="ew")

    def set_status(self, status: str) -> None:
        if self._spin_job:
            self.after_cancel(self._spin_job)
            self._spin_job = None

        if status == "searching":
            self._name.configure(text_color=_TEXT)
            self._spin()
        elif status == "downloaded":
            self._icon.configure(text="✓", text_color=_SUCCESS)
            self._name.configure(text_color=_TEXT)
        elif status == "not_found":
            self._icon.configure(text="✗", text_color=_ERROR)
            self._name.configure(text_color=_MUTED)

    def _spin(self) -> None:
        self._icon.configure(text=self._SPIN[self._spin_idx], text_color=_WARN)
        self._spin_idx = (self._spin_idx + 1) % len(self._SPIN)
        self._spin_job = self.after(160, self._spin)


# ── Main window ───────────────────────────────────────────────────────────────

class AutoDownloadApp(ctk.CTk):

    def __init__(self) -> None:
        super().__init__()
        self.title("AutoDownload")
        self.geometry("960x640")
        self.minsize(820, 520)
        self.configure(fg_color=_BG)

        self._q: queue.SimpleQueue = queue.SimpleQueue()
        self._rows: dict[int, _TrackRow] = {}
        self._running = False
        self._thread: threading.Thread | None = None
        self._threads_val = MAX_CONCURRENT
        self._counts = {"downloaded": 0, "not_found": 0, "searching": 0}
        self._total = 0
        self._otp_event: Event = Event()
        self._otp_code: str = ""

        # Parsing progress animation state
        self._parsing = False
        self._anim_job: str | None = None
        self._parse_val = 0.0
        self._parse_dir = 1

        # Yandex inline error labels (populated in _build_left)
        self._yx_err: dict[str, ctk.CTkLabel] = {}

        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=300)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left  = ctk.CTkFrame(self, fg_color=_PANEL, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew")
        self._build_left(left)

        right = ctk.CTkFrame(self, fg_color=_BG, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        self._build_right(right)

    def _build_left(self, p: ctk.CTkFrame) -> None:
        p.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(0, weight=1)

        # Scrollable settings — prevents start button from being pushed off screen
        settings = ctk.CTkScrollableFrame(
            p, fg_color="transparent",
            scrollbar_button_color=_BORDER,
            scrollbar_button_hover_color=_ACCENT,
        )
        settings.grid(row=0, column=0, sticky="nsew")
        settings.grid_columnconfigure(0, weight=1)

        r = 0

        # Header
        ctk.CTkLabel(settings, text="AutoDownload",
                     font=ctk.CTkFont(size=19, weight="bold"), text_color=_TEXT,
                     ).grid(row=r, column=0, padx=24, pady=(28, 2), sticky="w"); r += 1
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
        self._src.grid(row=r, column=0, padx=24, pady=(5, 16), sticky="ew"); r += 1

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
            ("phone",    "Телефон *",    "+7 999 000-00-00"),
            ("login",    "Логин *",      "ник из music.yandex.ru/users/НИК"),
            ("account",  "Имя в шапке *", "Иван Иванов"),
            ("playlist", "Плейлист *",  "Мне нравится"),
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

            # Inline error label (empty = invisible, red on validation fail)
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
        ctk.CTkCheckBox(
            settings, text="Скрытый браузер (без окна)",
            variable=self._headless_var,
            font=ctk.CTkFont(size=12), text_color=_TEXT,
            fg_color=_ACCENT, hover_color=_ACCENT2,
            border_color=_BORDER, checkmark_color=_TEXT,
        ).grid(row=r, column=0, padx=24, pady=(14, 0), sticky="w"); r += 1

        # Track limit
        self._lbl(settings, r, "МАКСИМУМ ТРЕКОВ"); r += 1
        self._limit = ctk.CTkEntry(settings, placeholder_text="Все",
                                   fg_color=_SURFACE, border_color=_BORDER,
                                   text_color=_TEXT, height=34)
        self._limit.grid(row=r, column=0, padx=24, pady=(5, 20), sticky="ew")

        # Fixed bottom: always visible regardless of settings height
        bot = ctk.CTkFrame(p, fg_color=_PANEL, corner_radius=0)
        bot.grid(row=1, column=0, sticky="ew")
        bot.grid_columnconfigure(0, weight=1)

        ctk.CTkFrame(bot, height=1, fg_color=_BORDER
                     ).grid(row=0, column=0, padx=20, sticky="ew")

        self._start_btn = ctk.CTkButton(
            bot, text="Запустить",
            fg_color=_ACCENT, hover_color=_ACCENT2, text_color=_TEXT,
            height=44, font=ctk.CTkFont(size=14, weight="bold"), corner_radius=10,
            command=self._on_start,
        )
        self._start_btn.grid(row=1, column=0, padx=24, pady=20, sticky="ew")

    def _build_right(self, p: ctk.CTkFrame) -> None:
        p.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(1, weight=1)

        # Header
        hdr = ctk.CTkFrame(p, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=24, pady=(24, 0), sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(hdr, text="Прогресс",
                     font=ctk.CTkFont(size=15, weight="bold"), text_color=_TEXT,
                     ).grid(row=0, column=0, sticky="w")
        self._status_lbl = ctk.CTkLabel(hdr, text="Ожидание запуска",
                                        font=ctk.CTkFont(size=11), text_color=_MUTED)
        self._status_lbl.grid(row=1, column=0, sticky="w")

        # Scroll area
        self._scroll = ctk.CTkScrollableFrame(
            p, fg_color=_PANEL, corner_radius=12,
            scrollbar_button_color=_SURFACE,
            scrollbar_button_hover_color=_ACCENT,
        )
        self._scroll.grid(row=1, column=0, padx=24, pady=16, sticky="nsew")
        self._scroll.grid_columnconfigure(0, weight=1)

        self._empty_lbl = ctk.CTkLabel(
            self._scroll,
            text="Треки появятся здесь после запуска",
            font=ctk.CTkFont(size=12), text_color=_MUTED,
        )
        self._empty_lbl.grid(row=0, column=0, pady=48)

        # Stats bar
        bar = ctk.CTkFrame(p, fg_color=_PANEL, corner_radius=12)
        bar.grid(row=2, column=0, padx=24, pady=(0, 20), sticky="ew")
        bar.grid_columnconfigure(1, weight=1)

        self._pb = ctk.CTkProgressBar(bar, height=5,
                                      progress_color=_ACCENT, fg_color=_SURFACE)
        self._pb.set(0)
        self._pb.grid(row=0, column=0, columnspan=3, padx=16, pady=(12, 6), sticky="ew")

        self._lbl_ok  = ctk.CTkLabel(bar, text="✓  0", font=ctk.CTkFont(size=12),
                                     text_color=_SUCCESS)
        self._lbl_ok.grid(row=1, column=0, padx=(20, 0), pady=(0, 10))

        self._lbl_srch = ctk.CTkLabel(bar, text="◌  0", font=ctk.CTkFont(size=12),
                                      text_color=_WARN)
        self._lbl_srch.grid(row=1, column=1, pady=(0, 10))

        self._lbl_nf  = ctk.CTkLabel(bar, text="✗  0", font=ctk.CTkFont(size=12),
                                     text_color=_ERROR)
        self._lbl_nf.grid(row=1, column=2, padx=(0, 20), pady=(0, 10))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _lbl(self, parent, row: int, text: str) -> None:
        ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=_MUTED,
                     ).grid(row=row, column=0, padx=24, pady=(14, 0), sticky="w")

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

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_src(self, value: str) -> None:
        if value == "JSON файл":
            self._yx_f.grid_remove()
            self._json_f.grid()
        else:
            self._json_f.grid_remove()
            self._yx_f.grid()

    def _on_threads(self, val: float) -> None:
        self._threads_val = int(val)
        self._thr_lbl.configure(text=str(self._threads_val))

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

    # ── Yandex field validation ───────────────────────────────────────────────

    def _validate_yandex(self) -> bool:
        """Проверяет обязательные поля. Показывает inline-ошибки. Возвращает True если всё заполнено."""
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

    # ── Start / config ────────────────────────────────────────────────────────

    def _on_start(self) -> None:
        if self._running:
            return

        try:
            config = self._build_config()
        except ValueError as exc:
            if str(exc):  # пустое сообщение = inline-ошибки уже показаны
                self._status_lbl.configure(text=str(exc), text_color=_ERROR)
            return

        self._reset_progress()
        self._running = True
        self._start_btn.configure(state="disabled", text="Выполняется…")
        self._counts = {"downloaded": 0, "not_found": 0, "searching": 0}
        self._total = 0
        self._rows.clear()

        while not self._q.empty():
            try:
                self._q.get_nowait()
            except Exception:
                break

        self._thread = threading.Thread(
            target=self._run, args=(config,), daemon=True,
        )
        self._thread.start()
        self.after(100, self._poll)

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
            raise ValueError("")  # ошибки уже показаны inline

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
            self._otp_event.wait()
            return self._otp_code

        asyncio.run(_async_main(config, on_progress=_cb, code_callback=_code_cb))

    # ── Progress polling (tkinter main thread) ────────────────────────────────

    def _poll(self) -> None:
        try:
            while True:
                item = self._q.get_nowait()
                self._handle(*item)
        except queue.Empty:
            pass

        if self._thread and self._thread.is_alive():
            self.after(100, self._poll)
        else:
            self._on_done()

    def _handle(self, index: int, track: str, status: str) -> None:
        if index == -2:
            self._show_otp_dialog()
            return

        if index == -1:
            if status == "parsing":
                # Яндекс.Музыка: идёт парсинг плейлиста
                self._status_lbl.configure(text=track, text_color=_WARN)
                self._start_parse_anim()
                if self._empty_lbl and self._empty_lbl.winfo_exists():
                    self._empty_lbl.configure(text=track)
            elif status == "error":
                self._stop_parse_anim()
                self._pb.set(0)
                self._status_lbl.configure(text=track, text_color=_ERROR)
            else:
                self._stop_parse_anim()
                self._status_lbl.configure(text=track, text_color=_MUTED)
            return

        # Первый реальный трек — останавливаем анимацию парсинга
        if self._parsing:
            self._stop_parse_anim()
            self._pb.set(0)

        if index not in self._rows:
            if self._empty_lbl and self._empty_lbl.winfo_exists():
                self._empty_lbl.destroy()

            row_num = len(self._rows)
            row = _TrackRow(self._scroll, track)
            row.grid(row=row_num, column=0, sticky="ew", padx=6, pady=3)
            self._rows[index] = row
            self._total += 1

        self._rows[index].set_status(status)

        if status == "searching":
            self._counts["searching"] += 1
        elif status == "downloaded":
            self._counts["downloaded"] += 1
            self._counts["searching"] = max(0, self._counts["searching"] - 1)
        elif status == "not_found":
            self._counts["not_found"] += 1
            self._counts["searching"] = max(0, self._counts["searching"] - 1)

        self._refresh_stats()

    def _show_otp_dialog(self) -> None:
        """Модальный диалог ввода OTP. Разблокирует фоновый поток через otp_event."""
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

        self._status_lbl.configure(
            text=f"Обработано {done} из {self._total}",
            text_color=_MUTED,
        )

    def _reset_progress(self) -> None:
        self._stop_parse_anim()
        for w in self._scroll.winfo_children():
            w.destroy()
        self._empty_lbl = ctk.CTkLabel(
            self._scroll, text="Загрузка...",
            font=ctk.CTkFont(size=12), text_color=_MUTED,
        )
        self._empty_lbl.grid(row=0, column=0, pady=48)

        self._pb.set(0)
        self._lbl_ok.configure(text="✓  0")
        self._lbl_srch.configure(text="◌  0")
        self._lbl_nf.configure(text="✗  0")
        self._status_lbl.configure(text="Запуск…", text_color=_MUTED)

    def _on_done(self) -> None:
        self._stop_parse_anim()
        self._running = False
        d  = self._counts["downloaded"]
        nf = self._counts["not_found"]
        self._pb.set(1 if self._total else 0)
        self._status_lbl.configure(
            text=f"Готово  •  Скачано: {d}  •  Не найдено: {nf}",
            text_color=_SUCCESS if nf == 0 else _TEXT,
        )
        self._start_btn.configure(state="normal", text="Запустить ещё раз")

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
