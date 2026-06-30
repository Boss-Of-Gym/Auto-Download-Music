"""
downloader/browser.py — поиск трека на сайте и скачивание.

Единственная ответственность: два шага жизненного цикла одного трека на одном сайте:
  1. navigate_to_track_if_match — поиск и переход (или проверка совпадения без перехода).
  2. download_from_page          — клик на кнопку скачивания и сохранение файла.
"""

import asyncio
import logging
import re
from pathlib import Path
from urllib.parse import quote_plus

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PwTimeout

from downloader.matcher import titles_match
from utils import safe_filename

log = logging.getLogger(__name__)


async def navigate_to_track_if_match(page: Page, query: str, site: dict) -> bool:
    """
    Поиск трека на сайте. Если первый результат совпадает по названию —
    переходим на его страницу (если no_navigate не задан) и возвращаем True.
    При любой ошибке или отсутствии совпадения возвращает False.

    Опциональные ключи в site:
      title_fn     — async fn(element) → str: кастомная логика названия
      title_attr   — str: читать через get_attribute() вместо inner_text()
      click        — fn(first_el) → Locator: элемент для клика
      no_navigate  — bool: остаться на странице поиска (кнопка скачивания в выдаче)
      no_results_text — str: текст, сигнализирующий об отсутствии результатов
    """
    name = site["name"]
    # em/en-dash → пробел чтобы не ломать поисковые запросы
    search_query = re.sub(r"\s*[—–]\s*", " ", query).strip()
    _encode      = site.get("encode_fn", quote_plus)
    search_url   = site["search_url"].format(q=_encode(search_query))

    log.debug("  [%s] GET %s", name, search_url)
    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
    except PwTimeout:
        log.debug("  [%s] Таймаут навигации", name)
        return False
    log.debug("  [%s] URL после редиректа: %s", name, page.url)

    if "no_results_text" in site:
        if await page.get_by_text(site["no_results_text"], exact=False).count() > 0:
            log.debug("  [%s] Страница содержит '%s' — нет результатов", name, site["no_results_text"])
            return False

    result_locator = site["result"](page)
    try:
        await result_locator.first.wait_for(timeout=10_000)
    except PwTimeout:
        log.debug("  [%s] Результатов нет", name)
        return False

    first = result_locator.first
    try:
        if "title_fn" in site:
            found_title = await site["title_fn"](first)
        elif "title_attr" in site:
            found_title = await site["title"](first).get_attribute(site["title_attr"], timeout=3_000) or ""
        else:
            found_title = await site["title"](first).inner_text(timeout=3_000)
    except Exception as exc:
        log.debug("  [%s] Не удалось прочитать заголовок: %s", name, exc)
        return False

    if not titles_match(found_title, query):
        log.debug("  [%s] Нет совпадения: %r ≠ %r", name, found_title.strip(), query)
        return False

    log.debug("  [%s] Совпадение: %r", name, found_title.strip())

    if not site.get("no_navigate"):
        click_el = site["click"](first) if "click" in site else first
        await click_el.click()
        await page.wait_for_load_state("domcontentloaded")
    return True


async def download_from_page(page: Page, query: str, site: dict, download_dir: Path) -> bool:
    """
    Скачать трек со страницы (вызывается после navigate_to_track_if_match → True).
    Блокирует до полной записи файла на диск.
    Возвращает False если файл не создан или имеет нулевой размер.

    Опциональный ключ в site:
      pre_download_click — fn(page) → Locator: кнопка, открывающая попап скачивания.
    """
    name = site["name"]

    if "pre_download_click" in site:
        pre_btn = site["pre_download_click"](page)
        try:
            await pre_btn.wait_for(timeout=8_000)
            await pre_btn.click()
            await asyncio.sleep(0.5)
        except PwTimeout:
            log.warning("  [%s] Кнопка скачивания (шаг 1) не найдена", name)
            return False

    btn = site["download_btn"](page)
    try:
        await btn.wait_for(timeout=8_000)
    except PwTimeout:
        log.warning("  [%s] Кнопка скачивания не найдена", name)
        return False

    try:
        if "pre_download_click" in site:
            log.info("  [%s] Ожидаем начала скачивания...", name)
        async with page.expect_download(timeout=120_000) as dl_info:
            await btn.click()

        dl       = await dl_info.value
        filename = dl.suggested_filename or f"{query}.mp3"
        dest     = download_dir / safe_filename(filename)
        await dl.save_as(dest)

        if not dest.exists() or dest.stat().st_size == 0:
            if dest.exists():
                dest.unlink()
            log.warning("  [%s] Файл пустой или не создан: %s", name, dest.name)
            return False

        log.info("  [%s] ✓ Скачано: %s (%.1f KB)", name, dest.name, dest.stat().st_size / 1024)
        return True

    except Exception as exc:
        log.warning("  [%s] Ошибка скачивания: %s", name, exc)
        return False
