import pytest

from tests.conftest import FakeResponse, FakeSession, fixture_text, make_pdf
from vinparts.http import PoliteClient
from vinparts.library import Library, LibraryError, key_of
from vinparts.models import Vehicle
from vinparts.operations import match_operation
from vinparts.pipeline import run_query
from vinparts.sources.vwts import VwtsAdapter, parse_listing
from vinparts.store import Store

PDF_URL = "https://vwts.ru/manuals/ea888_gen3_engine.pdf"
ENGINE_PDF = make_pdf([
    "Cover page",
    "Timing chain - removing and installing\n1 - Chain tensioner\nAlways replace chain tensioner after removing.",
])


def test_key_ignores_case_folders_and_browser_suffix():
    assert key_of("https://vwts.ru/vw/g7/VW-Golf-7-maintenance-eng.pdf#page=3") == "vw-golf-7-maintenance-eng"
    assert key_of("vw-golf-7-maintenance-eng (1).pdf") == "vw-golf-7-maintenance-eng"
    assert key_of("C:\\Users\\me\\Downloads\\vw-golf-7-maintenance-eng.pdf") == "vw-golf-7-maintenance-eng"
    assert key_of("engine-cjsa-eng 2.pdf") == "engine-cjsa-eng"


def test_add_find_replace_and_remove(tmp_path):
    lib = Library(tmp_path / "lib")
    assert lib.find(PDF_URL) is None and lib.list() == []
    lib.add("ea888_gen3_engine (1).pdf", ENGINE_PDF)
    assert lib.read(PDF_URL) == ENGINE_PDF
    lib.add("ea888_gen3_engine.pdf", ENGINE_PDF)          # тот же документ под другим именем не копится
    assert [f.name for f in lib.list()] == ["ea888_gen3_engine.pdf"]
    assert lib.remove("ea888_gen3_engine.pdf") and lib.find(PDF_URL) is None
    assert not lib.remove("../../etc/passwd")


@pytest.mark.parametrize("name,data,text", [
    ("a.pdf", b"", "пустой"),
    ("a.txt", ENGINE_PDF, "только PDF"),
    ("a.pdf", fixture_text("download_page.html").encode(), "страница ожидания"),
    ("a.pdf", ENGINE_PDF[:-40], "не полностью"),
])
def test_add_rejects_bad_files(tmp_path, name, data, text):
    lib = Library(tmp_path / "lib")
    with pytest.raises(LibraryError, match=text):
        lib.add(name, data)
    assert lib.list() == []


def make_world(tmp_path, robots_text, pdf_response):
    routes = {
        "https://vwts.ru/robots.txt": FakeResponse(200, robots_text),
        "https://vwts.ru/": FakeResponse(200, fixture_text("home.html")),
        "https://vwts.ru/vw_golf7_5g.html": FakeResponse(200, fixture_text("model_page.html")),
        "https://vwts.ru/petrol-engine-vw-audi-skoda-repair-manual.html": FakeResponse(200, fixture_text("model_page.html")),
        "https://vwts.ru/manuals/golf7_maintenance.pdf": FakeResponse(200, make_pdf(["Maintenance"])),
        PDF_URL: pdf_response,
    }
    session = FakeSession(routes)
    client = PoliteClient(tmp_path / "cache", {"vwts.ru"}, session=session, min_delay=0, sleep=lambda s: None)
    store = Store()
    nav, docs = parse_listing(fixture_text("home.html"), "https://vwts.ru/")
    store.upsert_nav("vwts", nav)
    store.upsert_docs(docs)
    return client, store, session


def test_site_returns_download_page_gives_missing_entry(tmp_path, robots_text):
    client, store, _ = make_world(tmp_path, robots_text,
                                  FakeResponse(200, fixture_text("download_page.html"), {"Content-Type": "text/html"}))
    result = run_query([VwtsAdapter()], store, client, Vehicle(model="golf 7", engine_code="CJSA"),
                       match_operation("цепь грм"))
    assert result.findings == []
    assert [m["url"] for m in result.missing] == [PDF_URL]
    assert result.missing[0]["filename"] == "ea888_gen3_engine.pdf"


def test_library_file_is_used_without_touching_the_site(tmp_path, robots_text):
    client, store, session = make_world(tmp_path, robots_text,
                                        FakeResponse(200, fixture_text("download_page.html"), {"Content-Type": "text/html"}))
    lib = Library(tmp_path / "lib")
    lib.add("ea888_gen3_engine (1).pdf", ENGINE_PDF)
    asked = []
    result = run_query([VwtsAdapter()], store, client, Vehicle(model="golf 7", engine_code="CJSA"),
                       match_operation("цепь грм"), library=lib,
                       confirm=lambda doc, res: asked.append(res) or True)
    # спрашиваем только про то, чего в библиотеке нет; файл из библиотеки с сайта не запрашивается
    assert [[r.url for r in res] for res in asked] == [["https://vwts.ru/manuals/golf7_maintenance.pdf"]]
    assert PDF_URL not in [u for u, _ in session.calls]
    assert result.missing == [] and result.from_library == ["ea888_gen3_engine.pdf"]
    finding = result.findings[0]
    assert finding.part == "chain tensioner" and finding.page == 2
    assert finding.source_url == PDF_URL                   # ссылка остаётся на оригинал на сайте
