"""Справочник операций: как их называют по-русски и по-английски, и что искать в руководстве.

Чтобы добавить операцию, достаточно добавить запись в OPERATIONS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Operation:
    id: str
    title_ru: str
    keys: tuple[tuple[str, ...], ...]   # наборы основ слов: все основы набора должны встретиться
    en_terms: tuple[str, ...]           # фразы, по которым ищем нужные страницы в руководстве
    doc_kinds: tuple[str, ...]          # какие типы документов смотреть
    title_hints: tuple[str, ...] = ()   # слова в названии раздела, которые повышают его рейтинг


OPERATIONS: tuple[Operation, ...] = (
    Operation(
        "timing_chain", "Замена цепи ГРМ",
        keys=(("цеп", "грм"), ("цеп", "газорасп"), ("timing", "chain"), ("chain", "drive")),
        en_terms=("timing chain", "chain drive", "chain tensioner", "timing gear", "sprocket",
                  "chain guide", "guide rail"),
        doc_kinds=("engine",), title_hints=("engine",),
    ),
    Operation(
        "timing_belt", "Замена ремня ГРМ",
        keys=(("ремен", "грм"), ("ремн", "грм"), ("timing", "belt"), ("toothed", "belt")),
        en_terms=("toothed belt", "timing belt", "belt tensioner", "tensioning roller",
                  "coolant pump"),
        doc_kinds=("engine",), title_hints=("engine",),
    ),
    Operation(
        "water_pump", "Замена помпы",
        keys=(("помп",), ("водян", "насос"), ("water", "pump"), ("coolant", "pump")),
        en_terms=("coolant pump", "water pump", "coolant"),
        doc_kinds=("engine",), title_hints=("engine", "cooling"),
    ),
    Operation(
        "brake_pads", "Замена тормозных колодок",
        keys=(("колод",), ("brake", "pad")),
        en_terms=("brake pad", "brake pads", "brake disc", "brake caliper", "pad wear"),
        doc_kinds=("brake", "other"), title_hints=("brake",),
    ),
    Operation(
        "clutch", "Замена сцепления",
        keys=(("сцеплен",), ("clutch",)),
        en_terms=("clutch", "release bearing", "flywheel", "pressure plate"),
        doc_kinds=("gearbox", "engine"), title_hints=("gearbox", "clutch"),
    ),
    Operation(
        "spark_plugs", "Замена свечей зажигания",
        keys=(("свеч",), ("spark", "plug")),
        en_terms=("spark plug", "ignition coil", "spark plugs"),
        doc_kinds=("engine",), title_hints=("engine", "ignition"),
    ),
    Operation(
        "oil_service", "Замена масла и фильтра",
        keys=(("замен", "масл"), ("масл", "фильтр"), ("oil", "change"), ("engine", "oil")),
        en_terms=("engine oil", "oil filter", "oil drain plug", "drain plug", "oil change"),
        doc_kinds=("maintenance", "engine"), title_hints=("maintenance",),
    ),
)


def _tokens(text: str) -> list[str]:
    text = text.lower().replace("ё", "е")
    return re.findall(r"[a-zа-я0-9]+", text)


def match_operation(text: str) -> Operation | None:
    """Находит операцию по свободному тексту. Слова сравниваются по основам, поэтому
    «цепи ГРМ», «цепь грм» и «замена цепочки ГРМ» дадут одно и то же."""
    tokens = _tokens(text)
    best: tuple[int, Operation] | None = None
    for op in OPERATIONS:
        for key in op.keys:
            if all(any(tok.startswith(stem) for tok in tokens) for stem in key):
                score = len(key)
                if best is None or score > best[0]:
                    best = (score, op)
    return best[1] if best else None
