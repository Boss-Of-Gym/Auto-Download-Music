"""
config.py — AppConfig dataclass и технические константы.

AppConfig несёт все пользовательские настройки и передаётся явным параметром
через весь call-chain. Технические константы (HEADLESS, MAX_CONCURRENT и т.д.)
задаются разработчиком и не меняются между запусками.
"""

from dataclasses import dataclass, field
from pathlib import Path


# ── Технические константы ────────────────────────────────────────
HEADLESS           = False          # False — браузер виден; True — скрытый режим
MAX_CONCURRENT     = 3              # треков обрабатывается параллельно
DEFAULT_DOWNLOAD_DIR = Path(r"C:\Users\user\Music")


# ── Пользовательская конфигурация ────────────────────────────────
@dataclass
class AppConfig:
    """
    Все параметры, введённые пользователем перед запуском.
    Создаётся один раз в cli.collect_settings() и передаётся через весь стек.
    """
    source_mode:         str         # "json" | "yandex"
    download_dir:        Path
    track_limit:         int | None  # None = скачать всё
    max_concurrent:      int = field(default=MAX_CONCURRENT)
    headless:            bool = field(default=False)

    # JSON-режим
    track_file_path:     Path | None = field(default=None)

    # Яндекс.Музыка-режим
    name_playlist:       str = field(default="")
    yandex_phone:        str = field(default="")
    yandex_login:        str = field(default="")
    yandex_account_name: str = field(default="")
