@echo off
setlocal EnableExtensions
title Ahenk
cd /d "%~dp0"
chcp 65001 >nul

set "VPY="
if exist ".venv\Scripts\python.exe" set "VPY=.venv\Scripts\python.exe"
if not defined VPY if exist "venv\Scripts\python.exe" set "VPY=venv\Scripts\python.exe"
if not defined VPY set "VPY=.venv\Scripts\python.exe"

call :ensure_python
if errorlevel 1 goto :fail
call :ensure_venv
if errorlevel 1 goto :fail

if "%~1"=="cli" goto :exec_cli
if "%~1"=="run" goto :exec_run
if not "%~1"=="" goto :exec_passthru
goto :menu

:exec_cli
"%VPY%" -c "import sys, cli; sys.argv = ['cli.py'] + sys.argv[2:]; sys.exit(cli.main(sys.argv[1:]))" %*
exit /b %errorlevel%

:exec_run
"%VPY%" -c "import sys, main; sys.argv = ['main.py'] + sys.argv[2:]; sys.exit(main.main(sys.argv[1:]))" %*
exit /b %errorlevel%

:exec_passthru
"%VPY%" -c "import sys, cli; sys.argv = ['cli.py'] + sys.argv[1:]; sys.exit(cli.main(sys.argv[1:]))" %*
exit /b %errorlevel%
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
echo Konsol modu baslatiliyor... (Secenekler icin: %VPY% cli.py --help)
"%VPY%" cli.py
if errorlevel 1 (
  echo.
  echo Hata veya eksik anahtar. Ayrintili secenekler icin: "%VPY%" cli.py --help
  pause
)
goto menu
:build
echo.
call build.bat
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
  py -3.11 -c "import sys" >nul 2>&1
  if not errorlevel 1 (
    set "SYSPY=py -3.11"
    exit /b 0
  )
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
  if not errorlevel 1 (
    set "SYSPY=py -3"
    exit /b 0
  )
)
where python >nul 2>&1
if not errorlevel 1 (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
  if not errorlevel 1 (
    set "SYSPY=python"
    exit /b 0
  )
)
echo  Python 3.11 veya uzeri bulunamadi. https://www.python.org/downloads/
exit /b 1

:ensure_venv
if exist "%VPY%" exit /b 0
echo  venv olusturuluyor...
%SYSPY% -m venv .venv
if not exist "%VPY%" (
  echo  venv olusturulamadi.
  exit /b 1
)
call :ensure_deps
exit /b %errorlevel%
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
