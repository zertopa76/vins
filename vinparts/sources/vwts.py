"""Адаптер vwts.ru (Volkswagen Technical Site).

ВАЖНО: разбор написан по структуре ГЛАВНОЙ страницы (ссылки вида
`vw_golf7_5g.html#vw-golf-7-maintenance-eng`, `petrol-engine-...html#engine-czea-...-eng`,
строки «Engine code: ...»). Внутренние страницы моделей автор кода не видел, поэтому поиск файлов
внутри раздела (list_resources) сделан «с запасом» и должен быть проверен командой `recon`.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..http import HttpError, RobotsDenied
from ..models import DocRef, Resource, TextPart, Vehicle
from ..operations import Operation
from ..readers import read_html_text, read_remote_pdf
from .base import SourceAdapter, SourceTerms

SOURCE_NAME = "vwts"
BASE_URL = "https://vwts.ru/"
HOSTS = frozenset({"vwts.ru", "www.vwts.ru"})

_MODEL_PAGE = re.compile(r"^/(?:vw|audi|seat|sk)_[\w\-]+\.html$", re.I)
_ENGINE_HUBS = ("petrol-engine-vw-audi-skoda-repair-manual.html",
                "diesel-engine-vw-audi-skoda-repair-manual.html",
                "electric-engine-vw-audi-skoda-repair-manual.html")
_SECTION_FRAGMENT = re.compile(r"(?:-eng$|-rus$|repair-manual|^pps_|^engine-)", re.I)
_CODE_TOKEN = re.compile(r"^[a-z]{3,4}$")
_NOT_CODES = {"eng", "rus", "pps", "evo", "tsi", "tdi", "mpi", "fsi"}
_MODELS_IN_TEXT = re.compile(
    r"((?:VW|Volkswagen|Skoda|Škoda|Audi|Seat|SEAT)\s[^➤\n]{2,60}?)\s*➤")
_ENGINE_LINE = re.compile(r"Engine\s*(?:code|ID)s?\s*:?\s*([A-Z0-9][A-Z0-9, ./]{2,300})", re.I)
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico")


def engine_codes_from_fragment(fragment: str) -> tuple[str, ...]:
    """`engine-cpta-czca-czea-ea211-2020-09-eng` → ('CPTA','CZCA','CZEA')."""
    if not fragment.lower().startswith("engine-"):
        return ()
    codes = []
    for token in fragment.lower().split("-")[1:]:
        if _CODE_TOKEN.match(token) and token not in _NOT_CODES:
            codes.append(token.upper())
        else:
            break
    return tuple(codes)


def engine_codes_from_text(text: str) -> tuple[str, ...]:
    m = _ENGINE_LINE.search(text)
    if not m:
        return ()
    out = []
    for token in re.split(r"[,\s]+", m.group(1)):
        token = token.strip(" .")
        if re.fullmatch(r"[A-Z][A-Z0-9]{2,3}", token) and token not in ("TSI", "TDI", "MPI", "FSI", "EVO"):
            out.append(token)
    return tuple(dict.fromkeys(out))


def classify(title: str, page_url: str, fragment: str) -> str:
    blob = f"{title} {page_url} {fragment}".lower()
    if fragment.lower().startswith("pps_") or "self-study" in blob or "программ" in blob:
        return "training"
    if "wiring" in blob or "current flow" in blob:
        return "wiring"
    if "diagnos" in blob:
        return "diagnostic"
    if "maintenance" in blob:
        return "maintenance"
    if "brake" in blob:
        return "brake"
    if "gearbox" in blob or "transmission" in blob:
        return "gearbox"
    if "engine" in blob or "двигател" in blob:
        return "engine"
    return "other"


def _segments(container_text: str, titles: list[str]) -> list[str]:
    """Делит текст контейнера на куски «после заголовка N и до заголовка N+1»."""
    positions: list[int | None] = []
    pos = 0
    for t in titles:
        i = container_text.find(t, pos)
        positions.append(i if i >= 0 else None)
        if i >= 0:
            pos = i + len(t)
    result = []
    for k, (t, i) in enumerate(zip(titles, positions)):
        if i is None:
            result.append("")
            continue
        start = i + len(t)
        nxt = next((j for j in positions[k + 1:] if j is not None), len(container_text))
        result.append(container_text[start:nxt])
    return result


def parse_listing(html: str, page_url: str) -> tuple[list[tuple[str, str]], list[DocRef]]:
    """Возвращает (навигация по моделям/двигателям, найденные разделы руководств)."""
    soup = BeautifulSoup(html, "lxml")
    nav: list[tuple[str, str]] = []
    docs: list[DocRef] = []

    for a in soup.find_all("a", href=True):
        full = urljoin(page_url, a["href"])
        parsed = urlparse(full)
        if parsed.hostname not in HOSTS or parsed.fragment:
            continue
        label = a.get_text(" ", strip=True)
        if label and (_MODEL_PAGE.match(parsed.path) or parsed.path.lstrip("/") in _ENGINE_HUBS):
            nav.append((label, f"{parsed.scheme}://{parsed.netloc}{parsed.path}"))

    # группируем ссылки-разделы по ближайшему контейнеру, чтобы привязать к ним тексты рядом
    seen_containers: dict[int, list] = {}
    for a in soup.find_all("a", href=True):
        full = urljoin(page_url, a["href"])
        parsed = urlparse(full)
        if parsed.hostname not in HOSTS or not parsed.fragment:
            continue
        if not _SECTION_FRAGMENT.search(parsed.fragment):
            continue
        container = a.find_parent(["p", "div", "li", "td", "article", "section"]) or a.parent
        seen_containers.setdefault(id(container), [container, []])[1].append((a, full, parsed))

    nav_by_url = {url: label for label, url in nav}
    for container, items in seen_containers.values():
        text = container.get_text(" ", strip=True) if len(container.get_text()) < 4000 else ""
        titles = [a.get_text(" ", strip=True) for a, _, _ in items]
        segments = _segments(text, titles) if text else [""] * len(items)
        for (a, full, parsed), title, segment in zip(items, titles, segments):
            if not title:
                continue
            page = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            codes = engine_codes_from_fragment(parsed.fragment) or engine_codes_from_text(segment)
            models = tuple(dict.fromkeys(m.strip() for m in _MODELS_IN_TEXT.findall(segment)))
            if not models and page in nav_by_url:
                models = (nav_by_url[page],)
            docs.append(DocRef(SOURCE_NAME, title, page, parsed.fragment,
                               classify(title, page, parsed.fragment), codes, models))
    return nav, docs


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9а-я]", "", text.lower())


def _section_resources(soup: BeautifulSoup, anchor: str, page_url: str, limit: int) -> list[Resource]:
    el = soup.find(id=anchor) or soup.find("a", attrs={"name": anchor})
    if el is None:
        return []
    anchors = list(el.find_all("a", href=True))
    if not anchors:
        for nxt in el.next_elements:
            if nxt is el or not getattr(nxt, "name", None):
                continue
            nid = nxt.get("id") if hasattr(nxt, "get") else None
            if nid and nid != anchor and _SECTION_FRAGMENT.search(nid):
                break
            if nxt.name == "a" and nxt.get("href"):
                anchors.append(nxt)
            if len(anchors) >= limit * 4:
                break
    out: list[Resource] = []
    seen: set[str] = set()
    for a in anchors:
        href = a["href"]
        if href.startswith("#"):
            continue
        full = urljoin(page_url, href).split("#")[0]
        parsed = urlparse(full)
        path = parsed.path.lower()
        if parsed.hostname not in HOSTS or path.endswith(_IMAGE_EXT) or "/forum" in path or full in seen:
            continue
        seen.add(full)
        kind = "pdf" if path.endswith(".pdf") else "html"
        out.append(Resource(full, kind, a.get_text(" ", strip=True)))
        if len(out) >= limit:
            break
    return out


class VwtsAdapter(SourceAdapter):
    name = SOURCE_NAME
    hosts = HOSTS
    terms = SourceTerms(
        allows_automated_read=True,   # по robots.txt для обычных клиентов; письменного разрешения нет
        allows_llm=False,             # владелец закрыл ИИ-краулеры: без согласия не передаём текст в LLM
        notes="robots.txt разрешает чтение документации обычным клиентам и закрывает ИИ-краулеры. "
              "Права на сами руководства у производителя; без согласия владельца LLM не использовать.",
    )

    def supports(self, vehicle: Vehicle) -> bool:
        make = (vehicle.make or "").lower()
        return not make or any(k in make for k in ("volkswagen", "vw", "audi", "skoda", "škoda", "seat", "cupra"))

    def _index_pages(self, client, store, nav, urls: list[str], say) -> int:
        """Читает страницы моделей/двигателей и заносит их разделы в индекс. Возвращает число разделов."""
        total = 0
        for number, url in enumerate(urls, start=1):
            say(f"[{number}/{len(urls)}] {url}")
            try:
                page = client.get(url)
            except HttpError as exc:
                # страницы нет (404/410) или robots.txt её закрыл: пропускаем её, остальные читаем дальше.
                # Остальные ошибки (429, 503, сеть) прерывают обновление, чтобы не нагружать сайт.
                if isinstance(exc, RobotsDenied) or exc.status in (404, 410):
                    self.last_warnings.append(f"{url}: пропущено ({exc})")
                    store.mark_page(SOURCE_NAME, url)       # не спрашиваем её снова при каждом поиске
                    continue
                raise
            _, sub_docs = parse_listing(page.text(), url)
            labels = tuple(dict.fromkeys(lab for lab, u in nav if u == url))
            if labels:
                sub_docs = [DocRef(d.source, d.title, d.page_url, d.anchor, d.kind, d.engine_codes,
                                   d.models or labels) for d in sub_docs]
            store.upsert_docs(sub_docs)
            store.mark_page(SOURCE_NAME, url)
            total += len(sub_docs)
        return total

    def _read_home(self, client, store):
        home = client.get(BASE_URL)
        nav, docs = parse_listing(home.text(), BASE_URL)
        store.upsert_nav(SOURCE_NAME, nav)
        store.upsert_docs(docs)
        store.mark_page(SOURCE_NAME, BASE_URL)
        return nav, docs

    def refresh_index(self, client, store, models=None, include_engines=False, all_models=False,
                      progress=None) -> int:
        self.last_warnings: list[str] = []
        say = progress or (lambda message: None)
        nav, docs = self._read_home(client, store)
        total = len(docs)
        pages: list[str] = []
        if all_models:
            fresh = store.fresh_pages(SOURCE_NAME)          # то, что уже загружено, второй раз не качаем
            pages += [url for _, url in nav if url not in fresh]
        for query in (models or []):
            q = _norm(query)
            pages += [url for label, url in nav
                      if q and (q in _norm(label) or q in _norm(urlparse(url).path))]
        if include_engines:
            pages += [BASE_URL + hub for hub in _ENGINE_HUBS]
        return total + self._index_pages(client, store, nav, list(dict.fromkeys(pages)), say)

    def ensure_indexed(self, client, store, vehicle: Vehicle, progress=None) -> int:
        """Перед поиском дозагружает только то, чего ещё нет в индексе: страницу нужной модели
        и (если указан двигатель) три страницы с двигателями. Главная страница читается, если список
        моделей пуст. Уже загруженное повторно не запрашивается."""
        self.last_warnings = []
        say = progress or (lambda message: None)
        fresh = store.fresh_pages(SOURCE_NAME)
        if not store.nav(SOURCE_NAME):
            say(f"[{SOURCE_NAME}] {BASE_URL}")
            self._read_home(client, store)
        nav = store.nav(SOURCE_NAME)
        pages: list[str] = []
        q = _norm(vehicle.model or "")
        if q:
            pages += [url for label, url in nav
                      if (q in _norm(label) or q in _norm(urlparse(url).path)) and url not in fresh]
        if vehicle.engine_code:
            pages += [BASE_URL + hub for hub in _ENGINE_HUBS if BASE_URL + hub not in fresh]
        pages = list(dict.fromkeys(pages))
        return self._index_pages(client, store, nav, pages, say) if pages else 0

    def find_documents(self, store, vehicle: Vehicle, op: Operation) -> list[DocRef]:
        code = (vehicle.engine_code or "").upper()
        model = _norm(vehicle.model or "")
        scored: list[tuple[int, DocRef]] = []
        for doc in store.docs(SOURCE_NAME):
            score = 0
            if code and code in doc.engine_codes:
                score += 10
            if model:
                blob = _norm(" ".join(doc.models) + " " + urlparse(doc.page_url).path)
                if model in blob:
                    score += 4
            if doc.kind in op.doc_kinds:
                score += 2
            if any(h in doc.title.lower() or h in doc.anchor.lower() for h in op.title_hints):
                score += 1
            if doc.kind == "training":
                score -= 1
            relevant = (code and code in doc.engine_codes) or (model and score >= 4)
            if relevant and score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda s: (-s[0], s[1].title))
        return [d for _, d in scored]

    def list_resources(self, client, doc: DocRef, limit: int = 4) -> list[Resource]:
        page = client.get(doc.page_url)
        soup = BeautifulSoup(page.text(), "lxml")
        resources = _section_resources(soup, doc.anchor, doc.page_url, limit) if doc.anchor else []
        if not resources:
            # файлов в разделе не нашли: читаем сам раздел страницы как текст
            resources = [Resource(doc.url, "html", doc.title)]
        return resources

    def read_resource(self, client, resource: Resource) -> list[TextPart]:
        base_url, _, anchor = resource.url.partition("#")
        title = resource.title or base_url
        if resource.kind == "pdf" or base_url.lower().endswith(".pdf"):
            return read_remote_pdf(client, base_url, title)
        html = client.get(base_url).text()
        if anchor:
            soup = BeautifulSoup(html, "lxml")
            el = soup.find(id=anchor)
            if el is not None:
                chunk = [el.get_text("\n", strip=True)]
                for sib in el.find_next_siblings():
                    sid = sib.get("id", "")
                    if sid and _SECTION_FRAGMENT.search(sid):
                        break
                    chunk.append(sib.get_text("\n", strip=True))
                    if sum(len(c) for c in chunk) > 60000:
                        break
                return [TextPart("\n".join(chunk), None, resource.url, title)]
        return read_html_text(html, base_url, title)
