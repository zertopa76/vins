from __future__ import annotations

from pathlib import Path

import pytest
from requests.structures import CaseInsensitiveDict

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_pdf(pages: list[str]) -> bytes:
    """Минимальный PDF с текстом (без внешних библиотек) для тестов."""
    objs: list[bytes] = []

    def add(body: str | bytes) -> int:
        objs.append(body if isinstance(body, bytes) else body.encode("latin-1"))
        return len(objs)

    catalog = add("<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add("")  # заполним позже
    font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids = []
    for text in pages:
        lines = text.split("\n")
        stream = "BT /F1 11 Tf 40 780 Td 14 TL\n" + "\n".join(
            "(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*" for ln in lines
        ) + "\nET"
        content = add(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        page = add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] "
                   f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>")
        kids.append(page)
    objs[pages_id - 1] = (f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                          f"/Count {len(kids)} >>").encode("latin-1")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code = status
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.headers = CaseInsensitiveDict(headers or {})
        if status == 200 and "Content-Length" not in self.headers:
            self.headers["Content-Length"] = str(len(self._body))

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def close(self):
        pass


class FakeSession:
    """Подменяет requests.Session: отдаёт заранее заданные ответы и запоминает запросы."""

    def __init__(self, routes: dict[str, FakeResponse | tuple]):
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, headers=None, timeout=None, stream=None, allow_redirects=None):
        self.calls.append((url, dict(headers or {})))
        item = self.routes.get(url)
        if item is None:
            return FakeResponse(404, b"not found")
        if callable(item):
            return item(headers or {})
        return item


@pytest.fixture
def robots_text() -> str:
    return fixture_text("robots_vwts.txt")


@pytest.fixture
def no_sleep():
    slept: list[float] = []
    return slept, slept.append
