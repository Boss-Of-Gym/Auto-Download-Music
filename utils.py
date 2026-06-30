"""
utils.py — общие утилиты, не зависящие от домена приложения.
"""

import sys
from pathlib import Path


def safe_filename(name: str, max_len: int = 200) -> str:
    """Заменяет символы, запрещённые в именах файлов Windows, на подчёркивание. Обрезает до max_len."""
    cleaned = "".join("_" if c in r'\/:*?"<>|' else c for c in name)
    return cleaned[:max_len]


def app_dir() -> Path:
    """
    Рабочая папка приложения.
    В exe-сборке — папка рядом с AutoDownload.exe.
    В режиме исходников — папка с main.py.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent
