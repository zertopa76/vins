"""Вежливый HTTP-клиент.

Что он гарантирует:
  * ходит только на разрешённые домены (в том числе при редиректах);
  * перед каждым адресом проверяет robots.txt (если не прочитался — считает «всё запрещено»);
  * делает паузу между запросами к одному сайту;
  * хранит ответы в локальном кэше и перепроверяет их через ETag / Last-Modified;
  * не повторяет запрос при 429/503, а честно сообщает об этом;
  * ограничивает размер скачиваемого файла.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from . import config
from .robots import RobotsRules


class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class RobotsDenied(HttpError):
    pass


class HostNotAllowed(HttpError):
    pass


class TooLarge(HttpError):
    pass


@dataclass
class Fetched:
    url: str
    status: int
    content: bytes
    content_type: str
    from_cache: bool

    def text(self) -> str:
        charset = None
        if "charset=" in self.content_type.lower():
            charset = self.content_type.lower().split("charset=")[1].split(";")[0].strip()
        for enc in ([charset] if charset else []) + ["utf-8", "cp1251"]:
            try:
                return self.content.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return self.content.decode("utf-8", errors="replace")


class PoliteClient:
    def __init__(
        self,
        cache_dir: str | Path,
        allowed_hosts: set[str] | frozenset[str],
        *,
        session=None,
        min_delay: float = config.DEFAULT_DELAY_SECONDS,
        ttl_hours: float = config.DEFAULT_TTL_HOURS,
        use_cache: bool = True,
        max_bytes: int = config.DEFAULT_MAX_BYTES,
        user_agent: str | None = None,
        timeout: float = 30,
        sleep=time.sleep,
        clock=time.monotonic,
        wall=time.time,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.allowed_hosts = frozenset(h.lower() for h in allowed_hosts)
        self.session = session or requests.Session()
        self.min_delay = min_delay
        self.ttl_seconds = ttl_hours * 3600
        self.use_cache = use_cache
        self.max_bytes = max_bytes
        self.ua = user_agent or config.user_agent()
        self.timeout = timeout
        self._sleep, self._clock, self._wall = sleep, clock, wall
        self._robots: dict[str, RobotsRules] = {}
        self._last_request: dict[str, float] = {}
        self.requests_made = 0

    # ---------------------------------------------------------------- проверки
    def _check_host(self, url: str):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise HostNotAllowed(f"Неподдерживаемый адрес: {url}")
        if parsed.hostname.lower() not in self.allowed_hosts:
            raise HostNotAllowed(f"Домен не в списке разрешённых: {parsed.hostname}")
        return parsed

    def _wait(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            remaining = self.min_delay - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)

    def _raw_get(self, url: str, headers: dict):
        host = urlparse(url).hostname or ""
        self._wait(host)
        try:
            return self.session.get(
                url, headers=headers, timeout=self.timeout, stream=True, allow_redirects=False
            )
        finally:
            self._last_request[host] = self._clock()
            self.requests_made += 1

    def _rules_for(self, parsed) -> RobotsRules:
        key = f"{parsed.scheme}://{parsed.netloc}"
        if key in self._robots:
            return self._robots[key]
        url = key + "/robots.txt"
        rules: RobotsRules
        try:
            final, resp = self._request(url, {"User-Agent": self.ua}, check_robots=False)
            status = resp.status_code
            if status == 200:
                body = self._read_body(resp, 512 * 1024)
                rules = RobotsRules.from_text(body.decode("utf-8", errors="replace"))
            else:
                resp.close()
                # 404/410 = ограничений нет; любая другая ошибка = осторожно, считаем всё закрытым
                rules = RobotsRules.allow_all() if status in (404, 410) else RobotsRules.disallow_all()
        except (HttpError, requests.RequestException):
            rules = RobotsRules.disallow_all()
        self._robots[key] = rules
        return rules

    def is_allowed(self, url: str) -> bool:
        parsed = self._check_host(url)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        return self._rules_for(parsed).is_allowed(self.ua, path)

    # ------------------------------------------------------------------ запросы
    def _request(self, url: str, headers: dict, check_robots: bool = True):
        for _ in range(4):
            parsed = self._check_host(url)
            if check_robots and not self.is_allowed(url):
                raise RobotsDenied(f"robots.txt запрещает загрузку: {url}")
            resp = self._raw_get(url, headers)
            location = resp.headers.get("Location")
            if resp.status_code in (301, 302, 303, 307, 308) and location:
                resp.close()
                url = urljoin(url, location)
                continue
            return url, resp
        raise HttpError(f"Слишком много перенаправлений: {url}")

    @staticmethod
    def _read_body(resp, limit: int) -> bytes:
        length = resp.headers.get("Content-Length")
        if length and str(length).isdigit() and int(length) > limit:
            resp.close()
            raise TooLarge(f"Файл больше лимита ({int(length) / 1e6:.1f} МБ > {limit / 1e6:.0f} МБ)")
        buf = bytearray()
        try:
            for chunk in resp.iter_content(65536):
                buf.extend(chunk)
                if len(buf) > limit:
                    resp.close()
                    raise TooLarge(f"Файл больше лимита ({limit / 1e6:.0f} МБ)")
        except requests.RequestException as exc:
            resp.close()
            raise HttpError(f"Загрузка оборвалась: получено {len(buf) / 1e6:.1f} МБ ({exc.__class__.__name__}). "
                            "Попробуйте ещё раз.") from exc
        # Без сжатия Content-Length точен: меньше значит файл пришёл не целиком (в кэш такое не кладём).
        if (length and str(length).isdigit() and not resp.headers.get("Content-Encoding")
                and len(buf) != int(length)):
            raise HttpError(f"Файл скачан не полностью: получено {len(buf)} из {int(length)} байт. "
                            "Попробуйте ещё раз.")
        return bytes(buf)

    # --------------------------------------------------------------------- кэш
    def _paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{key}.bin", self.cache_dir / f"{key}.json"

    def _load_cached(self, url: str):
        body_path, meta_path = self._paths(url)
        if not (body_path.exists() and meta_path.exists()):
            return None, None
        try:
            return body_path.read_bytes(), json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, None

    def _save_cached(self, url: str, body: bytes, meta: dict) -> None:
        body_path, meta_path = self._paths(url)
        body_path.write_bytes(body)
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

    def forget(self, url: str) -> None:
        """Удаляет ответ из кэша (например, если там оказался повреждённый файл)."""
        for path in self._paths(url):
            try:
                path.unlink()
            except OSError:
                pass

    # Память о неудачах: если сайт вернул страницу вместо файла, несколько часов не просим его снова.
    def _failure_path(self, url: str) -> Path:
        return self.cache_dir.parent / "debug" / f"{hashlib.sha1(url.encode()).hexdigest()[:8]}.bad"

    def record_failure(self, url: str, note: str) -> None:
        path = self._failure_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"at": self._wall(), "note": note}, ensure_ascii=False), encoding="utf-8")

    def recent_failure(self, url: str, hours: float = 6.0) -> str | None:
        try:
            data = json.loads(self._failure_path(url).read_text(encoding="utf-8"))
            age = self._wall() - float(data["at"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if age >= hours * 3600:
            return None
        left = max(1, round(hours - age / 3600))
        return f"{data['note']} Повторный запрос отложен: сайт недавно уже ответил так (следующая попытка примерно через {left} ч)."

    def save_debug(self, url: str, body: bytes, limit: int = 256 * 1024) -> str:
        """Сохраняет начало ответа для разбора неполадок и возвращает путь к файлу."""
        folder = self.cache_dir.parent / "debug"
        folder.mkdir(parents=True, exist_ok=True)
        name = Path(urlparse(url).path).name or "response"
        path = folder / f"{hashlib.sha1(url.encode()).hexdigest()[:8]}_{name}.sample"
        path.write_bytes(body[:limit])
        return str(path)

    # -------------------------------------------------------------------- GET
    def get(self, url: str, *, max_bytes: int | None = None) -> Fetched:
        self._check_host(url)
        limit = max_bytes or self.max_bytes
        cached_body, meta = (self._load_cached(url) if self.use_cache else (None, None))

        if cached_body is not None and meta:
            if self._wall() - meta.get("fetched_at", 0) < self.ttl_seconds:
                return Fetched(url, 200, cached_body, meta.get("content_type", ""), True)

        wants_pdf = urlparse(url).path.lower().endswith(".pdf")
        headers = {
            "User-Agent": self.ua,
            "Accept": "application/pdf,*/*;q=0.5" if wants_pdf else "text/html,application/pdf;q=0.9,*/*;q=0.5",
        }
        if cached_body is not None and meta:
            if meta.get("etag"):
                headers["If-None-Match"] = meta["etag"]
            if meta.get("last_modified"):
                headers["If-Modified-Since"] = meta["last_modified"]

        final_url, resp = self._request(url, headers)
        status = resp.status_code
        if status == 304 and cached_body is not None:
            resp.close()
            meta["fetched_at"] = self._wall()
            self._save_cached(url, cached_body, meta)
            return Fetched(url, 200, cached_body, meta.get("content_type", ""), True)
        if status != 200:
            retry = resp.headers.get("Retry-After")
            resp.close()
            hint = f" (сервер просит подождать: Retry-After={retry})" if retry else ""
            raise HttpError(f"Сервер ответил {status} на {url}{hint}", status=status)

        body = self._read_body(resp, limit)
        content_type = resp.headers.get("Content-Type", "")
        if self.use_cache:
            self._save_cached(url, body, {
                "url": final_url,
                "etag": resp.headers.get("ETag"),
                "last_modified": resp.headers.get("Last-Modified"),
                "content_type": content_type,
                "fetched_at": self._wall(),
            })
        return Fetched(final_url, 200, body, content_type, False)
