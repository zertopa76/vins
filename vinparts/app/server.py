"""Локальный HTTP-сервер приложения.

Безопасность: слушает только 127.0.0.1; страница получает случайный токен, без которого API
не отвечает; проверяются заголовки Host и Origin (защита от чужих сайтов, открытых в браузере).
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .service import MAX_UPLOAD_BYTES, AppService, ServiceError

STATIC = Path(__file__).parent / "static"


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, service: AppService, port: int = 8765, host: str = "127.0.0.1"):
        self.service = service
        self.token = secrets.token_urlsafe(24)
        self.stop_event = threading.Event()
        self.on_focus = None            # вызывается, когда второй запуск просит показать окно
        self.window_error: str | None = None
        last_error: OSError | None = None
        for candidate in ([port] if port == 0 else [port, 0]):   # порт занят — берём любой свободный
            try:
                super().__init__((host, candidate), Handler)
                break
            except OSError as exc:
                last_error = exc
        else:
            raise last_error  # type: ignore[misc]
        self.port = self.server_address[1]
        self.last_seen = time.monotonic()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def touch(self) -> None:
        self.last_seen = time.monotonic()

    def start_watchdog(self, idle_seconds: float = 90.0, tick: float = 5.0) -> threading.Thread:
        """Останавливает программу, когда окно закрыто: страница шлёт сигнал раз в несколько секунд.
        Скачок времени (сон компьютера) не считается за закрытое окно."""
        tick = min(tick, idle_seconds / 3)

        def loop():
            previous = time.monotonic()
            while not self.stop_event.wait(tick):
                now = time.monotonic()
                if now - previous > tick * 4:      # компьютер спал: страница ещё не успела отозваться
                    self.last_seen = now
                previous = now
                if now - self.last_seen > idle_seconds:
                    self.stop_event.set()
                    return

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        return thread


class Handler(BaseHTTPRequestHandler):
    server: AppServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002 - тишина в консоли
        pass

    # ------------------------------------------------------------- вспомогательное
    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        return host in (f"127.0.0.1:{self.server.port}", f"localhost:{self.server.port}")

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return origin.lower() in (f"http://127.0.0.1:{self.server.port}", f"http://localhost:{self.server.port}")

    def _token_ok(self, query: dict) -> bool:
        supplied = self.headers.get("X-Token") or (query.get("t") or [""])[0]
        return secrets.compare_digest(supplied, self.server.token)

    def _body(self, limit: int) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            raise ServiceError("Слишком большой файл.", 413)
        return self.rfile.read(length) if length else b""

    def _json_body(self) -> dict:
        raw = self._body(1024 * 1024)
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except ValueError as exc:
            raise ServiceError("Неверный формат запроса.") from exc
        return data if isinstance(data, dict) else {}

    # ---------------------------------------------------------------------- GET
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._host_ok():
            return self._json(403, {"error": "Недопустимый адрес."})
        path = parsed.path
        try:
            if path == "/":
                self.server.touch()
                html = (STATIC / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", self.server.token)
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8",
                                  {"Content-Security-Policy":
                                   "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                                   "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
                                   "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"})
            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if path == "/health":          # без токена: так второй запуск узнаёт, что программа уже работает
                return self._json(200, {"app": "VinPartsHelper"})
            if not self._token_ok(query):
                return self._json(403, {"error": "Нет доступа."})
            self.server.touch()
            svc = self.server.service
            if path == "/api/ping":
                return self._json(200, {"ok": True})
            if path == "/api/info":
                return self._json(200, svc.info())
            if path == "/api/library":
                return self._json(200, svc.library_info())
            if path.startswith("/api/job/"):
                job = svc.job(unquote(path.split("/")[3]))
                return self._json(200, job.snapshot(int((query.get("since") or ["0"])[0] or 0)))
            if path.startswith("/api/preview/"):
                _, _, _, job_id, name = path.split("/", 4)
                png = svc.render_preview(unquote(job_id), int(name.removesuffix(".png")))
                return self._send(200, png, "image/png")
            return self._json(404, {"error": "Не найдено."})
        except ServiceError as exc:
            return self._json(exc.status, {"error": str(exc)})
        except (ValueError, IndexError):
            return self._json(400, {"error": "Неверный запрос."})

    # --------------------------------------------------------------------- POST
    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not (self._host_ok() and self._origin_ok() and self._token_ok(query)):
            return self._json(403, {"error": "Нет доступа."})
        self.server.touch()
        svc = self.server.service
        path = parsed.path
        try:
            if path == "/api/vin":
                return self._json(200, svc.decode_vin(str(self._json_body().get("vin", ""))))
            if path == "/api/search":
                return self._json(200, {"job": svc.start_search(self._json_body()).id})
            if path == "/api/index":
                body = self._json_body()
                models = body.get("models") or []
                if isinstance(models, str):
                    models = [models]
                job = svc.start_index(models, bool(body.get("engines", True)), bool(body.get("all_models")),
                                      str(body.get("lang") or "ru"))
                return self._json(200, {"job": job.id})
            if path == "/api/file":
                data = self._body(MAX_UPLOAD_BYTES)
                job = svc.start_file((query.get("name") or [""])[0], data, (query.get("op") or [""])[0])
                return self._json(200, {"job": job.id})
            if path == "/api/library":
                data = self._body(MAX_UPLOAD_BYTES)
                return self._json(200, svc.library_add((query.get("name") or [""])[0], data))
            if path == "/api/library/delete":
                return self._json(200, svc.library_remove(str(self._json_body().get("name", ""))))
            if path.startswith("/api/job/") and path.endswith("/confirm"):
                svc.job(unquote(path.split("/")[3])).answer(str(self._json_body().get("choice", "no")))
                return self._json(200, {"ok": True})
            if path.startswith("/api/job/") and path.endswith("/cancel"):
                svc.job(unquote(path.split("/")[3])).cancel()
                return self._json(200, {"ok": True})
            if path == "/api/focus":
                callback = self.server.on_focus
                return self._json(200, {"focused": bool(callback and callback())})
            if path == "/api/shutdown":
                self.server.stop_event.set()      # сначала сигнал, потом ответ: иначе клиент может опередить
                self._json(200, {"ok": True})
                return None
            return self._json(404, {"error": "Не найдено."})
        except ServiceError as exc:
            return self._json(exc.status, {"error": str(exc)})
        except (ValueError, IndexError):
            return self._json(400, {"error": "Неверный запрос."})


def find_running(port: int, timeout: float = 1.5) -> bool:
    """Есть ли на этом порту уже запущенная VinPartsHelper."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")).get("app") == "VinPartsHelper"
    except (OSError, ValueError):
        return False


def focus_running(port: int, timeout: float = 3.0) -> bool:
    """Просит уже работающую программу показать своё окно. True, если у неё есть окно."""
    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(base + "/", timeout=timeout) as resp:
            match = re.search(r'name="token" content="([^"]+)"', resp.read().decode("utf-8"))
        if not match:
            return False
        request = urllib.request.Request(base + "/api/focus", data=b"{}", method="POST",
                                         headers={"X-Token": match.group(1), "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return bool(json.loads(resp.read().decode("utf-8")).get("focused"))
    except (OSError, ValueError):
        return False


def serve(service: AppService, port: int = 8765) -> AppServer:
    """Запускает сервер в фоновом потоке и возвращает его (остановка: server.shutdown())."""
    server = AppServer(service, port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
