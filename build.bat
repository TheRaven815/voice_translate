@echo off
setlocal EnableExtensions
title Ahenk Derleme
cd /d "%~dp0"
chcp 65001 >nul

set "VPY=.venv\Scripts\python.exe"

if not exist "%VPY%" (
    echo [.venv bulunamadi, olusturuluyor...]
    where py >nul 2>&1 && (set "SYSPY=py -3") || (where python >nul 2>&1 && set "SYSPY=python")
    if not defined SYSPY (
        echo [HATA: Python bulunamadi! Lutfen Python yukleyin.]
        pause
        exit /b 1
    )
    %SYSPY% -m venv .venv
    if not exist "%VPY%" (
        echo [HATA: .venv olusturulamadi.]
        pause
        exit /b 1
    )
    "%VPY%" -m pip install -q --upgrade pip
    "%VPY%" -m pip install -q -r requirements.txt
)

echo [PyInstaller kontrol ediliyor...]
"%VPY%" -m pip install -q pyinstaller
if errorlevel 1 (
    echo [HATA: PyInstaller yuklenemedi.]
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Ahenk Derleniyor...
echo ========================================
echo.

"%VPY%" -m PyInstaller --noconfirm --clean Ahenk.spec

if errorlevel 1 (
    echo.
    echo [HATA: Derleme basarisiz oldu!]
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Derleme tamamlandi!
echo   Cikti: %cd%\dist\Ahenk.exe
echo ========================================
echo.
pause
