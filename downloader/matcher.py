"""
downloader/matcher.py — сравнение заголовков треков.

Единственная ответственность: нормализация строки и проверка совпадения.
"""

import re

# Минимальная длина строки для substring-совпадения.
# Защита от ложных срабатываний на коротких запросах: "Yes" не совпадёт с "Yesterday".
_MIN_SUBSTR_LEN = 10


def normalize(text: str) -> str:
    """Приводит к нижнему регистру, em/en-dash → дефис, схлопывает пробелы."""
    text = re.sub(r"[—–]", "-", text)
    return re.sub(r"\s+", " ", text.lower()).strip()


def titles_match(found: str, query: str) -> bool:
    """
    True если found и query совпадают с допуском на сокращения.

    Точное совпадение (всегда) или substring-совпадение когда обе строки
    достаточно длинные (≥ _MIN_SUBSTR_LEN):
      - q in f: сайт добавил уточнение (год, ремикс, Live)
      - f in q: сайт сократил название (убрал feat., скобки)
    """
    f = normalize(found)
    q = normalize(query)
    if f == q:
        return True
    if len(q) >= _MIN_SUBSTR_LEN and q in f:
        return True
    if len(f) >= _MIN_SUBSTR_LEN and f in q:
        return True
    return False
