@echo off
setlocal EnableExtensions
rem Console - Windows launcher (equivalent to start.command / start.sh)
rem Listens on 127.0.0.1:9600 and opens the browser.
rem
rem NOTE: keep this file ASCII-only. cmd.exe parses .bat files with the system
rem OEM code page (e.g. 936/GBK), so any non-ASCII (Chinese) comment can be
rem misread and break the parser. Keep all comments/labels ASCII.
cd /d "%~dp0"

rem Pick a real Python >= 3.12. We walk every interpreter on PATH and every
rem location each one resolves to, skipping the Windows Store "App execution
rem alias" stubs (which would only open the Store) and any interpreter that is
rem actually < 3.12. This keeps working even when a project/tool venv (e.g. a
rem 3.11 one) is first on PATH, as long as a 3.12+ interpreter is present.
set "PY_CMD="

rem -- python --
for /f "delims=" %%i in ('where python 2^>nul') do (
    if not defined PY_CMD (
        echo %%i | findstr /i /c:"WindowsApps" >nul
        if errorlevel 1 (
            "%%i" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
            if not errorlevel 1 set "PY_CMD=%%i"
        )
    )
)

rem -- python3 --
for /f "delims=" %%i in ('where python3 2^>nul') do (
    if not defined PY_CMD (
        echo %%i | findstr /i /c:"WindowsApps" >nul
        if errorlevel 1 (
            "%%i" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
            if not errorlevel 1 set "PY_CMD=%%i"
        )
    )
)

rem -- py --
for /f "delims=" %%i in ('where py 2^>nul') do (
    if not defined PY_CMD (
        echo %%i | findstr /i /c:"WindowsApps" >nul
        if errorlevel 1 (
            "%%i" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
            if not errorlevel 1 set "PY_CMD=%%i"
        )
    )
)

if not defined PY_CMD (
    echo Error: no Python 3.12 or newer was found on PATH.
    echo   Install Python 3.12+, or activate a conda environment with Python 3.12.
    echo   Probed: python, python3, py
    pause
    exit /b 127
)

rem PY_CMD already passed the >= 3.12 check above, so just start the console.
"%PY_CMD%" server.py
exit /b 0
