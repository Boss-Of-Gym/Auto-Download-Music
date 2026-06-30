"""
downloader/matcher.py — сравнение заголовков треков.

Единственная ответственность: нормализация строки и проверка совпадения.
"""

import re


def normalize(text: str) -> str:
    """Приводит к нижнему регистру, em/en-dash → дефис, схлопывает пробелы."""
    text = re.sub(r"[—–]", "-", text)
    return re.sub(r"\s+", " ", text.lower()).strip()


def titles_match(found: str, query: str) -> bool:
    """
    True если found и query совпадают с допуском на сокращения.

    Три условия: точное совпадение, сайт добавил уточнение (год/ремикс),
    сайт сократил (убрал feat.).
    """
    f = normalize(found)
    q = normalize(query)
    return f == q or q in f or f in q
