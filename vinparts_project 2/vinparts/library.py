"""Библиотека руководств: PDF, которые пользователь сам скачал в обычном браузере.

Зачем: vwts.ru на ссылку PDF отдаёт страницу «Скачивание файла…» с отсчётом, а не сам файл.
Программа не притворяется браузером и страницу не обходит. Вместо этого файл один раз скачивается
человеком в браузере и кладётся сюда; дальше поиск читает его локально и к сайту за ним не ходит.

Файл сопоставляется со ссылкой по имени: у `https://vwts.ru/…/vw-golf-7-maintenance-eng.pdf`
ожидается файл `vw-golf-7-maintenance-eng.pdf`. Браузерные приписки « (1)» к имени не мешают.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from .readers import pdf_problem

MAX_FILE_BYTES = 80 * 1024 * 1024
_COPY_SUFFIX = re.compile(r"(?:\s*\(\d{1,3}\)|\s\d{1,3})$")
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class LibraryError(Exception):
    pass


@dataclass(frozen=True)
class LibraryFile:
    name: str
    size: int
    added: float


def basename_of(url_or_name: str) -> str:
    """Имя файла из ссылки или пути: без каталогов, #фрагмента и ?параметров."""
    text = url_or_name.strip()
    if "://" in text:
        text = unquote(urlparse(text).path)
    text = text.replace("\\", "/").rsplit("/", 1)[-1]
    return text.strip()


def key_of(url_or_name: str) -> str:
    """Имя для сравнения: без регистра, без «.pdf» и без « (1)», которое добавляет браузер."""
    name = basename_of(url_or_name).lower()
    if name.endswith(".pdf"):
        name = name[:-4]
    name = _COPY_SUFFIX.sub("", name.rstrip())
    return name.strip()


def clean_name(filename: str) -> str:
    name = _BAD_CHARS.sub("_", basename_of(filename)).strip(" .")
    if not name:
        raise LibraryError("У файла нет имени.")
    if not name.lower().endswith(".pdf"):
        raise LibraryError(f"«{name}»: в библиотеку добавляются только PDF-файлы.")
    return name


class Library:
    def __init__(self, folder: str | os.PathLike):
        self.folder = Path(folder)

    def _ensure(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)

    def _files(self) -> list[Path]:
        if not self.folder.is_dir():
            return []
        return [p for p in self.folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]

    def add(self, filename: str, data: bytes) -> LibraryFile:
        name = clean_name(filename)
        if not data:
            raise LibraryError(f"«{name}»: файл пустой.")
        if len(data) > MAX_FILE_BYTES:
            raise LibraryError(f"«{name}»: файл больше 80 МБ.")
        problem = pdf_problem(data)
        if problem:
            if b"<html" in data[:2048].lower() or b"<!doctype" in data[:2048].lower():
                raise LibraryError(
                    f"«{name}»: это веб-страница, а не PDF (скорее всего, страница ожидания скачивания). "
                    "Дождитесь окончания отсчёта на странице сайта и нажмите там ссылку на файл.")
            raise LibraryError(f"«{name}»: {problem}")
        if b"%%EOF" not in data[-2048:]:
            raise LibraryError(f"«{name}»: файл скачан не полностью. Скачайте его ещё раз.")
        self._ensure()
        key = key_of(name)
        for old in self._files():                    # тот же документ под другим именем не копим
            if key_of(old.name) == key and old.name != name:
                old.unlink(missing_ok=True)
        target = self.folder / name
        fd, tmp = tempfile.mkstemp(dir=self.folder, suffix=".part")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        stat = target.stat()
        return LibraryFile(name, stat.st_size, stat.st_mtime)

    def find(self, url_or_name: str) -> Path | None:
        key = key_of(url_or_name)
        if not key:
            return None
        for path in sorted(self._files()):
            if key_of(path.name) == key:
                return path
        return None

    def read(self, url_or_name: str) -> bytes | None:
        path = self.find(url_or_name)
        if path is None:
            return None
        try:
            return path.read_bytes()
        except OSError:
            return None

    def list(self) -> list[LibraryFile]:
        out = []
        for path in self._files():
            stat = path.stat()
            out.append(LibraryFile(path.name, stat.st_size, stat.st_mtime))
        return sorted(out, key=lambda f: f.name.lower())

    def remove(self, filename: str) -> bool:
        path = self.folder / Path(filename).name
        if path.is_file() and path.suffix.lower() == ".pdf" and path.parent == self.folder:
            path.unlink()
            return True
        return False

