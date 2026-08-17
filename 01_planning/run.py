#!/usr/bin/env python3
"""
Mechanical implementation of CONTEXT.md in this folder.

This is deterministic pattern matching, not judgment - see the "Why this
is mechanical, not judgment-based" section of CONTEXT.md for why that's a
deliberate choice, not a shortcut.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from typing import Optional

SUPPORTED_ATTRIBUTES = [
    "capital", "population", "currency", "official_language", "area",
    "head_of_government", "head_of_state", "author", "founded", "birth_date",
]

# Ordered (attribute, regex) pairs - see CONTEXT.md's process table.
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


@dataclass
class Plan:
    entity: Optional[str]
    attribute: Optional[str]
    matched_pattern: Optional[str] = None
    reason: Optional[str] = None


def _clean_entity(raw: str) -> str:
    entity = raw.strip().strip("?").strip()
    entity = re.sub(r"^(the|a|an)\s+", "", entity, flags=re.IGNORECASE)
    return entity.strip()


def make_plan(question: str) -> Plan:
    q = question.strip()
    for attribute, pattern in _COMPILED:
        m = pattern.search(q)
        if m:
            entity = _clean_entity(m.group(1))
            if entity:
                return Plan(entity=entity, attribute=attribute, matched_pattern=pattern.pattern)
    return Plan(entity=None, attribute=None, reason="question shape not recognized - doesn't match any supported attribute pattern")


def _output_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "plan.json")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: run.py \"<question>\"", file=sys.stderr)
        return 2

    question = sys.argv[1]
    plan = make_plan(question)

    with open(_output_path(), "w", encoding="utf-8") as f:
        json.dump(asdict(plan), f, indent=2)

    if plan.attribute is None:
        print(f"PLAN: no plan - {plan.reason}")
        print(f"      supported attributes: {', '.join(SUPPORTED_ATTRIBUTES)}")
        return 1

    print(f"PLAN: entity='{plan.entity}', attribute='{plan.attribute}' (matched: {plan.matched_pattern})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
