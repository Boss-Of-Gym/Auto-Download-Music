@echo off
setlocal

set PYTHON=.venv\Scripts\python.exe
set DIST=dist\AutoDownload

echo.
echo =========================================================
echo   AutoDownload - build distribution
echo =========================================================
echo.

if not exist %PYTHON% (
    echo ERROR: virtual environment not found.
    echo.
    echo Create it with:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo   .venv\Scripts\python.exe -m playwright install chromium
    echo.
    pause
    exit /b 1
)

echo [1/3] Installing/checking PyInstaller...
%PYTHON% -m pip install pyinstaller --quiet
if errorlevel 1 (
    echo ERROR: failed to install PyInstaller.
    pause
    exit /b 1
)

echo [2/3] Cleaning previous build...
if exist %DIST% rmdir /s /q %DIST%
if exist build   rmdir /s /q build

echo [3/3] Building...
%PYTHON% -m PyInstaller autodownload.spec --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR: build failed.
    pause
    exit /b 1
)

echo.
echo =========================================================
echo   Done! Distribution ready: %DIST%\
echo.
echo   For users:
echo     1. Copy the AutoDownload\ folder anywhere
echo     2. Run AutoDownload.exe
echo     3. First launch downloads Chromium (~180 MB, once)
echo =========================================================
echo.
pause
endlocal
