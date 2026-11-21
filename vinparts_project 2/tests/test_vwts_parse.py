from tests.conftest import fixture_text
from vinparts.models import Vehicle
from vinparts.operations import match_operation
from vinparts.sources.vwts import (VwtsAdapter, classify, engine_codes_from_fragment,
                                   engine_codes_from_text, parse_listing)
from vinparts.store import Store

HOME = "https://vwts.ru/"


def test_engine_codes_from_fragment():
    assert engine_codes_from_fragment("engine-cpta-czca-czea-ea211-2020-09-eng") == ("CPTA", "CZCA", "CZEA")
    assert engine_codes_from_fragment(
        "engine-awy-azq-bbm-bmd-bme-bzg-ea-111-repair-manual-eng") == ("AWY", "AZQ", "BBM", "BMD", "BME", "BZG")
    assert engine_codes_from_fragment("engine-dnka-ea211-evo2-repair-manual-eng") == ("DNKA",)
    assert engine_codes_from_fragment("vw-golf-7-maintenance-eng") == ()


def test_engine_codes_from_text():
    assert engine_codes_from_text("Workshop manual Engine code: CJSA, CJSB, CHHA ") == ("CJSA", "CJSB", "CHHA")
    assert engine_codes_from_text("нет кодов") == ()


def test_classify():
    assert classify("Maintenance (eng.)", "https://vwts.ru/x.html", "x-maintenance-eng") == "maintenance"
    assert classify("2.0 TSI engine", "https://vwts.ru/petrol-engine.html", "engine-cjsa-eng") == "engine"
    assert classify("SSP 757", "https://vwts.ru/x.html", "pps_757-the-id-buzz") == "training"
    assert classify("Brake system (eng.)", "https://vwts.ru/x.html", "x-brake-system-eng") == "brake"


def test_parse_listing_finds_nav_and_docs():
    nav, docs = parse_listing(fixture_text("home.html"), HOME)
    labels = dict((url, label) for label, url in nav)
    assert labels["https://vwts.ru/vw_golf7_5g.html"].startswith("VW Golf 7")
    assert "https://vwts.ru/forum/" not in labels
    by_anchor = {d.anchor: d for d in docs}

    tsi = by_anchor["engine-cjsa-cjsb-chha-chhb-dlba-dlbc-dkza-dktb-czpb-repair-manual-eng"]
    assert tsi.kind == "engine" and "CJSA" in tsi.engine_codes and "CZPB" in tsi.engine_codes
    assert any("Golf" in m for m in tsi.models)

    ea211 = by_anchor["engine-cpta-czca-czea-ea211-2020-09-eng"]
    assert ea211.engine_codes == ("CPTA", "CZCA", "CZEA")
    assert not any("Golf" in m for m in ea211.models)   # тексты соседних записей не смешиваются

    maint = by_anchor["vw-golf-7-maintenance-eng"]
    assert maint.kind == "maintenance"
    # прямая ссылка на PDF без якоря разделом не считается
    assert all(not d.page_url.endswith(".pdf") for d in docs)


def _index():
    store = Store()
    nav, docs = parse_listing(fixture_text("home.html"), HOME)
    store.upsert_nav("vwts", nav)
    store.upsert_docs(docs)
    return store


def test_find_documents_prefers_matching_engine_code():
    store = _index()
    op = match_operation("цепь грм")
    docs = VwtsAdapter().find_documents(store, Vehicle(model="golf 7", engine_code="CJSA"), op)
    assert docs and docs[0].anchor.startswith("engine-cjsa")
    assert all("czea" not in d.anchor for d in docs)


def test_find_documents_without_matches_returns_empty():
    store = _index()
    op = match_operation("цепь грм")
    assert VwtsAdapter().find_documents(store, Vehicle(model="phaeton", engine_code="ZZZZ"), op) == []


def test_upsert_is_idempotent():
    store = _index()
    before = store.counts("vwts")
    nav, docs = parse_listing(fixture_text("home.html"), HOME)
    store.upsert_docs(docs)
    assert store.counts("vwts") == before
