"""
cli.py — сбор пользовательских данных через терминал.

Единственная ответственность: задать вопросы пользователю и вернуть AppConfig.
Не содержит бизнес-логики и не обращается к браузеру.
"""

from pathlib import Path

from config import AppConfig, DEFAULT_DOWNLOAD_DIR, MAX_CONCURRENT
from utils import app_dir, safe_filename


def _ask(prompt: str, default: str = "", required: bool = True) -> str:
    hint = f" [{default}]" if default else ""
    while True:
        value = input(f"  {prompt}{hint}: ").strip()
        if value:
            return value
        if not required:
            return default
        print("    Поле обязательно — попробуйте ещё раз.")


def _ask_source_mode() -> str:
    while True:
        raw = input("  Источник треков (1 — JSON-файл, 2 — Яндекс.Музыка) [1]: ").strip()
        if not raw or raw == "1":
            return "json"
        if raw == "2":
            return "yandex"
        print("    Введите 1 или 2.")


def _ask_max_concurrent() -> int:
    while True:
        raw = input(f"  Параллельных потоков (1–10) [{MAX_CONCURRENT}]: ").strip()
        if not raw:
            return MAX_CONCURRENT
        if raw.isdigit() and 1 <= int(raw) <= 10:
            return int(raw)
        print("    Введите число от 1 до 10.")


def _ask_track_limit() -> int | None:
    while True:
        raw = input("  Сколько треков скачать? (all — все или введите число) [all]: ").strip()
        if not raw or raw.lower() == "all":
            return None
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("    Введите 'all' или целое положительное число.")


def collect_settings() -> AppConfig:
    """Запрашивает все настройки из терминала и возвращает AppConfig."""
    print()
    print("═" * 52)
    print("  AutoDownload — ввод данных")
    print("═" * 52)

    source_mode = _ask_source_mode()

    track_file_path     = None
    name_playlist       = ""
    yandex_phone        = ""
    yandex_login        = ""
    yandex_account_name = ""

    if source_mode == "json":
        raw = _ask("Путь к JSON-файлу или имя плейлиста")
        p = Path(raw)
        if p.suffix.lower() != ".json":
            p = app_dir() / (safe_filename(raw) + "_tracks.json")
        track_file_path = p
    else:
        yandex_phone        = _ask("Номер телефона")
        yandex_login        = _ask("Логин аккаунта (ник для URL)")
        yandex_account_name = _ask("Имя аккаунта в шапке сайта", required=False)
        name_playlist       = _ask("Название плейлиста")

    dl_raw = _ask("Папка загрузок", default=str(DEFAULT_DOWNLOAD_DIR), required=False)
    download_dir = Path(dl_raw) if dl_raw else DEFAULT_DOWNLOAD_DIR

    max_concurrent = _ask_max_concurrent()
    track_limit    = _ask_track_limit()

    raw_headless = input("  Скрытый браузер без окна? (y/N) [N]: ").strip().lower()
    headless = raw_headless in ("y", "yes", "1")

    print("═" * 52)
    print()

    return AppConfig(
        source_mode=source_mode,
        download_dir=download_dir,
        track_limit=track_limit,
        max_concurrent=max_concurrent,
        headless=headless,
        track_file_path=track_file_path,
        name_playlist=name_playlist,
        yandex_phone=yandex_phone,
        yandex_login=yandex_login,
        yandex_account_name=yandex_account_name,
    )
