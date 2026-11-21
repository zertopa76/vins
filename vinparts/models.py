"""Простые структуры данных, общие для всех источников."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Vehicle:
    make: str | None = None
    model: str | None = None        # свободный текст: "golf 7", "octavia a7"
    year: int | None = None
    engine_code: str | None = None  # например "CZEA"
    vin: str | None = None

    def describe(self) -> str:
        parts = [self.make, self.model, str(self.year) if self.year else None,
                 f"двигатель {self.engine_code}" if self.engine_code else None]
        return ", ".join(p for p in parts if p) or "машина не указана"


@dataclass
class DocRef:
    """Ссылка на раздел руководства. Сам текст здесь не хранится."""
    source: str
    title: str
    page_url: str
    anchor: str = ""
    kind: str = "other"                 # engine / maintenance / gearbox / brake / wiring / ...
    engine_codes: tuple[str, ...] = ()
    models: tuple[str, ...] = ()

    @property
    def url(self) -> str:
        return f"{self.page_url}#{self.anchor}" if self.anchor else self.page_url


@dataclass
class Resource:
    """Конкретный файл или страница с текстом, которую нужно скачать."""
    url: str
    kind: str   # "pdf" | "html"
    title: str = ""


@dataclass
class TextPart:
    text: str
    page: int | None
    url: str
    title: str


@dataclass
class Finding:
    part: str
    part_ru: str | None
    role: str          # required / recommended / conditional / check
    quote: str
    source_title: str
    source_url: str
    page: int | None = None
    mentions: int = 1
