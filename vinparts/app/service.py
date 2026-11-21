"""Логика приложения без привязки к окну/HTTP: фоновые задачи, подтверждения, картинки.

Интерфейс (браузерное окно) только вызывает эти методы, поэтому их можно тестировать отдельно.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

from .. import config, preview
from ..extract import ROLE_LABEL_RU, ROLE_ORDER, analyze
from ..http import HttpError, PoliteClient
from ..i18n import norm_lang, tr
from ..library import Library, LibraryError
from ..models import DocRef, Finding, Resource, Vehicle
from ..operations import OPERATIONS, match_operation
from ..pipeline import run_query
from ..readers import DocumentError, decode_bytes, read_html_text, read_pdf_bytes
from ..sources import all_adapters, allowed_hosts
from ..store import Store
from ..vin import decode

MAX_UPLOAD_BYTES = 80 * 1024 * 1024
CONFIRM_TIMEOUT_SECONDS = 600
KEEP_JOBS = 30
LOCAL_PREFIX = "local:"


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class JobCancelled(Exception):
    pass


class Job:
    """Фоновая задача: поиск, обновление индекса или разбор файла."""

    def __init__(self, kind: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.state = "running"          # running / waiting_confirm / done / error / cancelled
        self.log: list[str] = []
        self.confirm: dict | None = None
        self.result: dict | None = None
        self.error: str | None = None
        self.findings: list[Finding] = []
        self.blobs: dict[str, bytes] = {}       # загруженные пользователем файлы по их «адресу»
        self.previews: dict[int, bytes] = {}
        self.created = time.time()
        self.cancelled = False
        self.auto_yes = False
        self._lock = threading.Lock()
        self._answer_event = threading.Event()
        self._answer = False

    def say(self, message: str) -> None:
        with self._lock:
            self.log.append(message)
        if self.cancelled:
            raise JobCancelled()

    def ask_confirm(self, doc: DocRef, resources: list[Resource]) -> bool:
        if self.auto_yes:
            return True
        if self.cancelled:
            raise JobCancelled()
        with self._lock:
            self.confirm = {
                "doc": {"title": doc.title, "url": doc.url, "kind": doc.kind, "source": doc.source},
                "resources": [{"url": r.url, "kind": r.kind, "title": r.title} for r in resources],
            }
            self.state = "waiting_confirm"
            self._answer_event.clear()
        answered = self._answer_event.wait(CONFIRM_TIMEOUT_SECONDS)
        with self._lock:
            self.confirm = None
            if self.state == "waiting_confirm":
                self.state = "running"
        if self.cancelled:
            raise JobCancelled()
        return bool(answered and self._answer)

    def answer(self, choice: str) -> None:
        if choice == "all":
            self.auto_yes = True
        self._answer = choice in ("yes", "all")
        self._answer_event.set()

    def cancel(self) -> None:
        self.cancelled = True
        self._answer_event.set()

    def snapshot(self, since: int = 0) -> dict:
        with self._lock:
            return {
                "id": self.id, "kind": self.kind, "state": self.state,
                "log": self.log[since:], "next": len(self.log),
                "confirm": self.confirm, "result": self.result, "error": self.error,
            }


def _is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def _link_for(f: Finding) -> str | None:
    """Ссылка, которую можно открыть кликом. Только http(s); у загруженного файла ссылки нет."""
    parsed = urlparse(f.source_url)
    if parsed.scheme not in ("http", "https"):
        return None
    if f.page and _is_pdf_url(f.source_url) and not parsed.fragment:
        return f"{f.source_url}#page={f.page}"
    return f.source_url


def finding_to_dict(i: int, f: Finding) -> dict:
    return {
        "idx": i, "part": f.part, "part_ru": f.part_ru, "role": f.role,
        "role_label_ru": ROLE_LABEL_RU[f.role], "quote": f.quote,
        "source_title": f.source_title, "source_url": f.source_url, "link": _link_for(f),
        "local": f.source_url.startswith(LOCAL_PREFIX),
        "page": f.page, "mentions": f.mentions,
        "previewable": bool(f.page) and preview.available(),
    }


def _result_dict(job: Job, vehicle: Vehicle, op, findings: list[Finding], docs: list[DocRef],
                 notes: list[str], requests_made: int, missing: list[dict] | None = None,
                 from_library: list[str] | None = None) -> dict:
    counts = {role: 0 for role in ROLE_ORDER}
    for f in findings:
        counts[f.role] += 1
    return {
        "vehicle": {"make": vehicle.make, "model": vehicle.model, "year": vehicle.year,
                    "engine": vehicle.engine_code, "vin": vehicle.vin},
        "operation": {"id": op.id, "title_ru": op.title_ru},
        "findings": [finding_to_dict(i, f) for i, f in enumerate(findings)],
        "counts": counts,
        "docs": [{"title": d.title, "url": d.url, "kind": d.kind, "source": d.source} for d in docs],
        "notes": notes,
        "requests_made": requests_made,
        "missing": missing or [],
        "from_library": from_library or [],
    }


class AppService:
    def __init__(self, data_dir: str | Path | None = None, adapters=None, client: PoliteClient | None = None,
                 delay: float = config.DEFAULT_DELAY_SECONDS, use_cache: bool = True):
        self.data_dir = config.data_dir(data_dir)
        self.adapters = adapters if adapters is not None else all_adapters()
        self.client = client or PoliteClient(self.data_dir / "cache", allowed_hosts(self.adapters),
                                             min_delay=delay, use_cache=use_cache)
        self.library = Library(self.data_dir / "library")
        self.net_lock = threading.Lock()     # к сайтам ходим по одному запросу за раз
        self.jobs: dict[str, Job] = {}
        self._jobs_lock = threading.Lock()

    # ------------------------------------------------------------------ данные
    def _store(self) -> Store:
        return Store(self.data_dir / "index.sqlite")

    def info(self) -> dict:
        store = self._store()
        try:
            models: set[str] = set()
            engines: set[str] = set()
            index = {}
            for adapter in self.adapters:
                docs, nav = store.counts(adapter.name)
                index[adapter.name] = {"docs": docs, "nav": nav}
                models |= {label.strip(" ➤") for label, _ in store.nav(adapter.name)}
                for d in store.docs(adapter.name):
                    engines |= set(d.engine_codes)
        finally:
            store.close()
        return {
            "version": config.APP_VERSION,
            "user_agent": self.client.ua,
            "contact_set": "contact:" in self.client.ua,
            "data_dir": str(self.data_dir),
            "delay": self.client.min_delay,
            "operations": [{"id": o.id, "title_ru": o.title_ru} for o in OPERATIONS],
            "models": sorted(models, key=str.lower),
            "engines": sorted(engines),
            "index": index,
            "sources": [{"name": a.name, "notes": a.terms.notes, "allows_llm": a.terms.allows_llm,
                         "hosts": sorted(a.hosts)} for a in self.adapters],
            "preview": preview.available(),
            "library": self.library_info(),
        }

    # ------------------------------------------------------------ библиотека руководств
    def library_info(self) -> dict:
        files = self.library.list()
        return {"folder": str(self.library.folder),
                "files": [{"name": f.name, "size": f.size, "added": f.added} for f in files]}

    def library_add(self, filename: str, data: bytes) -> dict:
        if len(data) > MAX_UPLOAD_BYTES:
            raise ServiceError("Файл больше 80 МБ.", 413)
        try:
            added = self.library.add(filename, data)
        except LibraryError as exc:
            raise ServiceError(str(exc)) from exc
        return {"added": {"name": added.name, "size": added.size}, **self.library_info()}

    def library_remove(self, filename: str) -> dict:
        if not self.library.remove(filename):
            raise ServiceError("Такого файла в библиотеке нет.", 404)
        return self.library_info()

    @staticmethod
    def decode_vin(vin: str) -> dict:
        info = decode(vin or "")
        return {"vin": info.vin, "valid": info.valid_format, "make": info.make, "year": info.year,
                "note": info.note}

    # ------------------------------------------------------------------ задачи
    def _register(self, job: Job) -> Job:
        with self._jobs_lock:
            # один пользователь: новый запрос того же вида отменяет прежний, который ещё не закончен
            for old in self.jobs.values():
                if old.kind == job.kind and old.state in ("running", "waiting_confirm"):
                    old.cancel()
            self.jobs[job.id] = job
            for old in sorted(self.jobs.values(), key=lambda j: j.created)[:-KEEP_JOBS]:
                self.jobs.pop(old.id, None)
        return job

    def job(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise ServiceError("Задача не найдена (возможно, программа была перезапущена).", 404)
        return job

    @contextmanager
    def _network(self, job: Job):
        """К сайтам ходим по одной задаче за раз; ожидание видно в журнале, а отмена работает."""
        if not self.net_lock.acquire(blocking=False):
            job.say("Жду, пока закончится предыдущая задача.")
            while not self.net_lock.acquire(timeout=0.5):
                if job.cancelled:
                    raise JobCancelled()
        try:
            if job.cancelled:
                raise JobCancelled()
            yield
        finally:
            self.net_lock.release()

    @staticmethod
    def _run(job: Job, work) -> None:
        def target():
            try:
                work()
                if job.state != "error":
                    job.state = "done"
            except JobCancelled:
                job.state = "cancelled"
            except (HttpError, DocumentError) as exc:
                job.error, job.state = str(exc), "error"
            except Exception as exc:  # noqa: BLE001 - ошибка показывается в окне, а не роняет программу
                traceback.print_exc()
                job.error, job.state = f"Внутренняя ошибка: {exc}", "error"

        threading.Thread(target=target, daemon=True).start()

    def start_search(self, params: dict) -> Job:
        lang = norm_lang(params.get("lang"))
        op = match_operation(str(params.get("op") or ""))
        if op is None:
            raise ServiceError(tr(lang, "op_unknown"))
        vehicle = Vehicle(model=(params.get("model") or "").strip() or None,
                          engine_code=(params.get("engine") or "").strip().upper() or None)
        year = str(params.get("year") or "").strip()
        if year:
            if not year.isdigit() or not 1950 <= int(year) <= 2100:
                raise ServiceError(tr(lang, "year_bad"))
            vehicle.year = int(year)
        vin = (params.get("vin") or "").strip()
        if vin:
            info = decode(vin)
            if not info.valid_format:
                raise ServiceError(info.note)
            vehicle.vin, vehicle.make = info.vin, info.make
            vehicle.year = vehicle.year or info.year
        if not (vehicle.model or vehicle.engine_code):
            raise ServiceError(tr(lang, "need_model"))

        job = self._register(Job("search"))

        def work():
            with self._network(job):
                before = self.client.requests_made
                store = self._store()
                try:
                    result = run_query(self.adapters, store, self.client, vehicle, op,
                                       max_docs=int(params.get("max_docs") or 2),
                                       max_resources=int(params.get("max_resources") or 3),
                                       confirm=job.ask_confirm, library=self.library, progress=job.say,
                                       lang=lang)
                finally:
                    store.close()
            job.findings = result.findings
            job.result = _result_dict(job, vehicle, op, result.findings, result.docs, result.notes,
                                      self.client.requests_made - before, result.missing,
                                      result.from_library)

        job.say(tr(lang, "request_taken"))
        self._run(job, work)
        return job

    def start_index(self, models: list[str] | None, include_engines: bool, all_models: bool = False,
                    lang: str = "ru") -> Job:
        lang = norm_lang(lang)
        models = [m.strip() for m in (models or []) if m and m.strip()]
        job = self._register(Job("index"))

        def work():
            with self._network(job):
                before = self.client.requests_made
                store = self._store()
                try:
                    summary = []
                    for adapter in self.adapters:
                        job.say(tr(lang, "index_start", src=adapter.name, delay=self.client.min_delay))
                        found = adapter.refresh_index(self.client, store, models or None, include_engines,
                                                      all_models, progress=job.say)
                        docs, nav = store.counts(adapter.name)
                        warnings = list(getattr(adapter, "last_warnings", []))
                        summary.append({"source": adapter.name, "found": found, "docs": docs, "nav": nav,
                                        "warnings": warnings})
                finally:
                    store.close()
            job.result = {"summary": summary, "requests_made": self.client.requests_made - before}

        self._run(job, work)
        return job

    def start_file(self, filename: str, data: bytes, op_text: str) -> Job:
        op = match_operation(op_text or "")
        if op is None:
            raise ServiceError("Операция не распознана. Выберите её из списка.")
        if not data:
            raise ServiceError("Файл пустой.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise ServiceError("Файл больше 80 МБ.", 413)
        name = Path(filename or "file").name
        suffix = Path(name).suffix.lower()
        if suffix not in (".pdf", ".html", ".htm", ".txt", ".md"):
            raise ServiceError("Поддерживаются файлы PDF, HTML и TXT.")
        url = f"{LOCAL_PREFIX}{name}"
        job = self._register(Job("file"))

        def work():
            job.say(f"Читаю файл {name}.")
            if suffix == ".pdf":
                job.blobs[url] = data
                parts = read_pdf_bytes(data, url, name)
            elif suffix in (".html", ".htm"):
                parts = read_html_text(decode_bytes(data), url, name)
            else:
                from ..models import TextPart
                text = decode_bytes(data)
                parts = [TextPart(text, None, url, name)] if text.strip() else []
            notes = []
            if not parts:
                notes.append("В файле нет текста. Если это скан, программа его прочитать не может.")
            findings = analyze(parts, op) if parts else []
            job.findings = findings
            job.result = _result_dict(job, Vehicle(), op, findings, [], notes, 0)

        self._run(job, work)
        return job

    # -------------------------------------------------------------- картинки
    def render_preview(self, job_id: str, index: int) -> bytes:
        job = self.job(job_id)
        if not preview.available():
            raise ServiceError("Для картинок страниц нужен пакет pypdfium2 (pip install pypdfium2).", 501)
        if not 0 <= index < len(job.findings):
            raise ServiceError("Такой детали нет.", 404)
        if index in job.previews:
            return job.previews[index]
        f = job.findings[index]
        if not f.page:
            raise ServiceError("У этого источника нет страниц.", 404)
        data = job.blobs.get(f.source_url) or self.library.read(f.source_url)
        if data is None:
            if f.source_url.startswith(LOCAL_PREFIX):
                raise ServiceError("Файл больше недоступен: загрузите его снова.", 404)
            with self.net_lock:       # из кэша; если кэш устарел, запрос будет вежливым
                try:
                    data = self.client.get(f.source_url.split("#")[0]).content
                except HttpError as exc:
                    raise ServiceError(str(exc), 502) from exc
        if not data.startswith(b"%PDF"):
            raise ServiceError("Источник не является PDF.", 404)
        png = preview.render_page(data, f.page, f.quote, f.part)
        if png is None:
            raise ServiceError("Не удалось отобразить страницу.", 404)
        job.previews[index] = png
        return png
