@echo off
chcp 65001 >nul
cd /d "%~dp0"
title VinPartsHelper

if not exist ".venv\Scripts\python.exe" (
    echo Первый запуск: устанавливаю программу, это займёт пару минут...
    py -3.13 -m venv .venv 2>nul
    if errorlevel 1 py -3.14 -m venv .venv 2>nul
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo Не найден Python 3.13 (подойдёт и 3.14). Установите его с python.org/downloads, отметьте "Add python.exe to PATH" и запустите файл снова.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Не удалось установить пакеты. Проверьте интернет и запустите файл снова.
        pause
        exit /b 1
    )
)

rem Контакт для владельцев сайтов (e-mail). Впишите свой после знака равно, если хотите.
rem set VINPARTS_CONTACT=ваш@email

".venv\Scripts\python.exe" -m vinparts gui --auto-exit
if errorlevel 1 pause
