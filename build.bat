@echo off
setlocal EnableExtensions
title Ahenk Derleme
cd /d "%~dp0"
chcp 65001 >nul

set "NOPAUSE="
if /i "%~1"=="/nopause" set "NOPAUSE=1"
if /i "%~1"=="--nopause" set "NOPAUSE=1"

set "VPY="
if exist ".venv\Scripts\python.exe" set "VPY=.venv\Scripts\python.exe"
if not defined VPY if exist "venv\Scripts\python.exe" set "VPY=venv\Scripts\python.exe"
if not defined VPY set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" call :init_venv
if errorlevel 1 (
    if not defined NOPAUSE pause
    exit /b 1
)

echo [PyInstaller kontrol ediliyor...]
"%VPY%" -m pip install -q pyinstaller
if errorlevel 1 (
    echo [HATA: PyInstaller yuklenemedi.]
    if not defined NOPAUSE pause
    exit /b 1
)

echo.
echo ========================================
echo   Ahenk Derleniyor...
echo ========================================
echo.

if exist "Ahenk.spec" (
    "%VPY%" -m PyInstaller --noconfirm --clean Ahenk.spec
) else (
    "%VPY%" -m PyInstaller --noconfirm --clean --onefile --windowed --name Ahenk --icon assets\ahenk.ico --add-data "assets;assets" --hidden-import soundcard --hidden-import google.genai --collect-submodules google.genai main.py
)

if errorlevel 1 (
    echo.
    echo [HATA: Derleme basarisiz oldu!]
    if not defined NOPAUSE pause
    exit /b 1
)
"%VPY%" -c "import hashlib,pathlib; p=pathlib.Path(r'dist\Ahenk.exe'); pathlib.Path(r'dist\Ahenk.exe.sha256').write_text(hashlib.sha256(p.read_bytes()).hexdigest() + ' *Ahenk.exe\n', encoding='ascii')"
if errorlevel 1 (
    echo [HATA: SHA-256 dosyasi olusturulamadi.]
    if not defined NOPAUSE pause
    exit /b 1
)

echo.
echo ========================================
echo   Derleme tamamlandi!
echo   GUI Cikti: %cd%\dist\Ahenk.exe
echo   CLI Cikti: %cd%\dist\Ahenk-cli.exe
echo ========================================
echo.
if not defined NOPAUSE pause
exit /b 0

:init_venv
echo [.venv bulunamadi, olusturuluyor...]
set "SYSPY="
where py >nul 2>&1 && set "SYSPY=py -3"
if not defined SYSPY where python >nul 2>&1 && set "SYSPY=python"
if not defined SYSPY (
    echo [HATA: Python bulunamadi! Lutfen Python yukleyin.]
    exit /b 1
)
%SYSPY% -m venv .venv
if not exist "%VPY%" (
    echo [HATA: .venv olusturulamadi.]
    exit /b 1
)
"%VPY%" -m pip install -q --upgrade pip
"%VPY%" -m pip install -q -r requirements.txt
exit /b 0
