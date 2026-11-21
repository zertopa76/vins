"""Разбор robots.txt с поддержкой подстановок (* и $).

Стандартный urllib.robotparser не понимает пути вида /*search.html, а vwts.ru их использует,
поэтому правила разбираются здесь. Работает без внешних библиотек.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class _Group:
    agents: list[str]
    rules: list[tuple[bool, re.Pattern]] = field(default_factory=list)  # (allow?, шаблон пути)
    lengths: list[int] = field(default_factory=list)


def _compile(pattern: str) -> re.Pattern:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    body = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.compile("^" + body + ("$" if anchored else ""))


class RobotsRules:
    def __init__(self, groups: list[_Group] | None = None, *, mode: str = "rules"):
        self.groups = groups or []
        self.mode = mode  # "rules" | "allow_all" | "disallow_all"

    @classmethod
    def allow_all(cls) -> "RobotsRules":
        return cls(mode="allow_all")

    @classmethod
    def disallow_all(cls) -> "RobotsRules":
        return cls(mode="disallow_all")

    @classmethod
    def from_text(cls, text: str) -> "RobotsRules":
        groups: list[_Group] = []
        current: _Group | None = None
        last_was_rule = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            name, value = line.split(":", 1)
            name = name.strip().lower()
            value = value.strip()
            if name == "user-agent":
                if current is None or last_was_rule:
                    current = _Group(agents=[])
                    groups.append(current)
                current.agents.append(value.lower())
                last_was_rule = False
            elif name in ("allow", "disallow"):
                if current is None:
                    continue
                last_was_rule = True
                if value == "":
                    continue  # пустой Disallow = «можно всё»
                current.rules.append((name == "allow", _compile(value)))
                current.lengths.append(len(value.rstrip("$")))
            # Clean-param, Host, Sitemap и прочее игнорируем и не прерываем группу
        return cls(groups)

    def _select(self, user_agent: str) -> list[_Group]:
        ua = user_agent.lower()
        specific = [g for g in self.groups if any(a != "*" and a in ua for a in g.agents)]
        if specific:
            return specific
        return [g for g in self.groups if "*" in g.agents]

    def is_allowed(self, user_agent: str, path: str) -> bool:
        if self.mode == "allow_all":
            return True
        if self.mode == "disallow_all":
            return False
        if not path.startswith("/"):
            path = "/" + path
        best_len = -1
        best_allow = True
        for group in self._select(user_agent):
            for (allow, pattern), length in zip(group.rules, group.lengths):
                if pattern.match(path):
                    # побеждает самое длинное правило; при равенстве — разрешающее
                    if length > best_len or (length == best_len and allow):
                        best_len, best_allow = length, allow
        return best_allow
