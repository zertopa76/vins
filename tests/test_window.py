"""Окно приложения проверяется на подставном pywebview: настоящее окно здесь показать нельзя."""
import sys
import threading
import types

import pytest

from tests.demo_server import build_service
from vinparts import cli
from vinparts.app import window as win
from vinparts.app.server import AppServer, focus_running


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self

    def fire(self):
        for fn in self.handlers:
            fn()


class FakeWindow:
    def __init__(self):
        self.events = types.SimpleNamespace(shown=Event())
        self.calls = []

    def destroy(self): self.calls.append("destroy")
    def restore(self): self.calls.append("restore")
    def show(self): self.calls.append("show")


def fake_webview(show=True, fail_start=False, fail_create=False, hold=None):
    mod = types.ModuleType("webview")
    mod.created, mod.started, mod.windows = [], [], []

    def create_window(title, url, **kw):
        if fail_create:
            raise RuntimeError("нет движка")
        window = FakeWindow()
        mod.created.append((title, url, kw))
        mod.windows.append(window)
        return window

    def start(**kw):
        mod.started.append(kw)
        if fail_start:
            raise RuntimeError("WebView2 не найден")
        window = mod.windows[0]
        if show:
            window.events.shown.fire()
        if hold:                       # окно «открыто», пока не нажмут «Выход» или не закроют
            hold.wait(5)

    mod.create_window, mod.start = create_window, start
    return mod


@pytest.fixture
def server(tmp_path):
    srv = AppServer(build_service(tmp_path), 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_window_is_created_with_app_settings(monkeypatch, server, tmp_path):
    mod = fake_webview()
    monkeypatch.setitem(sys.modules, "webview", mod)
    monkeypatch.setattr(sys, "platform", "win32")
    assert win.run_native(server, tmp_path / "wv") is True
    title, url, kw = mod.created[0]
    assert title == "VinPartsHelper" and url == server.url
    assert kw["text_select"] is True and kw["min_size"] == (980, 640)
    opts = mod.started[0]
    assert opts["gui"] == "edgechromium" and opts["private_mode"] is False
    assert opts["storage_path"] == str(tmp_path / "wv")


def test_no_edge_forcing_on_mac(monkeypatch, server):
    mod = fake_webview()
    monkeypatch.setitem(sys.modules, "webview", mod)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert win.run_native(server) is True and "gui" not in mod.started[0]


def test_falls_back_when_pywebview_missing(monkeypatch, server):
    monkeypatch.setitem(sys.modules, "webview", None)       # import webview -> ImportError
    assert win.run_native(server) is False and "pywebview" in server.window_error


@pytest.mark.parametrize("kwargs, text", [({"fail_start": True}, "WebView2"), ({"fail_create": True}, "движка"),
                                           ({"show": False}, "не открылось")])
def test_falls_back_when_window_cannot_be_shown(monkeypatch, server, kwargs, text):
    monkeypatch.setitem(sys.modules, "webview", fake_webview(**kwargs))
    assert win.run_native(server) is False and text in server.window_error


def test_quit_button_closes_window(monkeypatch, server):
    release = threading.Event()
    mod = fake_webview(hold=release)
    monkeypatch.setitem(sys.modules, "webview", mod)
    done = {}
    thread = threading.Thread(target=lambda: done.setdefault("r", win.run_native(server)), daemon=True)
    thread.start()
    while not mod.windows:
        pass
    server.stop_event.set()                                   # то же делает кнопка «Выход»
    for _ in range(100):
        if "destroy" in mod.windows[0].calls:
            break
        threading.Event().wait(0.05)
    assert "destroy" in mod.windows[0].calls
    release.set()
    thread.join(5)
    assert done["r"] is True


def test_second_launch_brings_window_to_front(monkeypatch, server):
    release = threading.Event()
    mod = fake_webview(hold=release)
    monkeypatch.setitem(sys.modules, "webview", mod)
    thread = threading.Thread(target=lambda: win.run_native(server), daemon=True)
    thread.start()
    for _ in range(100):
        if server.on_focus:
            break
        threading.Event().wait(0.05)
    assert focus_running(server.port) is True
    assert mod.windows[0].calls[-2:] == ["restore", "show"]
    release.set()
    thread.join(5)
    assert focus_running(server.port) is False                # окна больше нет


def test_focus_false_without_window(server):
    assert focus_running(server.port) is False


def test_external_links_open_in_default_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(win.webbrowser, "open", opened.append)
    api = win._Api()
    assert api.open_external("https://vwts.ru/a.pdf#page=2") is True
    assert api.open_external("javascript:alert(1)") is False
    assert api.open_external("file:///etc/passwd") is False
    assert opened == ["https://vwts.ru/a.pdf#page=2"]


def test_api_exposes_only_what_page_needs():
    public = [n for n in dir(win._Api()) if not n.startswith("_")]
    assert sorted(public) == ["open_external", "quit"]


def test_gui_command_uses_native_window_and_exits_when_closed(monkeypatch, tmp_path):
    called = {}
    monkeypatch.setattr(win, "run_native", lambda server, storage=None: called.setdefault("ok", True))
    opened = []
    monkeypatch.setattr("vinparts.app.launcher.open_ui", lambda *a, **k: opened.append(a))
    assert cli.main(["--data-dir", str(tmp_path), "gui", "--port", "0"]) == 0
    assert called["ok"] and not opened                        # браузер не открывался


def test_gui_command_falls_back_to_browser(monkeypatch, tmp_path, capsys):
    def no_window(server, storage=None):
        server.window_error = "WebView2 не найден"
        return False

    monkeypatch.setattr(win, "run_native", no_window)
    monkeypatch.setattr("vinparts.app.launcher.open_ui", lambda url, app_window=True: "app-window")
    monkeypatch.setattr("vinparts.app.server.AppServer.start_watchdog",
                        lambda self, idle, tick=5.0: self.stop_event.set())    # сразу «закрыли окно»
    assert cli.main(["--data-dir", str(tmp_path), "gui", "--port", "0", "--auto-exit"]) == 0
    out = capsys.readouterr().out
    assert "WebView2 не найден" in out and "Открываю в браузере" in out
