"""
Turns a natural-language question into a concrete plan: which entity and
which attribute of it are being asked about. If the question doesn't match
a shape we can independently verify, the plan is explicitly "no plan" -
the agent must decline rather than guess at what was meant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from factchecker.sources import ATTRIBUTE_PIDS

SUPPORTED_ATTRIBUTES = sorted(ATTRIBUTE_PIDS.keys())


@dataclass
class Plan:
    entity: str
    attribute: str
    matched_pattern: str


# Ordered (attribute, regex) pairs. Regexes are matched case-insensitively
# against the question with a trailing "?" stripped. First match wins.
_PATTERNS: list[tuple[str, str]] = [
    ("capital", r"capital(?:\s+city)?\s+of\s+(.+)"),
    ("population", r"population\s+of\s+(.+)"),
    ("currency", r"currency\s+of\s+(.+)"),
    ("official_language", r"(?:official\s+)?languages?\s+(?:of|spoken\s+in)\s+(.+)"),
    ("area", r"area\s+of\s+(.+)"),
    ("head_of_government", r"(?:current\s+)?(?:prime\s+minister|chancellor|head\s+of\s+government)\s+of\s+(.+)"),
    ("head_of_state", r"(?:current\s+)?(?:president|head\s+of\s+state)\s+of\s+(.+)"),
    ("author", r"who\s+wrote\s+(.+)"),
    ("founded", r"(?:when\s+was\s+)?(.+?)\s+(?:founded|established)\b"),
    ("birth_date", r"(?:when\s+was\s+)?(.+?)\s+born\b"),
]

_COMPILED = [(attr, re.compile(pat, re.IGNORECASE)) for attr, pat in _PATTERNS]


def _clean_entity(raw: str) -> str:
    entity = raw.strip().strip("?").strip()
    entity = re.sub(r"^(the|a|an)\s+", "", entity, flags=re.IGNORECASE)
    return entity.strip()


def make_plan(question: str) -> Optional[Plan]:
    q = question.strip()
    for attribute, pattern in _COMPILED:
        m = pattern.search(q)
        if m:
            entity = _clean_entity(m.group(1))
            if entity:
                return Plan(entity=entity, attribute=attribute, matched_pattern=pattern.pattern)
    return None
