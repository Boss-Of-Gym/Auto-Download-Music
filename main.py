"""
main.py — точка входа приложения.

Единственная ответственность: прочитать конфигурацию, запустить основной
async-цикл и вывести итоговый отчёт.
"""

import sys

# Windows: переключаем консоль на UTF-8 чтобы корректно выводить кириллицу
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# ── Настройка Playwright-окружения (до импорта playwright.async_api) ──────────
# В exe-сборке выставляет PLAYWRIGHT_BROWSERS_PATH и скачивает Chromium при
# первом запуске. В режиме исходников — ничего не меняет.
from bootstrap import setup_environment
setup_environment()
# ──────────────────────────────────────────────────────────────────────────────

import asyncio
import logging

from playwright.async_api import async_playwright

from cli import collect_settings
from config import AppConfig
from downloader.processor import process_track
from track_store import load_all, load_pending, reset_not_found
from yandex.collector import collect_from_yandex

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


async def main(config: AppConfig, on_progress=None, code_callback=None) -> None:
    """
    on_progress(index, track, status) вызывается при изменении статуса трека.
    status: "pending" | "searching" | "downloaded" | "not_found"
    Специальный случай: index == -1 — обновление общего статуса (track = текст).
    """
    config.download_dir.mkdir(parents=True, exist_ok=True)

    stats     = {"downloaded": 0, "not_found": 0}
    file_lock = asyncio.Lock()

    # ── Источник списка треков ────────────────────────────────────
    if config.source_mode == "json":
        track_file = config.track_file_path
        if not track_file.exists():
            log.error("Файл треков не найден: %s", track_file)
            if on_progress:
                on_progress(-1, f"Файл не найден: {track_file}", "error")
            return
        log.info("Файл треков: %s", track_file.name)
    else:
        track_file = await collect_from_yandex(config, code_callback=code_callback, on_progress=on_progress)
        if track_file is None:
            if on_progress:
                on_progress(-1, "Не удалось получить треки из Яндекс.Музыки", "error")
            return
    # ─────────────────────────────────────────────────────────────

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=config.headless, slow_mo=0)
        try:
            context = await browser.new_context(
                accept_downloads=True,
                locale="ru-RU",
                viewport={"width": 1280, "height": 800},
            )
            context.set_default_timeout(30_000)

            pending = load_pending(track_file)
            if config.track_limit is not None:
                pending = pending[:config.track_limit]

            log.info("=" * 55)
            log.info(
                "Треков к скачиванию: %d%s",
                len(pending),
                f" (лимит: {config.track_limit})" if config.track_limit is not None else " (все pending)",
            )
            log.info("Параллельных потоков: %d  (сайты перебираются последовательно)", config.max_concurrent)
            log.info("=" * 55)

            if not pending:
                log.info("Все треки уже обработаны.")
                if on_progress:
                    on_progress(-1, "Все треки уже скачаны", "done")
                return

            # Показываем все треки как "pending" сразу
            if on_progress:
                for entry in pending:
                    on_progress(entry["index"], entry["track"], "pending")

            semaphore = asyncio.Semaphore(config.max_concurrent)
            tasks = [
                asyncio.create_task(
                    process_track(
                        context, entry, semaphore, stats,
                        track_file, file_lock, config.download_dir,
                        on_progress=on_progress,
                    )
                )
                for entry in pending
            ]
            try:
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
        finally:
            await browser.close()

    all_data   = load_all(track_file)
    total      = len(all_data)
    downloaded = sum(1 for e in all_data if e["status"] == "downloaded")
    not_found  = sum(1 for e in all_data if e["status"] == "not_found")

    log.info("=" * 55)
    log.info("Готово!")
    log.info("Скачано:    %d / %d", downloaded, total)
    log.info("Не найдено: %d / %d", not_found, total)
    log.info("Осталось:   %d / %d", total - downloaded - not_found, total)

    reset_count = reset_not_found(track_file)
    if reset_count:
        log.info("Сброшено в pending: %d (для следующего прогона)", reset_count)


if __name__ == "__main__":
    import sys as _sys
    if "--cli" in _sys.argv:
        cfg = collect_settings()
        asyncio.run(main(cfg))
    else:
        from gui import launch
        launch()
