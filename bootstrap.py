"""
bootstrap.py — настройка окружения Playwright перед запуском.

Должен импортироваться ДО playwright.async_api.
В exe-сборке (PyInstaller --onedir) устанавливает PLAYWRIGHT_BROWSERS_PATH
и при первом запуске скачивает Chromium через встроенный playwright-драйвер.
"""

import os
import subprocess
import sys
from pathlib import Path


def _exe_dir() -> Path:
    """Папка, где лежит исполняемый файл (exe или main.py)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _meipass() -> Path | None:
    """sys._MEIPASS в PyInstaller 6.x — подпапка _internal/, иначе None."""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else None


def _playwright_install_cmd(browsers: Path) -> list[str] | None:
    """
    Команда для установки Chromium через playwright-драйвер из сборки.
    Playwright упаковывает node.exe + package/cli.js (не playwright.cmd).
    Возвращает None если драйвер не найден (использовать fallback).
    """
    base = _meipass()
    if base is None:
        return None
    for candidate in [base, _exe_dir()]:
        node = candidate / "playwright" / "driver" / "node.exe"
        cli  = candidate / "playwright" / "driver" / "package" / "cli.js"
        if node.exists() and cli.exists():
            return [str(node), str(cli), "install", "chromium",
                    "--with-deps"]
    return None


def _browsers_dir() -> Path:
    """
    Папка для хранения браузеров.
    В сборке — рядом с exe (browsers/). В исходниках — стандартный путь Playwright.
    """
    if getattr(sys, "frozen", False):
        return _exe_dir() / "browsers"
    # Исходники: не трогаем, Playwright знает куда ставить сам
    return Path.home() / "AppData" / "Local" / "ms-playwright"


def setup_environment() -> None:
    """
    Выставляет PLAYWRIGHT_BROWSERS_PATH и при первом запуске из сборки
    скачивает Chromium. Вызывать до любого импорта playwright.async_api.
    """
    browsers = _browsers_dir()

    # Явно выставляем путь — перебиваем дефолт Playwright ("0" в frozen-режиме)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)

    if getattr(sys, "frozen", False):
        _ensure_chromium(browsers)


def _ensure_chromium(browsers: Path) -> None:
    """Скачивает Chromium если папка chromium-* не найдена."""
    if any(browsers.glob("chromium-*")):
        return

    browsers.mkdir(parents=True, exist_ok=True)

    print()
    print("=" * 58)
    print("  Первый запуск: установка браузера Chromium (~150 MB)")
    print("  Это займёт несколько минут. Последующие — мгновенны.")
    print("=" * 58)
    print()

    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)

    cmd = _playwright_install_cmd(browsers)
    if cmd is None:
        # Fallback: playwright module из sys.executable (не должен происходить в сборке)
        cmd = [sys.executable, "-m", "playwright", "install", "chromium"]

    result = subprocess.run(cmd, env=env)

    if result.returncode != 0:
        print()
        print("ОШИБКА: не удалось установить Chromium.")
        print("Проверьте подключение к интернету и запустите снова.")
        sys.exit(1)

    print()
    print("Браузер установлен. Запускаем AutoDownload...")
    print()
