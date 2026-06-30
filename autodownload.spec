# autodownload.spec — PyInstaller build specification
#
# Запуск: pyinstaller autodownload.spec --noconfirm
# Или через build.bat (рекомендуется).
#
# Результат: dist/AutoDownload/AutoDownload.exe
# При первом запуске exe скачивает Chromium в dist/AutoDownload/browsers/

from PyInstaller.utils.hooks import collect_all

# Playwright поставляет node.exe + playwright.cmd через hook-playwright.*.py
pl_datas, pl_binaries, pl_hidden = collect_all("playwright")
# customtkinter содержит JSON-темы, которые нужны как data-файлы
ctk_datas, ctk_binaries, ctk_hidden = collect_all("customtkinter")

a = Analysis(
    ["main.py"],
    pathex=["."],
    datas=pl_datas + ctk_datas,
    binaries=pl_binaries + ctk_binaries,
    hiddenimports=pl_hidden + ctk_hidden + [
        # stdlib (могут не подхватиться при lambda-ссылках)
        "asyncio",
        "json",
        "re",
        "pathlib",
        "urllib.parse",
        # наши пакеты
        "bootstrap",
        "config",
        "cli",
        "gui",
        "utils",
        "track_store",
        "customtkinter",
        "darkdetect",
        "yandex",
        "yandex.locators",
        "yandex.auth",
        "yandex.collector",
        "downloader",
        "downloader.matcher",
        "downloader.sites",
        "downloader.browser",
        "downloader.processor",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoDownload",
    console=True,       # нужен терминал для ввода настроек
    uac_admin=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    name="AutoDownload",
)
