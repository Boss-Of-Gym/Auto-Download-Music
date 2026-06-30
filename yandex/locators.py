"""
yandex/locators.py — Playwright-локаторы для Яндекс.Музыки и Яндекс.ID.

Только статические методы. Никакой логики навигации или авторизации —
это находится в auth.py и collector.py.
"""

from playwright.async_api import Locator, Page


class YandexMusic:
    """
    Полные локаторы элементов Яндекс.Музыки и формы Яндекс.ID.
    Каждый метод принимает page (или элемент) и возвращает Locator.
    """

    # ── Проверка авторизации ──────────────────────────────────────

    @staticmethod
    def avatar(page: Page, name_account: str) -> Locator:
        """Аватар аккаунта в шапке — появляется только после входа."""
        return page.get_by_text(name_account)

    # ── Начало входа: кнопки на главной странице ──────────────────

    @staticmethod
    def close_banner_btn(page: Page) -> Locator:
        """Кнопка закрытия рекламного баннера (aria role=button)."""
        return page.get_by_role("button", name="Закрыть")

    @staticmethod
    def profile_btn(page: Page) -> Locator:
        """Кнопка открытия меню профиля (aria-label)."""
        return page.get_by_label("Ваш профиль")

    # ── Форма Яндекс.ID внутри iframe ────────────────────────────

    @staticmethod
    def auth_btn(page: Page) -> Locator:
        """Кнопка «Войти» внутри iframe Яндекс.ID (aside iframe → content_frame)."""
        return page.locator("aside iframe").content_frame.get_by_test_id("auth")

    # ── Форма ввода телефона ──────────────────────────────────────

    @staticmethod
    def phone_input(page: Page) -> Locator:
        """Поле ввода номера телефона (input внутри контейнера phone-input)."""
        return page.get_by_test_id("phone-input").locator("input[data-testid='text-field-input']")

    @staticmethod
    def phone_next_btn(page: Page) -> Locator:
        """Кнопка «Далее» после ввода телефона."""
        return page.get_by_test_id("split-add-user-next-phone")

    # ── OTP-код (6 отдельных ячеек) ──────────────────────────────

    @staticmethod
    def code_segment(page: Page, index: int) -> Locator:
        """Одна ячейка OTP-кода по индексу 0–5."""
        return page.get_by_test_id("code-field-segment").nth(index)

    # ── Выбор аккаунта и пропуск рекламы ────────────────────────

    @staticmethod
    def account_item(page: Page, name_account: str, Yandex_login: str) -> Locator:
        """Элемент аккаунта в списке выбора по точному имени."""
        return page.get_by_role("button", name=f"{name_account}, {Yandex_login}")

    @staticmethod
    def promo_skip_btn(page: Page) -> Locator:
        """Кнопка пропуска рекламного экрана Яндекс.ID."""
        return page.get_by_test_id("identification-promo-start-skip-btn")

    # ── Плейлист: навигация ──────────────────────────────────────

    @staticmethod
    def go_to_favorite(page: Page) -> Locator:
        """Кнопка перехода в раздел «Коллекция»."""
        return page.get_by_role("link", name="Коллекция")

    @staticmethod
    def choise_our_playlist(page: Page, name_playlist: str) -> Locator:
        """Ссылка на конкретный плейлист по его имени."""
        return page.get_by_role("link", name=name_playlist)

    # ── Плейлист: содержимое ─────────────────────────────────────

    @staticmethod
    def playlist_track_count(page: Page) -> Locator:
        """Span в шапке плейлиста с атрибутом title='N трек'."""
        return page.locator("span[title*='трек']")

    @staticmethod
    def track_items(page: Page) -> Locator:
        """Все видимые контейнеры треков — по атрибуту data-index."""
        return page.locator("div[data-index]")

    @staticmethod
    def track_title(item: Locator) -> Locator:
        """Название трека (без версии/ремастера)."""
        return item.locator("[class*='Meta_title__']")

    @staticmethod
    def track_artists(item: Locator) -> Locator:
        """Контейнер исполнителей трека."""
        return item.locator("[class*='Meta_artists__']")
