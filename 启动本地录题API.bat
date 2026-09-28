@echo off
setlocal EnableExtensions DisableDelayedExpansion
title MathCyclus Local Draft API
set "PROJECT_DIR=%~dp0"
pushd "%PROJECT_DIR%" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Cannot open the project folder.
    pause
    exit /b 1
)

set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    echo [ERROR] The project virtual environment was not found.
    echo Run 启动程序.bat once first.
    pause
    exit /b 1
)

"%VENV_PYTHON%" scripts\run_local_api.py --port 8765
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%

