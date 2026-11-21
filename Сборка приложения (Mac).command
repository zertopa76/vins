#!/bin/bash
cd "$(dirname "$0")" || exit 1
echo "Сборка приложения VinPartsHelper.app. Нужен интернет, займёт несколько минут."

PY=""
for candidate in python3.13 /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13 \
                 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \
                 python3.14 /opt/homebrew/bin/python3.14 /usr/local/bin/python3.14 \
                 /Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then
    echo "Не найден Python 3.13 (подойдёт и 3.14). Установите его с python.org/downloads/macos и запустите файл снова."
    read -r -p "Нажмите Enter, чтобы закрыть..." _
    exit 1
fi

fail() {
    echo
    echo "Сборка не удалась. Скопируйте текст ошибки выше и пришлите его."
    read -r -p "Нажмите Enter, чтобы закрыть..." _
    exit 1
}

[ -x ".build-venv/bin/python" ] || "$PY" -m venv .build-venv || fail
.build-venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt -r requirements-build.txt || fail

.build-venv/bin/python -m PyInstaller --noconfirm --clean --windowed \
    --name VinPartsHelper --icon assets/icon.icns --osx-bundle-identifier local.vinpartshelper \
    --add-data "vinparts/app/static:vinparts/app/static" \
    --collect-all pypdfium2 --collect-all pypdfium2_raw \
    --collect-submodules lxml --hidden-import lxml._elementpath \
    --collect-all webview \
    --hidden-import webview.platforms.cocoa \
    --exclude-module tkinter \
    vinparts_app.py || fail

echo
echo "Готово: $(pwd)/dist/VinPartsHelper.app"
echo "Перетащите VinPartsHelper.app в папку «Программы». При первом запуске: правый щелчок → «Открыть»."
open dist
read -r -p "Нажмите Enter, чтобы закрыть..." _
