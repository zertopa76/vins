"""Картинка страницы PDF с подсвеченным местом, откуда взята деталь.

Нужен pypdfium2 (есть готовые сборки для Windows и Mac). Если его нет, программа работает
без картинок: остаются цитата и ссылка на страницу руководства.
"""

from __future__ import annotations

import io
import re

try:  # pragma: no cover - зависит от окружения
    import pypdfium2 as pdfium
except Exception:  # noqa: BLE001
    pdfium = None


def available() -> bool:
    return pdfium is not None


def _candidates(quote: str, part: str) -> list[str]:
    """Что искать на странице: сначала кусок цитаты (точнее), потом название детали."""
    out: list[str] = []
    cleaned = re.sub(r"\s+", " ", quote or "").strip(" «»\"'…")
    cleaned = re.sub(r"^[A-Za-z][\w ]{0,40}:\s+", "", cleaned) if cleaned.count(":") == 1 else cleaned
    if cleaned:
        out.append(cleaned[:60])
        words = cleaned.split(" ")
        if len(words) > 4:
            out.append(" ".join(words[:4]))
    if part:
        out.append(part)
    return list(dict.fromkeys(c for c in out if len(c) >= 3))


def _find_rects(textpage, needle: str) -> list[tuple[float, float, float, float]]:
    searcher = textpage.search(needle, match_case=False)
    hit = searcher.get_next()
    if not hit:
        return []
    index, count = hit
    rects = []
    for i in range(textpage.count_rects(index, count)):
        rects.append(textpage.get_rect(i))   # (left, bottom, right, top) в координатах PDF
    return rects


def page_count(data: bytes) -> int:
    if pdfium is None:
        return 0
    pdf = pdfium.PdfDocument(data)
    try:
        return len(pdf)
    finally:
        pdf.close()


def render_page(data: bytes, page_number: int, quote: str = "", part: str = "",
                width: int = 900) -> bytes | None:
    """PNG страницы (нумерация с 1) с жёлтой подсветкой найденного места. None, если нельзя."""
    if pdfium is None:
        return None
    from PIL import Image, ImageDraw

    pdf = pdfium.PdfDocument(data)
    try:
        if not 1 <= page_number <= len(pdf):
            return None
        page = pdf[page_number - 1]
        page_w, page_h = page.get_size()
        scale = width / page_w
        image = page.render(scale=scale).to_pil().convert("RGBA")

        rects: list[tuple[float, float, float, float]] = []
        try:
            textpage = page.get_textpage()
            for needle in _candidates(quote, part):
                rects = _find_rects(textpage, needle)
                if rects:
                    break
        except Exception:  # noqa: BLE001 - подсветка необязательна, страница важнее
            rects = []

        if rects:
            overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            for left, bottom, right, top in rects:
                draw.rectangle(
                    [left * scale - 2, (page_h - top) * scale - 2,
                     right * scale + 2, (page_h - bottom) * scale + 2],
                    fill=(255, 214, 0, 90), outline=(230, 160, 0, 220), width=2)
            image = Image.alpha_composite(image, overlay)

        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    finally:
        pdf.close()
