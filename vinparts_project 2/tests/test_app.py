import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from tests.demo_server import ENGINE_PDF, build_service
from vinparts.app import launcher
from vinparts.app.server import AppServer


class Api:
    """Тонкий клиент к локальному серверу, как это делает страница."""

    def __init__(self, server: AppServer):
        self.base = f"http://127.0.0.1:{server.port}"
        html = urllib.request.urlopen(self.base + "/").read().decode("utf-8")
        self.token = re.search(r'name="token" content="([^"]+)"', html).group(1)
        self.html = html

    def call(self, path, body=None, method=None, raw=None, headers=None, token=True):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method or ("POST" if data is not None else "GET"))
        if token:
            req.add_header("X-Token", self.token)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req) as resp:
                payload = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                return resp.status, (json.loads(payload) if "json" in ctype else payload)
        except urllib.error.HTTPError as err:
            payload = err.read()
            return err.code, (json.loads(payload) if payload.startswith(b"{") else payload)

    def wait(self, job, states=("done", "error", "cancelled", "waiting_confirm"), timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            _, snap = self.call(f"/api/job/{job}")
            if snap["state"] in states:
                return snap
            time.sleep(0.05)
        raise AssertionError("задача не завершилась")


@pytest.fixture
def world(tmp_path):
    service = build_service(tmp_path)
    server = AppServer(service, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield service, server, Api(server)
    server.shutdown()
    server.server_close()


SEARCH = {"op": "цепь грм", "model": "Golf 7", "engine": "cjsa"}


def finish(api, job, choice="yes"):
    """Отвечает на все вопросы о скачивании (их по одному на раздел) и ждёт результат."""
    snap = api.wait(job)
    while snap["state"] == "waiting_confirm":
        api.call(f"/api/job/{job}/confirm", {"choice": choice})
        time.sleep(0.1)
        snap = api.wait(job)
    return snap


# ------------------------------------------------------------------ безопасность
def test_api_needs_token_and_local_host(world):
    _, server, api = world
    assert api.call("/api/info", token=False)[0] == 403
    assert api.call("/api/info")[0] == 200
    assert api.call("/api/info", headers={"Host": "evil.example"})[0] == 403
    assert api.call("/api/search", SEARCH, headers={"Origin": "http://evil.example"})[0] == 403
    assert api.call("/api/search", SEARCH, token=False)[0] == 403


def test_page_is_served_with_csp(world):
    _, server, api = world
    with urllib.request.urlopen(api.base + "/") as resp:
        assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
    assert "__TOKEN__" not in api.html and len(api.token) > 20


def test_shutdown_sets_stop_event(world):
    _, server, api = world
    assert api.call("/api/shutdown", {})[0] == 200
    assert server.stop_event.is_set()


# ----------------------------------------------------------------------- данные
def test_info_lists_models_engines_and_operations(world):
    _, _, api = world
    _, info = api.call("/api/info")
    assert {o["id"] for o in info["operations"]} >= {"timing_chain", "clutch"}
    assert info["index"]["vwts"]["docs"] > 0 and info["engines"]
    assert info["sources"][0]["allows_llm"] is False


def test_vin_endpoint(world):
    _, _, api = world
    _, ok = api.call("/api/vin", {"vin": "WVWZZZAUZDW000000"})
    assert ok["valid"] and ok["make"] == "Volkswagen" and ok["year"] == 2013
    assert api.call("/api/vin", {"vin": "123"})[1]["valid"] is False


# ------------------------------------------------------------------------ поиск
def test_search_with_confirmation_and_page_preview(world):
    service, _, api = world
    status, started = api.call("/api/search", SEARCH)
    assert status == 200
    snap = api.wait(started["job"])
    assert snap["state"] == "waiting_confirm"
    assert snap["confirm"]["resources"][0]["url"].endswith("ea888_gen3_engine.pdf")
    assert not any(u.endswith(".pdf") for u, _ in service.fake_session.calls)   # до ответа ничего не качали

    api.call(f"/api/job/{started['job']}/confirm", {"choice": "all"})
    snap = api.wait(started["job"], states=("done", "error"))
    assert snap["state"] == "done", snap
    result = snap["result"]
    by_part = {f["part"].lower(): f for f in result["findings"]}
    assert by_part["chain tensioner"]["role"] == "required"
    assert by_part["chain tensioner"]["link"].endswith("ea888_gen3_engine.pdf#page=2")
    assert by_part["chain tensioner"]["previewable"] is True
    assert result["vehicle"]["engine"] == "CJSA" and result["counts"]["required"] >= 2

    status, png = api.call(f"/api/preview/{started['job']}/{by_part['chain tensioner']['idx']}.png?t={api.token}",
                           token=False)
    assert status == 200 and png.startswith(b"\x89PNG")


def test_declined_download_fetches_nothing(world):
    service, _, api = world
    job = api.call("/api/search", SEARCH)[1]["job"]
    assert api.wait(job)["state"] == "waiting_confirm"
    snap = finish(api, job, "no")
    assert snap["state"] == "done" and snap["result"]["findings"] == []
    assert any("пропущено" in n for n in snap["result"]["notes"])
    assert not any(u.endswith(".pdf") for u, _ in service.fake_session.calls)


def test_new_search_cancels_unfinished_one(world):
    _, _, api = world
    first = api.call("/api/search", SEARCH)[1]["job"]
    assert api.wait(first)["state"] == "waiting_confirm"
    second = api.call("/api/search", SEARCH)[1]["job"]
    assert api.wait(first, states=("cancelled",))["state"] == "cancelled"
    assert api.wait(second)["state"] == "waiting_confirm"      # вторая не зависла на блокировке
    api.call(f"/api/job/{second}/cancel", {})
    assert api.wait(second, states=("cancelled",))["state"] == "cancelled"


@pytest.mark.parametrize("body, text", [
    ({"op": "что-то странное", "model": "Golf 7"}, "не распознана"),
    ({"op": "цепь грм"}, "модель или код"),
    ({"op": "цепь грм", "model": "Golf", "year": "abc"}, "Год"),
    ({"op": "цепь грм", "model": "Golf", "vin": "123"}, "17 знаков"),
])
def test_search_validation(world, body, text):
    _, _, api = world
    status, data = api.call("/api/search", body)
    assert status == 400 and text in data["error"]


def test_empty_index_gives_hint(tmp_path):
    service = build_service(tmp_path, index=False)
    server = AppServer(service, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        api = Api(server)
        assert api.call("/api/info")[1]["index"]["vwts"]["docs"] == 0
        job = api.call("/api/search", SEARCH)[1]["job"]
        snap = finish(api, job)
        assert snap["state"] == "done" and snap["result"]["findings"]       # индекс заполнился сам
        assert api.call("/api/info")[1]["index"]["vwts"]["docs"] > 0
    finally:
        server.shutdown()
        server.server_close()


def test_index_job_fills_index(tmp_path):
    service = build_service(tmp_path, index=False)
    server = AppServer(service, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        api = Api(server)
        job = api.call("/api/index", {"models": ["golf"], "engines": True})[1]["job"]
        snap = api.wait(job, states=("done", "error"))
        assert snap["state"] == "done", snap
        assert snap["result"]["summary"][0]["docs"] > 0
        assert any("golf8" in w for w in snap["result"]["summary"][0]["warnings"])   # битая страница пропущена
        assert api.call("/api/info")[1]["index"]["vwts"]["docs"] > 0
    finally:
        server.shutdown()
        server.server_close()


# ------------------------------------------------------------------- свой файл
def test_file_analysis_and_preview(world):
    _, _, api = world
    status, started = api.call("/api/file?name=manual.pdf&op=%D1%86%D0%B5%D0%BF%D1%8C+%D0%B3%D1%80%D0%BC",
                               raw=ENGINE_PDF, headers={"Content-Type": "application/pdf"})
    assert status == 200
    snap = api.wait(started["job"], states=("done", "error"))
    assert snap["state"] == "done", snap
    parts = {f["part"].lower(): f for f in snap["result"]["findings"]}
    assert parts["chain tensioner"]["local"] is True and parts["chain tensioner"]["link"] is None
    idx = parts["chain tensioner"]["idx"]
    status, png = api.call(f"/api/preview/{started['job']}/{idx}.png")
    assert status == 200 and png.startswith(b"\x89PNG")


def test_file_validation(world):
    _, _, api = world
    op = urllib.parse.quote_plus("цепь грм")
    assert api.call(f"/api/file?name=x.exe&op={op}", raw=b"data")[0] == 400
    assert api.call("/api/file?name=x.pdf&op=nonsense", raw=b"data")[0] == 400
    assert api.call(f"/api/file?name=x.txt&op={op}", raw=b"")[0] == 400


def test_text_file_has_no_preview(world):
    _, _, api = world
    text = b"Timing chain\nAlways replace chain tensioner after removing."
    job = api.call("/api/file?name=note.txt&op=timing+chain", raw=text)[1]["job"]
    snap = api.wait(job, states=("done", "error"))
    finding = snap["result"]["findings"][0]
    assert finding["previewable"] is False
    assert api.call(f"/api/preview/{job}/0.png")[0] == 404


def test_unknown_job_is_404(world):
    _, _, api = world
    assert api.call("/api/job/nope")[0] == 404


# ---------------------------------------------------------------------- запуск
def test_launcher_falls_back_to_default_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(launcher, "browser_candidates", lambda: [])
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url))
    assert launcher.open_ui("http://127.0.0.1:1/") == "browser" and opened


def test_launcher_uses_app_window_when_browser_found(monkeypatch, tmp_path):
    exe = tmp_path / "msedge.exe"
    exe.write_text("")
    started = []
    monkeypatch.setattr(launcher, "browser_candidates", lambda: [exe])
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    assert launcher.open_ui("http://127.0.0.1:1/") == "app-window"
    assert started[0][1] == "--app=http://127.0.0.1:1/"


def test_html_named_pdf_gives_clear_error(world):
    _, _, api = world
    op = urllib.parse.quote_plus("цепь грм")
    job = api.call(f"/api/file?name=fake.pdf&op={op}", raw=b"<html><body>blocked</body></html>")[1]["job"]
    snap = api.wait(job, states=("done", "error"))
    assert snap["state"] == "error" and "не PDF" in snap["error"]


# ------------------------------------------------- «как обычное приложение»
def test_health_needs_no_token_and_find_running(world):
    from vinparts.app.server import find_running
    _, server, api = world
    status, data = api.call("/health", token=False)
    assert status == 200 and data["app"] == "VinPartsHelper"
    assert find_running(server.port) is True
    assert api.call("/health", token=False, headers={"Host": "evil.example"})[0] == 403


def test_find_running_false_when_nothing_listens():
    import socket
    from vinparts.app.server import find_running
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    assert find_running(free, timeout=0.5) is False


def test_watchdog_stops_after_window_is_closed(world):
    _, server, api = world
    server.start_watchdog(idle_seconds=1.2)
    end = time.time() + 2.0
    while time.time() < end:                 # окно «открыто»: сигналы идут
        assert api.call("/api/ping")[0] == 200
        assert not server.stop_event.is_set()
        time.sleep(0.2)
    assert server.stop_event.wait(4.0)       # окно «закрыли»: сигналов нет, программа завершается


def test_gui_command_exits_by_itself_when_window_is_closed(tmp_path):
    from vinparts import cli
    results = {}

    def run():
        results["code"] = cli.main(["--data-dir", str(tmp_path), "gui", "--port", "0", "--no-open",
                                    "--auto-exit", "--idle-seconds", "1.5"])

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(10)
    assert not thread.is_alive() and results["code"] == 0


def test_exe_entry_point_survives_missing_console(monkeypatch, tmp_path, capsys):
    import sys
    import vinparts_app
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    vinparts_app._fix_streams()
    print("не падает без консоли")
    assert sys.stdout is not None


def test_second_start_reuses_running_app(world, tmp_path, capsys):
    from vinparts import cli
    _, server, _ = world
    code = cli.main(["--data-dir", str(tmp_path), "gui", "--port", str(server.port), "--no-open"])
    assert code == 0 and "уже запущен" in capsys.readouterr().out


# ------------------------------------------------- библиотека руководств
def test_library_flow_download_page_then_user_file(tmp_path):
    service = build_service(tmp_path, download_page=True)
    server = AppServer(service, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        api = Api(server)
        snap = finish(api, api.call("/api/search", SEARCH)[1]["job"])
        assert snap["state"] == "done" and snap["result"]["findings"] == []
        missing = snap["result"]["missing"]
        assert [m["filename"] for m in missing] == ["ea888_gen3_engine.pdf"]
        assert missing[0]["url"].startswith("https://vwts.ru/")

        status, body = api.call("/api/library?name=ea888_gen3_engine%20(1).pdf", raw=ENGINE_PDF)
        assert status == 200 and body["files"][0]["name"] == "ea888_gen3_engine (1).pdf"
        assert api.call("/api/info")[1]["library"]["files"][0]["size"] == len(ENGINE_PDF)

        snap = finish(api, api.call("/api/search", SEARCH)[1]["job"])
        result = snap["result"]
        assert result["missing"] == [] and result["from_library"] == ["ea888_gen3_engine.pdf"]
        assert "chain tensioner" in {f["part"] for f in result["findings"]}
        # картинка страницы строится из библиотеки, без запроса к сайту
        assert api.call(f"/api/preview/{snap['id']}/0.png")[1].startswith(b"\x89PNG")

        assert api.call("/api/library/delete", {"name": "ea888_gen3_engine (1).pdf"})[1]["files"] == []
        assert api.call("/api/library/delete", {"name": "nope.pdf"})[0] == 404
    finally:
        server.shutdown()
        server.server_close()


def test_library_rejects_html_page_and_needs_token(world):
    _, _, api = world
    status, body = api.call("/api/library?name=a.pdf", raw=b"<html>countdown</html>")
    assert status == 400 and "страница ожидания" in body["error"]
    assert api.call("/api/library", token=False)[0] == 403


# ------------------------------------------------- язык и «все модели»
def test_notes_follow_selected_language(tmp_path):
    service = build_service(tmp_path, index=False)
    server = AppServer(service, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        api = Api(server)
        nothing = {"op": "цепь грм", "model": "Zzz Unknown"}
        snap = api.wait(api.call("/api/search", {**nothing, "lang": "en"})[1]["job"], states=("done", "error"))
        assert any("no matching sections" in n for n in snap["result"]["notes"])
        snap = api.wait(api.call("/api/search", nothing)[1]["job"], states=("done", "error"))
        assert any("подходящих разделов" in n for n in snap["result"]["notes"])
        status, body = api.call("/api/search", {"op": "zzz", "model": "x", "lang": "en"})
        assert status == 400 and "not recognized" in body["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_index_all_models_visits_every_model_page(tmp_path):
    service = build_service(tmp_path, index=False)
    server = AppServer(service, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        api = Api(server)
        job = api.call("/api/index", {"all_models": True, "engines": False})[1]["job"]
        snap = api.wait(job, states=("done", "error"))
        assert snap["state"] == "done", snap
        info = api.call("/api/info")[1]
        assert info["index"]["vwts"]["nav"] >= 3
        _, full = api.call(f"/api/job/{job}")
        steps = [line for line in full["log"] if line.startswith("[") and "/" in line.split("]")[0]]
        assert len(steps) >= 3                                          # ход работы виден по страницам
        requested = [u for u, _ in service.fake_session.calls if u.endswith(".html")]
        assert len(set(requested)) >= 4                                 # главная + все страницы моделей
    finally:
        server.shutdown()
        server.server_close()
