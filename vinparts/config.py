"""Общие настройки: имя программы (User-Agent), папка данных, лимиты вежливости."""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "VinPartsHelper"
APP_VERSION = "0.1.0"

DEFAULT_DELAY_SECONDS = 4.0          # пауза между запросами к одному сайту
DEFAULT_TTL_HOURS = 24 * 7           # сколько хранить страницу в локальном кэше
DEFAULT_MAX_BYTES = 80 * 1024 * 1024  # максимальный размер одного скачиваемого файла


def user_agent() -> str:
    """Честное имя программы. Контакт (e-mail/сайт) берётся из VINPARTS_CONTACT,
    чтобы владелец сайта мог с вами связаться. Под поисковых роботов не маскируемся."""
    ua = f"{APP_NAME}/{APP_VERSION} (personal workshop tool; rate-limited)"
    contact = os.environ.get("VINPARTS_CONTACT", "").strip()
    if contact:
        ua += f" contact: {contact}"
    return ua


def data_dir(override: str | os.PathLike | None = None) -> Path:
    """Папка для индекса и кэша. Можно переопределить: --data-dir или VINPARTS_HOME."""
    base = override or os.environ.get("VINPARTS_HOME") or user_data_dir(APP_NAME, appauthor=False)
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path
