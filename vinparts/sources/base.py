"""Общий интерфейс источника. Новый источник (Toyota, ALLDATA API, папка с PDF) = новый
класс-наследник; ядро программы про конкретные сайты ничего не знает."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import DocRef, Resource, TextPart, Vehicle
from ..operations import Operation


@dataclass(frozen=True)
class SourceTerms:
    """Что разрешено делать с данными источника. Заполняется по условиям источника."""
    allows_automated_read: bool
    allows_llm: bool
    notes: str


class SourceAdapter(ABC):
    name: str
    hosts: frozenset[str]
    terms: SourceTerms

    @abstractmethod
    def supports(self, vehicle: Vehicle) -> bool:
        """Умеет ли источник работать с этой маркой."""

    @abstractmethod
    def refresh_index(self, client, store, models: list[str] | None = None,
                      include_engines: bool = False, all_models: bool = False,
                      progress=None) -> int:
        """Обновляет локальный индекс ссылок. Возвращает число найденных разделов.
        all_models: пройти страницы всех известных моделей (долго: между запросами пауза).
        progress: функция, которой сообщают о ходе работы (она же может прервать задачу)."""

    def ensure_indexed(self, client, store, vehicle: Vehicle, progress=None) -> int:
        """Перед поиском дозагружает в индекс недостающее для этой машины. По умолчанию ничего не делает."""
        return 0

    @abstractmethod
    def find_documents(self, store, vehicle: Vehicle, op: Operation) -> list[DocRef]:
        """Подбирает разделы руководств под машину и операцию (без скачивания текста)."""

    @abstractmethod
    def list_resources(self, client, doc: DocRef, limit: int = 4) -> list[Resource]:
        """Какие файлы/страницы нужно скачать, чтобы прочитать раздел."""

    @abstractmethod
    def read_resource(self, client, resource: Resource) -> list[TextPart]:
        """Скачивает и превращает ресурс в текст."""
