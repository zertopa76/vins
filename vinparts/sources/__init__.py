from __future__ import annotations

from .base import SourceAdapter, SourceTerms  # noqa: F401
from .vwts import VwtsAdapter


def all_adapters() -> list[SourceAdapter]:
    """Реестр источников. Новый источник добавляется сюда одной строкой."""
    return [VwtsAdapter()]


def allowed_hosts(adapters: list[SourceAdapter]) -> set[str]:
    hosts: set[str] = set()
    for adapter in adapters:
        hosts |= set(adapter.hosts)
    return hosts
