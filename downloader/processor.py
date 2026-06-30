"""
downloader/processor.py — оркестрация скачивания одного трека.

Единственная ответственность: перебрать сайты по порядку, найти совпадение,
скачать и обновить статус. Не знает ни о браузере в целом, ни о плейлисте.
"""

import asyncio
import logging
from pathlib import Path

from playwright.async_api import BrowserContext

from downloader.browser import download_from_page, navigate_to_track_if_match
from downloader.sites import SITES
from track_store import update_status

log = logging.getLogger(__name__)


async def process_track(
    context:      BrowserContext,
    entry:        dict,              # {"index": int, "track": str, "status": str}
    semaphore:    asyncio.Semaphore,
    stats:        dict[str, int],
    track_file:   Path,
    file_lock:    asyncio.Lock,
    download_dir: Path,
    on_progress=None,  # callable(index: int, track: str, status: str) | None
) -> None:
    """
    Полный цикл обработки одного трека через все сайты-источники.
    Перебирает SITES последовательно: нашёл совпадение → скачал → стоп.
    """
    track = entry["track"]
    idx   = entry["index"]

    async with semaphore:
        log.info("▶ [%d] %s", idx, track)
        if on_progress:
            on_progress(idx, track, "searching")

        downloaded = False

        for site in SITES:
            page = await context.new_page()
            try:
                found = await navigate_to_track_if_match(page, track, site)
                if not found:
                    continue

                log.info("  Совпадение на: %s → скачиваем", site["name"])
                success = await download_from_page(page, track, site, download_dir)
                if success:
                    downloaded = True
                    stats["downloaded"] += 1
                    await update_status(track_file, idx, "downloaded", file_lock)
                    break
            except Exception as exc:
                log.warning("  [%s] Неожиданная ошибка: %s", site["name"], exc)
            finally:
                await page.close()

        if not downloaded:
            log.warning("  ✗ Не найдено ни на одном сайте: %s", track)
            stats["not_found"] += 1
            await update_status(track_file, idx, "not_found", file_lock)

        if on_progress:
            on_progress(idx, track, "downloaded" if downloaded else "not_found")
