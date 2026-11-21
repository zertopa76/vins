"""Поиск в тексте руководства пометок «заменить / менять всегда / проверить».

Работает локально и без языковой модели: регулярные выражения по типичным формулировкам
сервисных руководств (VAG и других): «Always replace…», «…must be replaced», «Do not reuse…».
Результат всегда помечается как автоматический и требует проверки по источнику.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .glossary import gloss
from .models import Finding, TextPart
from .operations import Operation

ROLE_ORDER = {"required": 0, "recommended": 1, "conditional": 2, "check": 3}
ROLE_LABEL_RU = {
    "required": "ОБЯЗАТЕЛЬНО",
    "recommended": "УКАЗАНО ЗАМЕНИТЬ",
    "conditional": "ПО СОСТОЯНИЮ",
    "check": "ПРОВЕРИТЬ",
}

# ------------------------------------------------------------------ нарезка текста


@dataclass
class Chunk:
    text: str
    page: int | None
    url: str
    title: str


def chunk_parts(parts: list[TextPart], size: int = 2200) -> list[Chunk]:
    chunks: list[Chunk] = []
    for part in parts:
        text = part.text
        if len(text) <= size:
            chunks.append(Chunk(text, part.page, part.url, part.title))
            continue
        lines = text.splitlines()
        buf: list[str] = []
        length = 0
        for line in lines:
            # режем перед новым пунктом «N - Деталь», чтобы его пометки («❑ Renew after removal»)
            # не оторвались от заголовка; если пунктов нет, режем по размеру с перекрытием
            if buf and ((length >= size and _HEADING.match(line)) or length >= size * 2):
                chunks.append(Chunk("\n".join(buf), part.page, part.url, part.title))
                keep = [] if _HEADING.match(line) else buf[-3:]
                buf, length = keep, sum(len(x) + 1 for x in keep)
            buf.append(line)
            length += len(line) + 1
        if buf:
            chunks.append(Chunk("\n".join(buf), part.page, part.url, part.title))
    return chunks


def score_chunk(text: str, terms: tuple[str, ...]) -> int:
    low = text.lower()
    distinct = sum(1 for t in terms if t in low)
    total = sum(low.count(t) for t in terms)
    score = distinct * 3 + total
    if distinct and re.search(r"assembly overview|exploded view", low):
        score += 12            # сборочный обзор узла: именно там перечислены детали и пометки о замене
    return score


def top_chunks(chunks: list[Chunk], op: Operation, k: int = 15) -> list[Chunk]:
    scored = [(score_chunk(c.text, op.en_terms), i, c) for i, c in enumerate(chunks)]
    scored = [s for s in scored if s[0] > 0]
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [c for _, _, c in scored[:k]]


# ----------------------------------------------------------------------- правила

_SENT_SPLIT = re.compile(r"(?<!e\.g)(?<!i\.e)(?<=[.!?])\s+|\s*[•■▪●◦❑□◻]\s*|\n(?=\s*[A-Z0-9\-–])")
_HYPHEN_BREAK = re.compile(r"[‐‑]\s*\n\s*")      # перенос слова в PDF: «re‐\nplaced»

_STOP = (r"(?=\s+(?:if|when|after|before|and|with|whenever|on|during|each|every|always|as|only|"
         r"because|since|once|again|in|at|by|or)\b|[.;:,)(]|$)")
_PART = r"(?P<part>[A-Za-z0-9][A-Za-z0-9 \-/']{2,60}?)"

_CONNECTORS = (r"(?:if|when|after|before|and|with|whenever|on|during|each|every|always|as|only|"
               r"because|since|once|again|in|at|by|or)")
_PAT_REPLACE_OBJ = re.compile(
    r"\b(?:always\s+)?(?:replace|renew)\s+(?!" + _CONNECTORS + r"\b)(?:the\s+|all\s+|any\s+)?"
    r"(?:with\s+new\s+)?" + _PART +
    r"(?:\s+and\s+(?:the\s+)?(?P<part2>[A-Za-z0-9][A-Za-z0-9 \-/']{2,40}?))?" + _STOP, re.I)
_PAT_BE_REPLACED = re.compile(
    _PART + r"\s+(?:must|should|have to|has to|need to|needs to|shall)\s+(?:always\s+)?(?:be\s+)?(?:replaced|renewed)\b",
    re.I)
_PAT_DASH_REPLACE = re.compile(_PART + r"\s*(?:[-–:]|,)\s*(?:always\s+)?(?:replace|renew)\b", re.I)
_PAT_DONT_REUSE = re.compile(r"\bdo not re-?use\s+(?:the\s+)?" + _PART + _STOP, re.I)
_PAT_NOT_REUSED = re.compile(_PART + r"\s+(?:must not|may not|cannot|should not)\s+be\s+re-?used", re.I)
_PAT_CHECK = re.compile(
    r"\bcheck\s+(?:the\s+)?" + _PART + r"\s+for\s+(?:wear|damage|play|scoring|cracks|leaks)", re.I)

_GENERIC = {"it", "them", "this", "these", "those", "the part", "parts", "all", "everything", "as",
            "new", "part", "the", "following", "following parts", "components", "if", "and"}

_ARTICLES = re.compile(r"^(?:the|a|an|all|any|new|old)\s+", re.I)
# если «часть» начинается с глагола, это не деталь, а следующее действие ("…and check the guide rails")
_VERBS = {"check", "inspect", "remove", "install", "fit", "clean", "tighten", "observe", "mark", "note",
          "use", "apply", "insert", "lubricate", "ensure", "make", "adjust", "measure", "fill", "bleed"}


def sentences(text: str) -> list[str]:
    out = []
    for piece in _SENT_SPLIT.split(_HYPHEN_BREAK.sub("", text)):
        s = re.sub(r"\s+", " ", piece).strip(" -–\t")
        if 3 <= len(s) <= 400:
            out.append(s)
    return out


def _clean_part(raw: str, *, from_end: bool) -> list[str]:
    raw = _ARTICLES.sub("", raw.strip())
    pieces = re.split(r"\s+and\s+|,\s*|\s*/\s*(?=\w+\s)", raw)
    result = []
    for piece in pieces:
        words = _ARTICLES.sub("", piece.strip()).split()
        if not words:
            continue
        words = words[-5:] if from_end else words[:5]
        name = " ".join(words).strip(" -–'")
        if len(name) < 3 or name.lower() in _GENERIC or not re.search(r"[A-Za-z]{3}", name):
            continue
        if words[0].lower() in _VERBS:
            continue
        result.append(name)
    return result


def _role(sentence: str) -> str:
    s = sentence.lower()
    if (re.search(r"\b(?:do not|must not|never|may not|cannot|should not)\b[^.]{0,25}\bre-?us", s)
            or "non-reusable" in s or "single-use" in s or "one-time use" in s):
        return "required"
    # безусловные формулировки
    if re.search(r"\b(?:always|each time|every time|whenever)\b", s):
        return "required"
    if re.search(r"after\s+(?:each\s+|every\s+)?(?:removal|removing|disassembly|dismantling)", s):
        return "required"
    # условие («if/when…») сильнее слова «must», но слабее «always»
    if re.search(r"\b(?:if|when|as necessary|as required|depending|in case|provided that|where)\b", s):
        return "conditional"
    if re.search(r"\b(?:must|mandatory|necessarily|shall)\b", s):
        return "required"
    if re.search(r"\b(?:should|recommended|advisable|better to)\b", s):
        return "recommended"
    return "recommended"


def extract_from_sentence(sentence: str) -> list[tuple[str, str]]:
    """Возвращает [(название_детали, роль), ...] для одного предложения."""
    found: list[tuple[str, str]] = []
    base_role = _role(sentence)

    def add(match, from_end: bool, role: str | None = None):
        for group in ("part", "part2"):
            raw = match.groupdict().get(group)
            if not raw:
                continue
            for name in _clean_part(raw, from_end=from_end):
                found.append((name, role or base_role))

    for m in _PAT_REPLACE_OBJ.finditer(sentence):
        add(m, from_end=False)
    for m in _PAT_BE_REPLACED.finditer(sentence):
        add(m, from_end=True)
    for m in _PAT_DASH_REPLACE.finditer(sentence):
        add(m, from_end=True)
    for m in _PAT_DONT_REUSE.finditer(sentence):
        add(m, from_end=False, role="required")
    for m in _PAT_NOT_REUSED.finditer(sentence):
        add(m, from_end=True, role="required")
    for m in _PAT_CHECK.finditer(sentence):
        add(m, from_end=False, role="check")
    return found


def _norm(name: str) -> str:
    low = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    return re.sub(r"s\b", "", low)  # bolts == bolt


_HEADING = re.compile(r"^\s*\d{1,2}\s*[-–]\s*([A-Za-z][A-Za-z0-9 \-/,'()]{2,60}?)\s*$")
_BARE_REPLACE = re.compile(r"^\s*(?:(?:always|must always)\s+)?(?:replace|renew)(?:d)?\b", re.I)
_BARE_CHECK = re.compile(r"^\s*(?:check|inspect)\b[^.]{0,30}\b(?:wear|damage|play|scoring|cracks|leaks)\b", re.I)
_TORQUE = re.compile(r"\d+(?:[.,]\d+)?\s*Nm(?:\s*\+\s*\d+\s*°)?")
_GENERIC_ITEMS = {"bolt", "bolts", "nut", "nuts", "stud", "studs", "screw", "screws", "washer", "clip", "clips"}
_SKIP_HEADINGS = {"notes", "note", "legend", "general", "key"}


def blocks(text: str) -> list[tuple[str | None, str]]:
    """Делит текст по нумерованным заголовкам узлов («1 - Chain tensioner», как в сборочных
    обзорах VAG): пометка «Replace…» без названия детали относится к последнему заголовку."""
    result: list[tuple[str | None, str]] = []
    heading: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            if buf:
                result.append((heading, "\n".join(buf)))
                buf = []
            name = m.group(1).strip(" -–,'")
            heading = None if name.lower() in _SKIP_HEADINGS else name
            continue
        buf.append(line)
    if buf:
        result.append((heading, "\n".join(buf)))
    return result


def find_findings(chunks: list[Chunk]) -> list[Finding]:
    merged: dict[str, Finding] = {}
    for chunk in chunks:
        for heading, block in blocks(chunk.text):
            for sent in sentences(block):
                results = extract_from_sentence(sent)
                from_heading = False
                if not results and heading and _BARE_REPLACE.match(sent):
                    role = _role(sent)
                    results = [(name, role) for name in _clean_part(heading, from_end=False)]
                    from_heading = True
                elif not results and heading and _BARE_CHECK.match(sent):
                    results = [(name, "check") for name in _clean_part(heading, from_end=False)]
                    from_heading = True
                for name, role in results:
                    quote = sent if len(sent) <= 220 else sent[:217] + "…"
                    if from_heading:
                        # деталь взята из заголовка узла над пометкой. «Bolt», «Nut» без уточнения ничего не
                        # говорят, поэтому такие детали различаем по моменту затяжки из того же пункта
                        torque = _TORQUE.search(block)
                        if torque and name.lower() in _GENERIC_ITEMS:
                            name = f"{name} ({re.sub(r'\s+', ' ', torque.group(0))})"
                        # соседние пометки того же пункта; строки оглавления («⇒ page», «2.3 …») не берём
                        others = [s for s in sentences(block)
                                  if s != sent and "⇒" not in s and not re.match(r"\d+(?:\.\d+)+\s", s)
                                  and len(s) <= 120][:3]
                        quote = f"{heading}: {quote}" + (f" ({'; '.join(others)})" if others else "")
                        if len(quote) > 260:
                            quote = quote[:257] + "…"
                    key = _norm(name)
                    existing = merged.get(key)
                    if existing is None:
                        merged[key] = Finding(name, gloss(name), role, quote, chunk.title, chunk.url, chunk.page)
                    else:
                        existing.mentions += 1
                        if ROLE_ORDER[role] < ROLE_ORDER[existing.role]:
                            existing.role, existing.quote = role, quote
                            existing.source_title, existing.source_url, existing.page = (
                                chunk.title, chunk.url, chunk.page)
    findings = list(merged.values())
    findings.sort(key=lambda f: (ROLE_ORDER[f.role], -f.mentions, f.part.lower()))
    return findings


def analyze(parts: list[TextPart], op: Operation, top_k: int = 15) -> list[Finding]:
    chunks = top_chunks(chunk_parts(parts), op, k=top_k)
    return find_findings(chunks)
