"""
utils.py — общие утилиты, не зависящие от домена приложения.
"""

import sys
from pathlib import Path


def safe_filename(name: str) -> str:
    """Заменяет символы, запрещённые в именах файлов Windows, на подчёркивание."""
    return "".join("_" if c in r'\/:*?"<>|' else c for c in name)


def app_dir() -> Path:
    """
    Рабочая папка приложения.
    В exe-сборке — папка рядом с AutoDownload.exe.
    В режиме исходников — папка с main.py.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent
