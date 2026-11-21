"""Связывает всё вместе: машина + операция → источники → текст → найденные детали."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .extract import ROLE_ORDER, analyze
from .http import HttpError
from .i18n import tr
from .library import Library, basename_of
from .models import DocRef, Finding, Resource, Vehicle
from .operations import Operation
from .readers import DocumentError, read_pdf_bytes


@dataclass
class QueryResult:
    operation: Operation
    docs: list[DocRef] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # файлы, которые не удалось получить автоматически: человек может скачать их сам и положить в библиотеку
    missing: list[dict] = field(default_factory=list)
    from_library: list[str] = field(default_factory=list)


def _is_pdf(res: Resource) -> bool:
    return res.kind == "pdf" or res.url.split("#")[0].lower().endswith(".pdf")


def run_query(
    adapters,
    store,
    client,
    vehicle: Vehicle,
    op: Operation,
    *,
    max_docs: int = 2,
    max_resources: int = 3,
    confirm: Callable[[DocRef, list[Resource]], bool] | None = None,
    library: Library | None = None,
    progress: Callable[[str], None] = lambda msg: None,
    lang: str = "ru",
    auto_index: bool = True,
) -> QueryResult:
    result = QueryResult(operation=op)
    for adapter in adapters:
        if not adapter.supports(vehicle):
            continue
        if auto_index and client is not None:
            try:
                adapter.ensure_indexed(client, store, vehicle, progress)
            except HttpError as exc:
                result.notes.append(tr(lang, "index_failed", src=adapter.name, err=exc))
        docs = adapter.find_documents(store, vehicle, op)[:max_docs]
        if not docs:
            result.notes.append(tr(lang, "no_docs", src=adapter.name))
            continue
        for doc in docs:
            result.docs.append(doc)
            try:
                resources = adapter.list_resources(client, doc, limit=max_resources)
            except HttpError as exc:
                result.notes.append(f"[{adapter.name}] {doc.title}: {exc}")
                continue
            local = {res.url: library.read(res.url) for res in resources
                     if library is not None and _is_pdf(res)}
            local = {url: data for url, data in local.items() if data}
            to_download = [res for res in resources if res.url not in local]
            # спрашиваем разрешение только на то, что действительно будет скачано с сайта
            if confirm and to_download and not confirm(doc, to_download):
                if not local:
                    result.notes.append(tr(lang, "skipped", src=adapter.name, doc=doc.title))
                    continue
                resources = [res for res in resources if res.url in local]
            for res in resources:
                if res.url in local:
                    name = basename_of(res.url)
                    progress(f"читаю {name} из вашей библиотеки")
                    try:
                        parts = read_pdf_bytes(local[res.url], res.url, res.title)
                    except DocumentError as exc:
                        result.notes.append(tr(lang, "lib_unreadable", src=adapter.name, name=name, err=exc))
                        continue
                    result.from_library.append(name)
                    if not parts:
                        result.notes.append(tr(lang, "no_text", src=adapter.name, name=name))
                        continue
                    result.findings += analyze(parts, op)
                    continue
                progress(f"читаю {res.url}")
                try:
                    parts = adapter.read_resource(client, res)
                except DocumentError as exc:
                    if _is_pdf(res):
                        result.missing.append({
                            "url": res.url.split("#")[0], "title": res.title or basename_of(res.url),
                            "filename": basename_of(res.url), "doc_title": doc.title,
                            "page_url": doc.page_url, "reason": str(exc)})
                    else:
                        result.notes.append(f"[{adapter.name}] {res.url}: {exc}")
                    continue
                except HttpError as exc:
                    result.notes.append(f"[{adapter.name}] {res.url}: {exc}")
                    continue
                except Exception as exc:  # повреждённый PDF и т.п. не должен ронять весь запрос
                    result.notes.append(tr(lang, "cant_read", src=adapter.name, name=res.url, err=exc))
                    continue
                if not parts:
                    result.notes.append(tr(lang, "no_text", src=adapter.name, name=res.url))
                    continue
                result.findings += analyze(parts, op)

    result.missing = list({m["url"]: m for m in result.missing}.values())
    result.from_library = list(dict.fromkeys(result.from_library))

    # объединяем одинаковые детали из разных документов
    merged: dict[str, Finding] = {}
    for f in result.findings:
        key = f.part.lower()
        if key not in merged or ROLE_ORDER[f.role] < ROLE_ORDER[merged[key].role]:
            merged[key] = f
        else:
            merged[key].mentions += f.mentions
    result.findings = sorted(merged.values(), key=lambda f: (ROLE_ORDER[f.role], -f.mentions, f.part.lower()))
    return result
