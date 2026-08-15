@echo off
setlocal
title DeepSeek Agent Studio - Syntax Check
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
    py -3 -m py_compile deepseek_agent_core.py deepseek_agent_studio.pyw deepseek_eyes.py deepseek_updater.py make_deepseek_icon.py publish_update.py
    goto :check
)

where python >nul 2>nul
if not errorlevel 1 (
    python -m py_compile deepseek_agent_core.py deepseek_agent_studio.pyw deepseek_eyes.py deepseek_updater.py make_deepseek_icon.py publish_update.py
    goto :check
)

echo [ERROR] Python not found.
pause
exit /b 1

:check
if errorlevel 1 (
    echo.
    echo [ERROR] Syntax check failed. See messages above.
    pause
    exit /b 1
)
echo.
echo [OK] All Python files passed syntax check.
pause
