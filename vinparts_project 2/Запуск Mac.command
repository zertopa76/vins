#!/bin/bash
cd "$(dirname "$0")" || exit 1

PY=""
for candidate in python3.13 /usr/local/bin/python3.13 /opt/homebrew/bin/python3.13 \
                 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \
                 python3.14 /usr/local/bin/python3.14 /opt/homebrew/bin/python3.14 \
                 /Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then
    echo "Не найден Python 3.13 (подойдёт и 3.14). Установите его с python.org/downloads/macos и запустите файл снова."
    read -r -p "Нажмите Enter, чтобы закрыть..." _
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "Первый запуск: устанавливаю программу, это займёт пару минут..."
    "$PY" -m venv .venv && .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt || {
        echo "Не удалось установить пакеты. Проверьте интернет и запустите файл снова."
        read -r -p "Нажмите Enter, чтобы закрыть..." _
        exit 1
    }
fi

# Контакт для владельцев сайтов (e-mail). Раскомментируйте и впишите свой:
# export VINPARTS_CONTACT="ваш@email"

.venv/bin/python -m vinparts gui --auto-exit
