@echo off
setlocal EnableExtensions
title Ahenk
cd /d "%~dp0"
chcp 65001 >nul

set "VPY=.venv\Scripts\python.exe"

call :ensure_python
if errorlevel 1 goto :fail
call :ensure_venv
if errorlevel 1 goto :fail
call :ensure_deps
if errorlevel 1 goto :fail

:menu
echo.
echo  Ahenk
echo  ----------------
echo  [1] Calistir
echo  [2] Konsol
echo  [3] Onefile derle
echo  [4] Bagimliliklari yenile
echo  [5] Cikis
echo.
set "SEL="
set /p "SEL=Secim [1-5]: "
if "%SEL%"=="1" goto run
if "%SEL%"=="2" goto cli
if "%SEL%"=="3" goto build
if "%SEL%"=="4" goto deps
if "%SEL%"=="5" goto end
echo  Gecersiz secim.
goto menu

:run
echo.
"%VPY%" main.py
goto menu

:cli
echo.
"%VPY%" cli.py
goto menu

:build
echo.
echo  PyInstaller kuruluyor...
"%VPY%" -m pip install -q pyinstaller
if errorlevel 1 (
  echo  PyInstaller kurulamadi.
  pause
  goto menu
)
echo  Derleniyor: dist\Ahenk.exe
"%VPY%" -m PyInstaller --noconfirm --clean --onefile --windowed --name Ahenk --icon assets\ahenk.ico --add-data "assets;assets" --hidden-import soundcard --hidden-import google.genai --collect-submodules google.genai main.py
if errorlevel 1 (
  echo  Derleme basarisiz.
  pause
  goto menu
)
echo.
echo  Hazir: %cd%\dist\Ahenk.exe
pause
goto menu

:deps
call :ensure_deps
if errorlevel 1 (
  pause
  goto menu
)
echo  Bagimliliklar guncel.
pause
goto menu

:end
exit /b 0

:fail
echo.
pause
exit /b 1

:ensure_python
where py >nul 2>&1
if not errorlevel 1 (
  set "SYSPY=py -3"
  exit /b 0
)
where python >nul 2>&1
if not errorlevel 1 (
  set "SYSPY=python"
  exit /b 0
)
echo  Python bulunamadi. https://www.python.org/downloads/
exit /b 1

:ensure_venv
if exist "%VPY%" exit /b 0
echo  venv olusturuluyor...
%SYSPY% -m venv .venv
if exist "%VPY%" exit /b 0
echo  venv olusturulamadi.
exit /b 1

:ensure_deps
echo  Kutuphaneler kontrol ediliyor...
"%VPY%" -m pip install -q --upgrade pip
if errorlevel 1 exit /b 1
"%VPY%" -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo  Kutuphane kurulumu basarisiz.
  exit /b 1
)
exit /b 0
