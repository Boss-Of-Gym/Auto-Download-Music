"""
yandex/auth.py — авторизация в Яндекс.Музыке через Яндекс.ID.

Единственная ответственность: открыть браузер на music.yandex.ru,
пройти форму телефон→OTP и убедиться что аватар появился.
"""

import asyncio
import logging

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PwTimeout

from config import AppConfig
from yandex.locators import YandexMusic

log = logging.getLogger(__name__)


async def is_logged_in(page: Page, config: AppConfig) -> bool:
    """Вернуть True если аватар аккаунта виден (пользователь авторизован)."""
    try:
        await YandexMusic.avatar(page, config.yandex_account_name).wait_for(timeout=4_000)
        return True
    except PwTimeout:
        return False


async def login(page: Page, config: AppConfig, code_callback=None) -> None:
    """
    Авторизация через Яндекс.ID (телефон + OTP из push-уведомления).

    Шаги:
      1. Закрыть рекламный баннер (если есть).
      2. Открыть меню профиля → нажать «Войти» в iframe Яндекс.ID.
      3. Ввести номер телефона → нажать «Далее».
      4. Прочитать OTP из консоли и заполнить ячейки кода.
      5. Выбрать аккаунт из списка (если несколько).
      6. Пропустить рекламный экран Яндекс.ID.
      7. Убедиться что аватар появился — вход подтверждён.
    """
    log.info("Авторизация...")
    await page.goto("https://music.yandex.ru/", wait_until="domcontentloaded")

    # Шаг 1: закрыть баннер если появился (не всегда есть)
    try:
        await YandexMusic.close_banner_btn(page).click(timeout=5_000)
    except PwTimeout:
        pass

    # Шаг 2: открыть меню профиля и нажать «Войти» в iframe Яндекс.ID
    await YandexMusic.profile_btn(page).click()
    await YandexMusic.auth_btn(page).click()
    await page.wait_for_load_state("domcontentloaded")

    # Шаг 3: ввести номер телефона (задержка: маска поля инициализируется асинхронно)
    phone_field = YandexMusic.phone_input(page)
    await phone_field.click()
    await asyncio.sleep(0.7)
    await phone_field.press_sequentially(config.yandex_phone, delay=120)
    await YandexMusic.phone_next_btn(page).click()

    # Шаг 4: ввод OTP-кода — через callback (GUI-диалог) или терминал (CLI)
    log.info("─" * 50)
    log.info("Push-уведомление отправлено на %s", config.yandex_phone)
    if code_callback is None:
        log.info("Введите 6-значный код в терминале и нажмите Enter.")
    log.info("─" * 50)
    _read_code = code_callback if code_callback is not None else (
        lambda: input("  Код подтверждения: ").strip()
    )
    loop = asyncio.get_running_loop()
    code = await loop.run_in_executor(None, _read_code)
    for i, digit in enumerate(code[:6]):
        await YandexMusic.code_segment(page, i).fill(digit)

    # Шаг 5: выбрать аккаунт из списка (если несколько)
    if config.yandex_account_name:
        try:
            await YandexMusic.account_item(
                page,
                name_account=config.yandex_account_name,
                Yandex_login=config.yandex_login,
            ).click(timeout=8_000)
        except PwTimeout:
            pass  # аккаунт единственный — список не появился

    # Шаг 6: пропустить рекламный экран Яндекс.ID
    try:
        await YandexMusic.promo_skip_btn(page).click(timeout=8_000)
    except PwTimeout:
        pass

    # Шаг 7: убедиться что вход успешен
    try:
        await YandexMusic.avatar(page, config.yandex_account_name).wait_for(timeout=15_000)
        log.info("Авторизация успешна")
    except PwTimeout:
        raise RuntimeError("Авторизация не подтверждена — аватар не появился.")
