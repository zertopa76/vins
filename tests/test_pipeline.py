from bs4 import BeautifulSoup

from tests.conftest import FakeResponse, FakeSession, fixture_text, make_pdf
from vinparts.http import PoliteClient
from vinparts.models import DocRef, Resource, TextPart, Vehicle
from vinparts.operations import match_operation
from vinparts.pipeline import run_query
from vinparts.sources.base import SourceAdapter, SourceTerms
from vinparts.sources.vwts import VwtsAdapter, _section_resources, parse_listing
from vinparts.store import Store

HUB = "https://vwts.ru/petrol-engine-vw-audi-skoda-repair-manual.html"
GOLF = "https://vwts.ru/vw_golf7_5g.html"


def build_world(tmp_path, robots_text):
    engine_pdf = make_pdf([
        "Cover page, contents",
        "Timing chain - removing and installing\n1 - Chain tensioner\n"
        "Always replace chain tensioner after removing.\n2 - Timing chain\nReplace if damaged or worn.",
    ])
    routes = {
        "https://vwts.ru/robots.txt": FakeResponse(200, robots_text),
        "https://vwts.ru/": FakeResponse(200, fixture_text("home.html")),
        HUB: FakeResponse(200, fixture_text("model_page.html")),
        GOLF: FakeResponse(200, fixture_text("model_page.html")),
        "https://vwts.ru/manuals/ea888_gen3_engine.pdf": FakeResponse(200, engine_pdf),
    }
    session = FakeSession(routes)
    client = PoliteClient(tmp_path / "cache", {"vwts.ru"}, session=session, min_delay=0,
                          sleep=lambda s: None)
    store = Store()
    nav, docs = parse_listing(fixture_text("home.html"), "https://vwts.ru/")
    store.upsert_nav("vwts", nav)
    store.upsert_docs(docs)
    return client, store, session


def test_section_resources_stop_at_next_section():
    soup = BeautifulSoup(fixture_text("model_page.html"), "lxml")
    res = _section_resources(soup, "vw-golf-7-maintenance-eng", GOLF, limit=5)
    assert [r.url for r in res] == ["https://vwts.ru/manuals/golf7_maintenance.pdf"]   # без jpg и без brake.pdf
    assert res[0].kind == "pdf"


def test_end_to_end_query(tmp_path, robots_text):
    client, store, session = build_world(tmp_path, robots_text)
    result = run_query([VwtsAdapter()], store, client,
                       Vehicle(model="golf 7", engine_code="CJSA"), match_operation("цепь грм"))
    parts = {f.part.lower(): f for f in result.findings}
    assert parts["chain tensioner"].role == "required"
    assert parts["chain tensioner"].part_ru == "натяжитель цепи"
    assert parts["chain tensioner"].page == 2
    assert parts["chain tensioner"].source_url.endswith("ea888_gen3_engine.pdf")
    assert parts["timing chain"].role == "conditional"
    assert "if damaged" not in parts
    fetched = [u for u, _ in session.calls]
    assert "https://vwts.ru/manuals/golf7_brakes.pdf" not in fetched   # лишнего не качали


def test_declined_confirmation_downloads_nothing(tmp_path, robots_text):
    client, store, session = build_world(tmp_path, robots_text)
    result = run_query([VwtsAdapter()], store, client, Vehicle(model="golf 7", engine_code="CJSA"),
                       match_operation("цепь грм"), confirm=lambda doc, res: False)
    assert result.findings == []
    assert not any(u.endswith(".pdf") for u, _ in session.calls)
    assert any("пропущено" in n for n in result.notes)


def test_unsupported_make_is_skipped(tmp_path, robots_text):
    client, store, session = build_world(tmp_path, robots_text)
    result = run_query([VwtsAdapter()], store, client, Vehicle(make="Toyota", model="corolla"),
                       match_operation("цепь грм"))
    assert result.findings == [] and session.calls == []


def test_no_index_gives_helpful_note(tmp_path, robots_text):
    client, _, session = build_world(tmp_path, robots_text)
    result = run_query([VwtsAdapter()], Store(), client, Vehicle(model="golf 7", engine_code="CJSA"),
                       match_operation("цепь грм"), auto_index=False)
    assert result.findings == [] and any("index" in n for n in result.notes)


def test_search_loads_missing_index_pages_by_itself(tmp_path, robots_text):
    client, _, session = build_world(tmp_path, robots_text)
    store = Store()                                        # пустой индекс: ничего не загружено заранее
    adapter = VwtsAdapter()
    result = run_query([adapter], store, client, Vehicle(model="golf 7", engine_code="CJSA"),
                       match_operation("цепь грм"))
    assert any(f.part == "chain tensioner" for f in result.findings)
    fresh = store.fresh_pages("vwts")
    assert GOLF in fresh and HUB in fresh and "https://vwts.ru/" in fresh
    assert "https://vwts.ru/vw_golf8_cd.html" not in fresh   # чужие модели не трогаем
    # второй запрос ничего лишнего не дозагружает
    assert adapter.ensure_indexed(client, store, Vehicle(model="golf 7", engine_code="CJSA")) == 0


def test_models_sharing_one_page_keep_all_names():
    store = Store()
    store.upsert_nav("vwts", [("VW Golf 6, Jetta 6 2009 - 2017", "https://vwts.ru/vw_golf6_5k.html"),
                              ("VW Golf Plus 2009 - 2014", "https://vwts.ru/vw_golf6_5k.html")])
    labels = {label for label, _ in store.nav("vwts")}
    assert len(labels) == 2 and store.counts("vwts")[1] == 1


def test_core_is_source_agnostic(tmp_path):
    """Новый источник = новый класс; ядро (pipeline, extract) не меняется."""

    class FakeToyota(SourceAdapter):
        name = "fake-toyota"
        hosts = frozenset()
        terms = SourceTerms(True, False, "тест")

        def supports(self, vehicle):
            return (vehicle.make or "").lower() == "toyota"

        def refresh_index(self, client, store, models=None, include_engines=False, all_models=False, progress=None):
            return 0

        def find_documents(self, store, vehicle, op):
            return [DocRef(self.name, "Timing chain", "mem://doc", "", "engine")]

        def list_resources(self, client, doc, limit=4):
            return [Resource("mem://doc", "html", doc.title)]

        def read_resource(self, client, resource):
            return [TextPart("Timing chain\nAlways replace chain tensioner after removing.", None,
                             resource.url, resource.title)]

    result = run_query([FakeToyota(), VwtsAdapter()], Store(), client=None,
                       vehicle=Vehicle(make="Toyota"), op=match_operation("цепь грм"))
    assert [f.part for f in result.findings] == ["chain tensioner"]
    assert result.findings[0].source_url == "mem://doc"
