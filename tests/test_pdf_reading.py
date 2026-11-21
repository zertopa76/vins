import pytest
import requests

from tests.conftest import FakeResponse, FakeSession, fixture_text, make_pdf
from vinparts.extract import analyze
from vinparts.http import HttpError, PoliteClient
from vinparts.models import Resource
from vinparts.operations import match_operation
from vinparts.readers import (DocumentError, _read_pdf_pdfium, _read_pdf_pypdf, pdf_problem, read_pdf_bytes,
                              read_remote_pdf)
from vinparts.sources.vwts import VwtsAdapter

URL = "https://vwts.ru/vw/g7/vw-golf-7-maintenance-eng.pdf"
GOOD = make_pdf(["Timing chain\n1 - Chain tensioner\nAlways replace chain tensioner after removing.\n"
                 "Replace the sealing ring and the oil filter.\nCheck the guide rails for wear."])
HTML = b"<!DOCTYPE html><html><head><title>Blocked</title></head><body>Please wait</body></html>"


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def make_client(tmp_path, routes, wall=None):
    base = {"https://vwts.ru/robots.txt": FakeResponse(200, fixture_text("robots_vwts.txt"))}
    session = FakeSession({**base, **routes})
    kwargs = {"wall": wall} if wall else {}
    return PoliteClient(tmp_path / "cache", {"vwts.ru"}, session=session, min_delay=0, sleep=lambda s: None,
                        **kwargs), session


def pdf_calls(session):
    return [c for c in session.calls if c[0].endswith(".pdf")]


def roles(parts):
    op = match_operation("цепь грм")
    return {(f.part.lower(), f.role) for f in analyze(parts, op)}


def test_both_pdf_engines_give_the_same_findings():
    a = roles(_read_pdf_pdfium(GOOD, URL, "t"))
    b = roles(_read_pdf_pypdf(GOOD, URL, "t"))
    assert a == b and ("chain tensioner", "required") in a and ("guide rails", "check") in a


def test_truncated_pdf_gives_clear_error_instead_of_stream_message():
    cut = GOOD[:-30]     # нет хвоста файла: раньше пользователь видел только «Stream has ended unexpectedly»
    with pytest.raises(DocumentError) as err:
        read_pdf_bytes(cut, URL, "t")
    assert "не полностью" in str(err.value) and "байт" in str(err.value)


def test_html_instead_of_pdf_is_explained():
    message = pdf_problem(HTML, "text/html; charset=utf-8")
    assert "веб-страница" in message and "text/html" in message and "Blocked" in message
    assert pdf_problem(b"") and pdf_problem(GOOD) is None


def test_junk_pdf_gives_readable_error():
    with pytest.raises(DocumentError) as err:
        read_pdf_bytes(b"%PDF-1.4\nthis is not a real pdf at all")
    assert "не полностью" in str(err.value) or "повреждён" in str(err.value)


def test_html_for_pdf_is_not_kept_in_cache_and_sample_is_saved(tmp_path):
    client, session = make_client(tmp_path, {URL: FakeResponse(200, HTML, {"Content-Type": "text/html"})})
    adapter = VwtsAdapter()
    with pytest.raises(DocumentError) as err:
        adapter.read_resource(client, Resource(URL, "pdf", "Maintenance"))
    text = str(err.value)
    assert "веб-страница" in text and "Образец ответа сохранён" in text
    assert list((tmp_path / "debug").glob("*.sample"))
    assert not list((tmp_path / "cache").glob("*.bin")) or all(b"Blocked" not in p.read_bytes()
                                                              for p in (tmp_path / "cache").glob("*.bin"))
    assert "Свой файл" in text                      # подсказка, что делать


def test_bad_cached_response_is_replaced_automatically(tmp_path):
    client, session = make_client(tmp_path, {URL: FakeResponse(200, HTML, {"Content-Type": "text/html"})})
    client.get(URL)                                     # плохой ответ осел в кэше (как в прошлых запусках)
    session.routes[URL] = FakeResponse(200, GOOD, {"Content-Type": "application/pdf"})
    parts = read_remote_pdf(client, URL, "Maintenance")
    assert parts and "chain" in parts[0].text.lower()
    assert len(pdf_calls(session)) == 2                  # один раз скачано заново


def test_truncated_download_is_reported_and_not_cached(tmp_path):
    short = FakeResponse(200, GOOD[:200], {"Content-Length": str(len(GOOD))})
    client, session = make_client(tmp_path, {URL: short})
    with pytest.raises(HttpError, match="не полностью"):
        client.get(URL)
    session.routes[URL] = FakeResponse(200, GOOD)
    assert client.get(URL).content == GOOD and not client.get(URL).from_cache is False


def test_connection_drop_is_reported(tmp_path):
    class Dropping(FakeResponse):
        def iter_content(self, chunk_size=65536):
            yield b"%PDF-1.4"
            raise requests.exceptions.ChunkedEncodingError("Connection broken")

    client, _ = make_client(tmp_path, {URL: Dropping(200, b"x" * 10, {"Content-Length": "99"})})
    with pytest.raises(HttpError, match="оборвалась"):
        client.get(URL)
    assert not list((tmp_path / "cache").glob("*.bin"))


def test_pdf_requests_ask_for_pdf(tmp_path):
    client, session = make_client(tmp_path, {URL: FakeResponse(200, GOOD)})
    client.get(URL)
    assert session.calls[-1][1]["Accept"].startswith("application/pdf")


def test_site_is_not_asked_again_for_hours_after_html_answer(tmp_path):
    clock = Clock()
    client, session = make_client(tmp_path, {URL: FakeResponse(200, HTML, {"Content-Type": "text/html"})}, wall=clock)
    adapter = VwtsAdapter()
    resource = Resource(URL, "pdf", "Maintenance")
    with pytest.raises(DocumentError):
        adapter.read_resource(client, resource)
    asked = len(pdf_calls(session))
    with pytest.raises(DocumentError, match="Повторный запрос отложен"):
        adapter.read_resource(client, resource)
    assert len(pdf_calls(session)) == asked          # второй запрос к сайту не ходил

    clock.now += 7 * 3600                            # через 7 часов пробуем снова
    session.routes[URL] = FakeResponse(200, GOOD, {"Content-Type": "application/pdf"})
    parts = adapter.read_resource(client, resource)
    assert parts and len(pdf_calls(session)) == asked + 1


def test_truncated_download_is_retried_without_waiting(tmp_path):
    clock = Clock()
    short = FakeResponse(200, GOOD[:200], {"Content-Length": str(len(GOOD))})
    client, session = make_client(tmp_path, {URL: short}, wall=clock)
    with pytest.raises(HttpError):
        read_remote_pdf(client, URL, "t")
    session.routes[URL] = FakeResponse(200, GOOD)
    assert read_remote_pdf(client, URL, "t")         # обрыв связи не считается отказом сайта
