"""
locators.py — обратная совместимость.

Содержимое разнесено по модулям:
  YandexMusic → yandex/locators.py
  SITES       → downloader/sites.py
"""

from downloader.sites import SITES
from yandex.locators import YandexMusic

__all__ = ["YandexMusic", "SITES"]
