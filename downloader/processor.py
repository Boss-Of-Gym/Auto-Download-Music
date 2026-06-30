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

_MAX_ATTEMPTS = 2       # попыток на один сайт при сетевых ошибках
_RETRY_DELAY  = 2.0     # секунды между попытками


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
    При сетевой ошибке делает до _MAX_ATTEMPTS попыток перед переходом к следующему сайту.
    """
    track = entry["track"]
    idx   = entry["index"]

    async with semaphore:
        log.info("▶ [%d] %s", idx, track)
        if on_progress:
            on_progress(idx, track, "searching")

        downloaded = False

        for site in SITES:
            success = False

            for attempt in range(_MAX_ATTEMPTS):
                page = await context.new_page()
                try:
                    found = await navigate_to_track_if_match(page, track, site)
                    if not found:
                        break  # нет совпадения на этом сайте — retry не нужен

                    log.info("  Совпадение на: %s → скачиваем", site["name"])
                    success = await download_from_page(page, track, site, download_dir)
                    break  # результат получен (успех или неудача скачивания)

                except Exception as exc:
                    log.warning(
                        "  [%s] Попытка %d/%d, ошибка: %s",
                        site["name"], attempt + 1, _MAX_ATTEMPTS, exc,
                    )
                    if attempt < _MAX_ATTEMPTS - 1:
                        await asyncio.sleep(_RETRY_DELAY)
                    # продолжаем к следующей попытке

                finally:
                    await page.close()

            if success:
                downloaded = True
                stats["downloaded"] += 1
                await update_status(track_file, idx, "downloaded", file_lock)
                break  # трек найден — остальные сайты не нужны

        if not downloaded:
            log.warning("  ✗ Не найдено ни на одном сайте: %s", track)
            stats["not_found"] += 1
            await update_status(track_file, idx, "not_found", file_lock)

        if on_progress:
            on_progress(idx, track, "downloaded" if downloaded else "not_found")
