"""Чтение текста из PDF, HTML и обычных файлов. Всё выполняется локально."""

from __future__ import annotations

import io
from pathlib import Path

from bs4 import BeautifulSoup

from .models import TextPart


class DocumentError(Exception):
    """Документ получен, но прочитать его не удалось (не PDF, обрыв, повреждение)."""


def _sample(data: bytes) -> str:
    text = data[:160].decode("utf-8", errors="replace")
    return " ".join(text.split())[:120]


def pdf_problem(data: bytes, content_type: str = "") -> str | None:
    """Если вместо PDF пришло что-то другое, объясняет что именно."""
    if not data:
        return "Сервер вернул пустой ответ."
    if b"%PDF-" in data[:1024]:
        return None
    kind = (content_type or "").split(";")[0].strip() or "тип не указан"
    web = b"<html" in data[:2048].lower() or b"<!doctype" in data[:2048].lower()
    what = "веб-страница" if web else "не PDF"
    hint = (" Скачайте файл в браузере по этой же ссылке и откройте его на вкладке «Свой файл»."
            if web else "")
    return (f"Сервер вернул не PDF, а {what} ({len(data)} байт, Content-Type: {kind}). "
            f"Начало ответа: «{_sample(data)}».{hint}")


def _read_pdf_pdfium(data: bytes, url: str, title: str) -> list[TextPart]:
    import pypdfium2 as pdfium  # терпимее к повреждённым файлам и намного быстрее на больших руководствах

    pdf = pdfium.PdfDocument(data)
    parts: list[TextPart] = []
    try:
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                text = page.get_textpage().get_text_range()
            except Exception:  # noqa: BLE001 - плохая страница не должна останавливать разбор
                text = ""
            finally:
                page.close()
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            if text.strip():
                parts.append(TextPart(text, index + 1, url, title))
    finally:
        pdf.close()
    return parts


def _read_pdf_pypdf(data: bytes, url: str, title: str) -> list[TextPart]:
    from pypdf import PdfReader  # импорт здесь, чтобы остальной код работал и без pypdf

    reader = PdfReader(io.BytesIO(data))
    parts: list[TextPart] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # повреждённая страница не должна останавливать разбор всего файла
            text = ""
        if text.strip():
            parts.append(TextPart(text, number, url, title))
    return parts


def read_pdf_bytes(data: bytes, url: str = "", title: str = "", content_type: str = "") -> list[TextPart]:
    problem = pdf_problem(data, content_type)
    if problem:
        raise DocumentError(problem)
    errors: list[str] = []
    for name, engine in (("pdfium", _read_pdf_pdfium), ("pypdf", _read_pdf_pypdf)):
        try:
            return engine(data, url, title)
        except ImportError:
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
    cut = b"%%EOF" not in data[-2048:]
    reason = ("Файл скачан не полностью (нет конца файла)." if cut
              else "Файл повреждён или имеет необычный формат.")
    raise DocumentError(f"{reason} {len(data)} байт; {'; '.join(errors) or 'нет библиотеки чтения PDF'}.")


def read_remote_pdf(client, url: str, title: str = "") -> list[TextPart]:
    """Скачивает PDF и читает его. Плохой ответ не остаётся в кэше: сначала пробуем скачать заново.
    Если сайт вернул страницу вместо файла, повторные запросы откладываются на несколько часов."""
    earlier = client.recent_failure(url)
    if earlier:
        raise DocumentError(earlier)
    fetched = client.get(url)
    try:
        return read_pdf_bytes(fetched.content, url, title, fetched.content_type)
    except DocumentError as first:
        sample = client.save_debug(url, fetched.content)
        client.forget(url)
        error = first
        if fetched.from_cache:           # в кэше мог лежать плохой ответ от прошлых запусков
            fetched = client.get(url)
            try:
                return read_pdf_bytes(fetched.content, url, title, fetched.content_type)
            except DocumentError as second:
                sample = client.save_debug(url, fetched.content)
                client.forget(url)
                error = second
        message = f"{error} Образец ответа сохранён: {sample}"
        if pdf_problem(fetched.content, fetched.content_type):      # пришло не то, что просили: повторять рано
            client.record_failure(url, message)
        raise DocumentError(message) from error


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n")


def read_html_text(html: str, url: str = "", title: str = "") -> list[TextPart]:
    text = html_to_text(html)
    return [TextPart(text, None, url, title)] if text.strip() else []


def decode_bytes(data: bytes) -> str:
    for enc in ("utf-8", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def read_file(path: str | Path) -> list[TextPart]:
    path = Path(path)
    data = path.read_bytes()
    suffix = path.suffix.lower()
    title = path.name
    if suffix == ".pdf":
        return read_pdf_bytes(data, str(path), title)
    if suffix in (".html", ".htm"):
        return read_html_text(decode_bytes(data), str(path), title)
    text = decode_bytes(data)
    return [TextPart(text, None, str(path), title)] if text.strip() else []
