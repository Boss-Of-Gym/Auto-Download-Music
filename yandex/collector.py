"""
yandex/collector.py — сбор треков из плейлиста Яндекс.Музыки.

Единственная ответственность: прокрутить виртуальный список плейлиста,
собрать все треки и вернуть их. Авторизация — в auth.py, сохранение — в track_store.py.
"""

import asyncio
import logging
import re
from pathlib import Path

from playwright.async_api import Page, async_playwright
from playwright.async_api import TimeoutError as PwTimeout

from config import AppConfig
from track_store import save_track_list
from yandex.auth import login
from yandex.locators import YandexMusic

log = logging.getLogger(__name__)


async def _parse_playlist_count(page: Page) -> int:
    """Читает количество треков из шапки плейлиста (span[title*='трек'])."""
    try:
        text = await YandexMusic.playlist_track_count(page).first.get_attribute(
            "title", timeout=5_000
        )
        if text:
            found = re.search(r"\d+", text)
            return int(found.group()) if found else 0
    except Exception:
        pass
    log.warning("Не удалось прочитать количество треков из шапки плейлиста")
    return 0


async def collect_favorites(page: Page, config: AppConfig, on_progress=None) -> list[str]:
    """
    Открыть плейлист, прокрутить виртуальный список до конца и собрать
    все треки в список вида ['Исполнитель — Название', ...].

    Алгоритм:
      1. Перейти в «Коллекцию» и выбрать нужный плейлист.
      2. Прочитать общее число треков из шапки.
      3. В цикле: читать видимые div[data-index] → записывать по индексу
         → скроллить вниз → повторять пока не наберём total.
    """
    await YandexMusic.go_to_favorite(page).click(timeout=8_000)
    await page.wait_for_load_state("domcontentloaded")

    await YandexMusic.choise_our_playlist(page, name_playlist=config.name_playlist).click()
    await page.wait_for_load_state("domcontentloaded")

    total = await _parse_playlist_count(page)
    log.info("Плейлист '%s' содержит %d треков", config.name_playlist, total)
    if on_progress and total:
        on_progress(-1, f"Плейлист «{config.name_playlist}»: {total} треков", "parsing")

    try:
        await YandexMusic.track_items(page).first.wait_for(timeout=20_000)
    except PwTimeout:
        log.error("Треки не загрузились. Проверьте логин и авторизацию.")
        return []

    collected: dict[int, str] = {}  # data-index → "Исполнитель — Название"
    prev_count   = -1
    no_progress  = 0
    MAX_NO_PROGRESS = 10

    while True:
        items_loc = YandexMusic.track_items(page)
        n = await items_loc.count()

        for i in range(n):
            item = items_loc.nth(i)
            try:
                raw_idx = await item.get_attribute("data-index", timeout=300)
            except Exception:
                continue
            if raw_idx is None:
                continue
            idx = int(raw_idx)
            if idx in collected:
                continue

            try:
                title = (await YandexMusic.track_title(item).inner_text(timeout=800)).strip()
            except Exception:
                continue
            if not title:
                continue

            try:
                artist = (await YandexMusic.track_artists(item).inner_text(timeout=800)).strip()
            except Exception:
                artist = ""

            collected[idx] = f"{artist} — {title}" if artist else title

        cur_count = len(collected)

        if total and cur_count >= total:
            break

        if cur_count == prev_count:
            no_progress += 1
            if no_progress >= MAX_NO_PROGRESS:
                log.warning(
                    "Прокрутка не даёт новых треков, останавливаемся (%d/%d).",
                    cur_count, total,
                )
                break
        else:
            no_progress = 0
            log.info("Собрано %d / %d треков...", cur_count, total or "?")
            if on_progress:
                on_progress(-1, f"Собрано {cur_count} / {total or '?'} треков...", "parsing")

        prev_count = cur_count
        # Курсор должен быть над списком — иначе wheel уйдёт в (0,0) и не прокрутит Virtuoso
        await page.mouse.move(640, 400)
        await page.mouse.wheel(0, 1500)
        await asyncio.sleep(0.7)

    tracks = [collected[i] for i in sorted(collected.keys())]
    log.info("Итого собрано: %d треков", len(tracks))
    return tracks


async def collect_from_yandex(config: AppConfig, code_callback=None, on_progress=None) -> Path | None:
    """
    Открывает браузер, авторизуется, собирает плейлист, сохраняет JSON.
    code_callback() — блокирующая функция, возвращающая введённый OTP-код.
    on_progress(index, text, status) — callback прогресса (index=-1 для статуса).
    Возвращает путь к созданному файлу или None при ошибке.
    """
    if on_progress:
        on_progress(-1, "Подключение к Яндекс.Музыке...", "parsing")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=config.headless, slow_mo=30)
        context = await browser.new_context(
            locale="ru-RU",
            viewport={"width": 1280, "height": 800},
        )
        context.set_default_timeout(30_000)
        page = await context.new_page()
        try:
            await login(page, config, code_callback=code_callback)
            if on_progress:
                on_progress(-1, "Сбор треков из плейлиста...", "parsing")
            tracks = await collect_favorites(page, config, on_progress=on_progress)
        finally:
            await browser.close()

    if not tracks:
        log.error("Не удалось собрать треки с Яндекс.Музыки.")
        return None

    path = save_track_list(tracks, config.name_playlist)
    log.info("Список треков сохранён: %s (%d треков)", path.name, len(tracks))
    return path
