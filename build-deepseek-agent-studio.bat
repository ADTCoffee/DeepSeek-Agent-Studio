@echo off
setlocal
title Build DeepSeek Agent Studio
cd /d "%~dp0"

echo ============================================
echo   Build DeepSeek Agent Studio (exe)
echo ============================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python not found.
        echo         Install Python 3 from https://www.python.org/
        pause
        exit /b 1
    )
    set "PYCMD=python"
) else (
    set "PYCMD=py -3"
)

echo [1/4] Generating brand logo and icon...
%PYCMD% make_deepseek_icon.py
if errorlevel 1 (
    echo.
    echo [ERROR] Icon generation failed.
    pause
    exit /b 1
)

echo.
echo [2/4] Upgrading PyInstaller...
%PYCMD% -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install PyInstaller.
    pause
    exit /b 1
)

echo.
echo [3/4] Building single-file GUI exe...
%PYCMD% -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "DeepSeek-Agent-Studio" ^
    --icon "assets\deepseek_agent.ico" ^
    "deepseek_agent_studio.pyw"
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller build failed.
    pause
    exit /b 1
)

echo.
echo [4/4] Done.
echo.
echo Output: %~dp0dist\DeepSeek-Agent-Studio.exe
echo.
start "" explorer "%~dp0dist"
pause
endlocal
