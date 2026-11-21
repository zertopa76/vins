"""Собственное окно программы (без браузера, вкладок и адресной строки).

Использует pywebview: на Windows это встроенный в систему WebView2 (движок Edge), на Mac WebKit.
Интерфейс тот же, что и раньше, только показан в окне приложения. Если окно создать нельзя
(нет pywebview или WebView2), run_native() возвращает False, и программа открывается в запасном режиме.
"""

from __future__ import annotations

import re
import sys
import threading
import webbrowser
from pathlib import Path

TITLE = "VinPartsHelper"
_WINDOW_SIZE = (1320, 900)
_MIN_SIZE = (980, 640)


class _Api:
    """Что страница может попросить у программы. Публичные методы видны странице, поэтому их мало."""

    def __init__(self) -> None:
        self._window = None       # с подчёркиванием: pywebview такие атрибуты странице не показывает

    def open_external(self, url: str) -> bool:
        """Ссылки на источники открываются в обычном браузере, а не внутри окна программы."""
        if isinstance(url, str) and re.match(r"https?://", url, re.IGNORECASE):
            webbrowser.open(url)
            return True
        return False

    def quit(self) -> None:
        if self._window is not None:
            self._window.destroy()


def _bring_to_front(window) -> bool:
    for name in ("restore", "show"):
        try:
            getattr(window, name)()
        except Exception:  # noqa: BLE001 - не все платформы умеют всё
            pass
    return True


def run_native(server, storage_dir: Path | None = None) -> bool:
    """Показывает окно и ждёт, пока его закроют. True: окно было показано и закрыто пользователем.
    False: окно создать не удалось (причина в server.window_error), сервер продолжает работать."""
    try:
        import webview
    except Exception as exc:  # noqa: BLE001
        server.window_error = f"не установлен pywebview ({exc.__class__.__name__})"
        return False

    api = _Api()
    try:
        window = webview.create_window(TITLE, server.url, js_api=api, width=_WINDOW_SIZE[0],
                                       height=_WINDOW_SIZE[1], min_size=_MIN_SIZE, text_select=True)
    except Exception as exc:  # noqa: BLE001
        server.window_error = str(exc)
        return False
    api._window = window

    shown = threading.Event()
    window.events.shown += shown.set
    server.on_focus = lambda: _bring_to_front(window)

    def close_when_server_stops() -> None:      # кнопка «Выход» в интерфейсе останавливает сервер
        server.stop_event.wait()
        try:
            window.destroy()
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=close_when_server_stops, daemon=True).start()

    options: dict = {"private_mode": False}      # чтобы язык и недавние запросы сохранялись между запусками
    if storage_dir is not None:
        options["storage_path"] = str(storage_dir)
    if sys.platform.startswith("win"):
        options["gui"] = "edgechromium"          # не позволяем откатиться на старый движок Internet Explorer

    try:
        webview.start(**options)                 # блокирует, пока окно открыто (вызывать из главного потока)
    except Exception as exc:  # noqa: BLE001
        server.window_error = str(exc)
        return False
    finally:
        server.on_focus = None
    if not shown.is_set():
        server.window_error = server.window_error or "окно не открылось"
        return False
    return True
