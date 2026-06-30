"""
downloader/sites.py — реестр сайтов-источников для скачивания MP3.

Единственная ответственность: хранить описание каждого сайта в виде словаря
с Playwright-локаторами. Никакой логики поиска или скачивания здесь нет.

Ключи каждого словаря:
  name              — отображаемое имя в логах
  search_url        — шаблон URL; {q} заменяется URL-кодированным запросом
  result            — fn(page) → Locator всех результатов поиска
  title             — fn(element) → Locator названия (inner_text)
  title_attr        — str: читать через get_attribute() вместо inner_text()
  title_fn          — async fn(element) → str: кастомная логика названия
  click             — fn(element) → Locator для клика (переход на страницу трека)
  no_navigate       — bool: не переходить со страницы поиска (download_btn в выдаче)
  pre_download_click— fn(page) → Locator кнопки, открывающей попап скачивания
  download_btn      — fn(page) → Locator финальной кнопки / ссылки скачивания
"""

import json as _json


async def _hitmoz_title(el) -> str:
    """Читает data-musmeta с li.tracks__item и возвращает 'Исполнитель — Название'."""
    raw  = await el.get_attribute("data-musmeta") or "{}"
    meta = _json.loads(raw)
    artist = meta.get("artist", "")
    title  = meta.get("title", "")
    return f"{artist} — {title}" if artist else title


SITES: list[dict] = [
    # ── zaycev.net ───────────────────────────────────────────────────────────
    # DOM: <li> → <div data-qa="track"> → <article> → <a data-qa="track-link" title="Исполнитель - Название">
    # Скачивание: 2 шага — [data-qa="track-download"] открывает попап,
    # затем *klCQXA* запускает рекламу → файл.
    {
        "name":               "zaycev.net",
        "search_url":         "https://zaycev.net/search?query_search={q}&type=track",
        "result":             lambda page: page.locator("li:has([data-qa='track'])"),
        "no_results_text":    "не найдено",
        "title":              lambda el: el.locator("a[data-qa='track-link']"),
        "title_attr":         "title",
        "click":              lambda el: el.locator("a[data-qa='track-link']"),
        "pre_download_click": lambda page: page.locator("[data-qa='track-download']").first,
        "download_btn":       lambda page: page.locator("[class*='klCQXA']").first,
    },
    # ── hitmoz.org ───────────────────────────────────────────────────────────
    # DOM: ul.tracks__list → li.tracks__item[data-musmeta='{artist,title}']
    # Кнопка скачивания находится в поисковой выдаче — переход на страницу трека не нужен.
    {
        "name":         "hitmoz.org",
        "search_url":   "https://rus.hitmoz.org/search?q={q}",
        "result":       lambda page: page.locator("li.tracks__item"),
        "title_fn":     _hitmoz_title,
        "no_navigate":  True,
        "download_btn": lambda page: page.locator("a.track__download-btn").first,
    },
    # 101.ru исключён: /download/{id} ведёт на страницу со ссылками на YouTube Music,
    # а не на прямой MP3-файл.
]
