@echo off
chcp 65001 >nul
title AQUA Audit Telegram Bot
echo ===================================================
echo        AQUA Audit Telegram Bot (@tupob0ss_bot)
echo ===================================================
echo.

rem Проверка наличия gsheets в PATH
where gsheets.cmd >nul 2>&1
if errorlevel 1 (
    set "PATH=%USERPROFILE%\.gemini\antigravity\bin;%PATH%"
)

echo Запуск бота...
python -u "%~dp0bot.py"
pause
