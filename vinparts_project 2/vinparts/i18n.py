"""Тексты сообщений программы на двух языках (русский / английский).

Названия деталей и цитаты из руководств берутся из самих руководств (они английские) и здесь не
переводятся: для них есть словарь `glossary` и подпись «оригинал» в окне.
"""

from __future__ import annotations

LANGS = ("ru", "en")

MESSAGES: dict[str, dict[str, str]] = {
    "no_docs": {
        "ru": "[{src}] подходящих разделов в индексе нет. Выполните `index` для этой модели "
              "(и `--engines`, если нужен двигатель) и проверьте код двигателя.",
        "en": "[{src}] no matching sections in the index. Run `index` for this model "
              "(and `--engines` if you need an engine) and check the engine code.",
    },
    "skipped": {
        "ru": "[{src}] {doc}: пропущено по вашему выбору.",
        "en": "[{src}] {doc}: skipped at your choice.",
    },
    "lib_unreadable": {
        "ru": "[{src}] файл «{name}» из библиотеки не читается: {err}",
        "en": "[{src}] library file “{name}” cannot be read: {err}",
    },
    "no_text": {
        "ru": "[{src}] {name}: текста не найдено (скан или пустая страница).",
        "en": "[{src}] {name}: no text found (a scan or an empty page).",
    },
    "cant_read": {
        "ru": "[{src}] {name}: не удалось прочитать ({err})",
        "en": "[{src}] {name}: could not be read ({err})",
    },
    "op_unknown": {
        "ru": "Операция не распознана. Выберите её из списка или опишите иначе, например «цепь грм».",
        "en": "The operation was not recognized. Pick it from the list or describe it differently, "
              "for example “timing chain”.",
    },
    "year_bad": {"ru": "Год указан неверно.", "en": "The year is invalid."},
    "need_model": {"ru": "Укажите модель или код двигателя.",
                   "en": "Enter a model or an engine code."},
    "index_start": {
        "ru": "[{src}] обновляю индекс; между запросами пауза {delay:g} с.",
        "en": "[{src}] updating the index; {delay:g} s pause between requests.",
    },
    "index_failed": {
        "ru": "[{src}] не удалось дозагрузить список разделов: {err}",
        "en": "[{src}] could not load the section list: {err}",
    },
    "request_taken": {"ru": "Запрос принят.", "en": "Request accepted."},
}


def tr(lang: str, key: str, **kwargs) -> str:
    entry = MESSAGES[key]
    text = entry.get(lang) or entry["ru"]
    return text.format(**kwargs) if kwargs else text


def norm_lang(value) -> str:
    return value if value in LANGS else "ru"
