"""Запуск окна приложения на ПОДДЕЛЬНЫХ данных (без интернета) — для проверки интерфейса.

    python -m tests.demo_server [порт]
"""

from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

from tests.conftest import FakeResponse, FakeSession, fixture_text, make_pdf
from vinparts.app.server import AppServer
from vinparts.app.service import AppService
from vinparts.http import PoliteClient
from vinparts.sources.vwts import VwtsAdapter, parse_listing
from vinparts.store import Store

ENGINE_PDF = make_pdf([
    "Cover page, contents",
    "Timing chain - removing and installing\n1 - Chain tensioner\n"
    "Always replace chain tensioner after removing.\n2 - Timing chain\nReplace if damaged or worn.\n"
    "3 - Gasket\nGasket: Replace gasket.\nReplace the sealing ring and the oil filter.\n"
    "Self-locking bolts must be replaced.\nCheck the guide rails for wear.",
])


def build_service(tmp: Path, index: bool = True, download_page: bool = False) -> AppService:
    routes = {
        "https://vwts.ru/robots.txt": FakeResponse(200, fixture_text("robots_vwts.txt")),
        "https://vwts.ru/": FakeResponse(200, fixture_text("home.html")),
        "https://vwts.ru/petrol-engine-vw-audi-skoda-repair-manual.html": FakeResponse(200, fixture_text("model_page.html")),
        "https://vwts.ru/diesel-engine-vw-audi-skoda-repair-manual.html": FakeResponse(200, fixture_text("model_page.html")),
        "https://vwts.ru/electric-engine-vw-audi-skoda-repair-manual.html": FakeResponse(200, fixture_text("model_page.html")),
        "https://vwts.ru/vw_golf7_5g.html": FakeResponse(200, fixture_text("model_page.html")),
        "https://vwts.ru/manuals/ea888_gen3_engine.pdf": (
            FakeResponse(200, fixture_text("download_page.html"), {"Content-Type": "text/html"})
            if download_page else FakeResponse(200, ENGINE_PDF)),
        "https://vwts.ru/manuals/golf7_maintenance.pdf": FakeResponse(200, make_pdf(["Maintenance"])),
    }
    session = FakeSession(routes)
    client = PoliteClient(tmp / "cache", {"vwts.ru"}, session=session, min_delay=0, sleep=lambda s: None)
    service = AppService(tmp, adapters=[VwtsAdapter()], client=client)
    service.fake_session = session  # для тестов
    if index:
        store = Store(tmp / "index.sqlite")
        nav, docs = parse_listing(fixture_text("home.html"), "https://vwts.ru/")
        store.upsert_nav("vwts", nav)
        store.upsert_docs(docs)
        store.close()
    return service


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8799
    service = build_service(Path(tempfile.mkdtemp()), download_page="--download-page" in sys.argv)
    server = AppServer(service, port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("DEMO", server.url, flush=True)
    server.stop_event.wait()
