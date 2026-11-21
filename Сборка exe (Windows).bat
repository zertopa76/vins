@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Сборка VinPartsHelper.exe

echo Сборка приложения VinPartsHelper.exe. Нужен интернет, займёт несколько минут.
echo.

set "PYCMD="
py -3.13 -c "import sys" >nul 2>&1 && set "PYCMD=py -3.13"
if not defined PYCMD (py -3.14 -c "import sys" >nul 2>&1 && set "PYCMD=py -3.14")
if not defined PYCMD (
    echo Не найден Python 3.13 (подойдёт и 3.14). Установите его с python.org/downloads, отметьте "Add python.exe to PATH" и запустите файл снова.
    pause
    exit /b 1
)

if not exist ".build-venv\Scripts\python.exe" (
    %PYCMD% -m venv .build-venv || goto :fail
)
".build-venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt -r requirements-build.txt || goto :fail

".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onefile ^
    --name VinPartsHelper --icon "assets\icon.ico" ^
    --add-data "vinparts\app\static;vinparts\app\static" ^
    --collect-all pypdfium2 --collect-all pypdfium2_raw ^
    --collect-submodules lxml --hidden-import lxml._elementpath ^
    --collect-all webview --collect-all pythonnet --collect-all clr_loader ^
    --hidden-import webview.platforms.edgechromium --hidden-import webview.platforms.winforms ^
    --exclude-module tkinter ^
    vinparts_app.py || goto :fail

echo.
echo Готово. Приложение - один файл: %CD%\dist\VinPartsHelper.exe
echo Его можно скопировать куда угодно и запускать двойным щелчком. Первый запуск занимает несколько секунд.
echo.
choice /c YN /m "Создать ярлык на рабочем столе"
if errorlevel 2 goto :end
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\VinPartsHelper.lnk'); $s.TargetPath='%CD%\dist\VinPartsHelper.exe'; $s.WorkingDirectory='%CD%\dist'; $s.IconLocation='%CD%\dist\VinPartsHelper.exe'; $s.Save()"
echo Ярлык создан.
:end
pause
exit /b 0

:fail
echo.
echo Сборка не удалась. Скопируйте текст ошибки выше и пришлите его.
pause
exit /b 1
