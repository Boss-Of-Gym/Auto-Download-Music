"""
config.py — AppConfig dataclass и технические константы.

AppConfig несёт все пользовательские настройки и передаётся явным параметром
через весь call-chain. Технические константы (HEADLESS, MAX_CONCURRENT и т.д.)
задаются разработчиком и не меняются между запусками.
"""

from dataclasses import dataclass, field
from pathlib import Path


# ── Технические константы ────────────────────────────────────────
HEADLESS             = False            # False — браузер виден; True — скрытый режим
MAX_CONCURRENT       = 3               # треков обрабатывается параллельно
DEFAULT_DOWNLOAD_DIR = Path.home() / "Music"
MIN_FILE_SIZE        = 512 * 1024      # 512 KB — минимальный размер валидного MP3


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

    def __post_init__(self) -> None:
        if not (1 <= self.max_concurrent <= 10):
            raise ValueError(f"max_concurrent должен быть от 1 до 10, получено: {self.max_concurrent}")
        if self.track_limit is not None and self.track_limit < 1:
            raise ValueError("track_limit должен быть ≥ 1 или None")
