import pytest

from tests.conftest import FakeResponse, FakeSession
from vinparts.http import HostNotAllowed, HttpError, PoliteClient, RobotsDenied, TooLarge

ROBOTS = "User-agent: *\nDisallow: /forum/search/\n"


def make_client(tmp_path, routes, **kw):
    session = FakeSession(routes)
    slept = []
    ticks = {"t": 0.0}

    def sleep(sec):
        slept.append(sec)
        ticks["t"] += sec

    client = PoliteClient(tmp_path, {"vwts.ru"}, session=session, min_delay=4.0, sleep=sleep,
                          clock=lambda: ticks["t"], **kw)
    return client, session, slept


def test_get_checks_robots_first_and_sends_honest_user_agent(tmp_path):
    routes = {"https://vwts.ru/robots.txt": FakeResponse(200, ROBOTS),
              "https://vwts.ru/page.html": FakeResponse(200, "<html>ok</html>")}
    client, session, _ = make_client(tmp_path, routes)
    result = client.get("https://vwts.ru/page.html")
    assert result.text() == "<html>ok</html>"
    assert session.calls[0][0].endswith("/robots.txt")
    assert all("VinPartsHelper" in headers["User-Agent"] for _, headers in session.calls)


def test_robots_denied_blocks_request(tmp_path):
    routes = {"https://vwts.ru/robots.txt": FakeResponse(200, ROBOTS),
              "https://vwts.ru/forum/search/?q=x": FakeResponse(200, "secret")}
    client, session, _ = make_client(tmp_path, routes)
    with pytest.raises(RobotsDenied):
        client.get("https://vwts.ru/forum/search/?q=x")
    assert all("forum/search" not in url for url, _ in session.calls)


def test_host_allowlist_and_redirects(tmp_path):
    routes = {"https://vwts.ru/robots.txt": FakeResponse(200, ROBOTS),
              "https://vwts.ru/old.html": FakeResponse(301, b"", {"Location": "https://evil.example/x"})}
    client, _, _ = make_client(tmp_path, routes)
    with pytest.raises(HostNotAllowed):
        client.get("https://other.example/page")
    with pytest.raises(HostNotAllowed):
        client.get("https://vwts.ru/old.html")  # редирект на чужой домен


def test_pause_between_requests(tmp_path):
    routes = {"https://vwts.ru/robots.txt": FakeResponse(200, ROBOTS),
              "https://vwts.ru/a.html": FakeResponse(200, "a"),
              "https://vwts.ru/b.html": FakeResponse(200, "b")}
    client, _, slept = make_client(tmp_path, routes)
    client.get("https://vwts.ru/a.html")
    client.get("https://vwts.ru/b.html")
    assert len(slept) >= 2 and all(s == pytest.approx(4.0) for s in slept)


def test_cache_and_etag_revalidation(tmp_path):
    state = {"n": 0}

    def page(headers):
        state["n"] += 1
        if headers.get("If-None-Match") == '"v1"':
            return FakeResponse(304, b"")
        return FakeResponse(200, "<html>v1</html>", {"ETag": '"v1"'})

    routes = {"https://vwts.ru/robots.txt": FakeResponse(200, ROBOTS), "https://vwts.ru/p.html": page}
    session = FakeSession(routes)
    now = {"t": 1000.0}
    client = PoliteClient(tmp_path, {"vwts.ru"}, session=session, min_delay=0, sleep=lambda s: None,
                          wall=lambda: now["t"], ttl_hours=1)
    assert not client.get("https://vwts.ru/p.html").from_cache and state["n"] == 1
    assert client.get("https://vwts.ru/p.html").from_cache and state["n"] == 1   # свежий кэш: без запроса
    now["t"] += 3 * 3600
    again = client.get("https://vwts.ru/p.html")                                  # устарел: ETag -> 304
    assert state["n"] == 2 and again.from_cache and again.text() == "<html>v1</html>"


def test_server_errors_are_reported_not_retried(tmp_path):
    routes = {"https://vwts.ru/robots.txt": FakeResponse(200, ROBOTS),
              "https://vwts.ru/busy.html": FakeResponse(429, b"", {"Retry-After": "120"})}
    client, session, _ = make_client(tmp_path, routes)
    with pytest.raises(HttpError, match="Retry-After=120"):
        client.get("https://vwts.ru/busy.html")
    assert sum(1 for url, _ in session.calls if url.endswith("busy.html")) == 1


def test_size_limit(tmp_path):
    routes = {"https://vwts.ru/robots.txt": FakeResponse(200, ROBOTS),
              "https://vwts.ru/big.pdf": FakeResponse(200, b"x" * 5000)}
    client, _, _ = make_client(tmp_path, routes)
    with pytest.raises(TooLarge):
        client.get("https://vwts.ru/big.pdf", max_bytes=1000)


def test_unreadable_robots_means_closed(tmp_path):
    routes = {"https://vwts.ru/robots.txt": FakeResponse(500, b""),
              "https://vwts.ru/a.html": FakeResponse(200, "a")}
    client, _, _ = make_client(tmp_path, routes)
    with pytest.raises(RobotsDenied):
        client.get("https://vwts.ru/a.html")


def test_missing_robots_means_open(tmp_path):
    routes = {"https://vwts.ru/robots.txt": FakeResponse(404, b""),
              "https://vwts.ru/a.html": FakeResponse(200, "a")}
    client, _, _ = make_client(tmp_path, routes)
    assert client.get("https://vwts.ru/a.html").text() == "a"
