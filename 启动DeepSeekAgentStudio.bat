@echo off
setlocal
title DeepSeek Agent Studio
cd /d "%~dp0"

rem Prefer the latest source so eyes/updater changes take effect immediately.
where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%~dp0deepseek_agent_studio.pyw"
    exit /b 0
)

where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%~dp0deepseek_agent_studio.pyw"
    exit /b 0
)

where py >nul 2>nul
if not errorlevel 1 (
    start "" py -3 "%~dp0deepseek_agent_studio.pyw"
    exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
    start "" python "%~dp0deepseek_agent_studio.pyw"
    exit /b 0
)

if exist "%~dp0dist\DeepSeek-Agent-Studio.exe" (
    start "" "%~dp0dist\DeepSeek-Agent-Studio.exe"
    exit /b 0
)

echo [ERROR] Cannot find Python or DeepSeek-Agent-Studio.exe.
echo.
echo Options:
echo   1. Install Python 3 from https://www.python.org/
echo   2. Run build-deepseek-agent-studio.bat to create the exe.
pause
exit /b 1
