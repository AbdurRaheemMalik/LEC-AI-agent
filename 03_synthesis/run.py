#!/usr/bin/env python3
"""
Mechanical implementation of CONTEXT.md in this folder: turns stage 2's
source_results.json into a verdict.json + human-readable report. Every
branch here maps directly to a row in CONTEXT.md's decision table - no
LLM call, no fuzzy judgment, so every verdict is reproducible and its
reasoning can be read straight off this file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from typing import Optional

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
NUMERIC_ATTRIBUTES = {"population", "area"}
NUMERIC_TOLERANCE = 0.10


@dataclass
class Verdict:
    status: str  # "answered" | "declined"
    answer: Optional[str]
    confidence: Optional[str]
    reason: str
    sources_used: list = field(default_factory=list)
    sources_skipped: list = field(default_factory=list)


def values_agree(a: str, b: str, attribute: str) -> bool:
    if attribute in NUMERIC_ATTRIBUTES:
        try:
            na, nb = float(a.replace(",", "")), float(b.replace(",", ""))
        except ValueError:
            return a.strip().lower() == b.strip().lower()
        if na == 0 or nb == 0:
            return na == nb
        return abs(na - nb) / max(na, nb) <= NUMERIC_TOLERANCE
    return a.strip().lower() == b.strip().lower()


def reconcile(wikidata, csv, wikipedia, attribute: str) -> Verdict:
    """wikidata/csv/wikipedia are objects with .status/.value/.detail/.extra
    (a SimpleNamespace loaded from JSON, or the live SourceResult dataclass
    from stage 2 - both work, this function only reads attributes)."""
    structured = {"wikidata": wikidata, "local_csv": csv}
    ok = {name: r for name, r in structured.items() if r.status == "ok"}
    failed = {name: r for name, r in structured.items() if r.status != "ok"}
    sources_skipped: list = [(name, r.detail) for name, r in failed.items()]

    # --- 0 structured sources succeeded -------------------------------
    if not ok:
        sources_skipped.append(("wikipedia", wikipedia.detail))
        return Verdict(
            status="declined", answer=None, confidence=None,
            reason="No source produced a value: " + "; ".join(f"{n} ({d})" for n, d in sources_skipped),
            sources_used=[], sources_skipped=sources_skipped,
        )

    # --- exactly 1 structured source succeeded --------------------------
    if len(ok) == 1:
        (name, r), = ok.items()
        value = r.value
        if wikipedia.status == "ok":
            corroborated = name in wikipedia.extra.get("corroborated", [])
            if corroborated:
                return Verdict(
                    status="answered", answer=value, confidence="MEDIUM",
                    reason=(f"Only {name} produced a structured value ({value}); Wikipedia's summary text "
                            f"independently corroborates it, so 2 independent sources agree overall."),
                    sources_used=[name, "wikipedia"], sources_skipped=sources_skipped,
                )
            sources_skipped.append(("wikipedia", "summary text did not corroborate the value"))
            return Verdict(
                status="declined", answer=value, confidence=None,
                reason=(f"Only {name} produced a value ({value}) and Wikipedia's summary text does not "
                        f"contain it. Not independently corroborated, so not treating it as confirmed."),
                sources_used=[], sources_skipped=sources_skipped,
            )
        sources_skipped.append(("wikipedia", wikipedia.detail))
        return Verdict(
            status="declined", answer=value, confidence=None,
            reason=(f"Only {name} responded ({value}); no second source could corroborate it "
                    f"(wikipedia: {wikipedia.detail}). A single uncorroborated source is not enough to answer confidently."),
            sources_used=[], sources_skipped=sources_skipped,
        )

    # --- both structured sources succeeded -------------------------------
    wd_val, csv_val = ok["wikidata"].value, ok["local_csv"].value
    if values_agree(wd_val, csv_val, attribute):
        sources_used = ["wikidata", "local_csv"]
        reason = f"wikidata and local_csv independently agree: {wd_val}."
        if wikipedia.status == "ok":
            if wikipedia.extra.get("corroborated"):
                sources_used.append("wikipedia")
                reason += " Wikipedia's summary text also corroborates this."
            else:
                sources_skipped.append(("wikipedia", "text did not literally contain the value (soft signal, not treated as a conflict)"))
        else:
            sources_skipped.append(("wikipedia", wikipedia.detail))
        return Verdict(status="answered", answer=wd_val, confidence="HIGH", reason=reason,
                        sources_used=sources_used, sources_skipped=sources_skipped)

    # conflict between wikidata and local_csv
    tie_break = None
    if wikipedia.status == "ok":
        corroborated = set(wikipedia.extra.get("corroborated", []))
        if "wikidata" in corroborated and "local_csv" not in corroborated:
            tie_break = "wikidata"
        elif "local_csv" in corroborated and "wikidata" not in corroborated:
            tie_break = "local_csv"

    if tie_break:
        loser = "local_csv" if tie_break == "wikidata" else "wikidata"
        winner_val, loser_val = ok[tie_break].value, ok[loser].value
        return Verdict(
            status="answered", answer=winner_val, confidence="MEDIUM",
            reason=(f"wikidata and local_csv disagree (wikidata={wd_val}, local_csv={csv_val}). "
                    f"Wikipedia's summary text corroborates '{winner_val}' ({tie_break}) and not '{loser_val}' "
                    f"({loser}) - the conflict is disclosed, not hidden, and the corroborated value is used."),
            sources_used=[tie_break, "wikipedia"],
            sources_skipped=sources_skipped + [(loser, f"disagreed with the corroborated value ({loser_val})")],
        )

    wiki_note = " Wikipedia's text did not clearly support either value." if wikipedia.status == "ok" \
        else f" Wikipedia could not be used to break the tie ({wikipedia.detail})."
    return Verdict(
        status="declined", answer=None, confidence=None,
        reason=(f"wikidata and local_csv disagree (wikidata={wd_val}, local_csv={csv_val}) and no third "
                f"source can break the tie.{wiki_note} Refusing to guess which is correct."),
        sources_used=[],
        sources_skipped=[("wikidata", f"conflicting value: {wd_val}"), ("local_csv", f"conflicting value: {csv_val}"),
                          ("wikipedia", wikipedia.detail if wikipedia.status != "ok" else "inconclusive")],
    )


def format_report(verdict: Verdict) -> str:
    lines = []
    if verdict.status == "answered":
        lines.append(f"VERDICT: {verdict.answer}")
        lines.append(f"CONFIDENCE: {verdict.confidence}")
    else:
        lines.append("VERDICT: cannot answer with confidence")
        if verdict.answer:
            lines.append(f"  (unverified single-source value seen: {verdict.answer} - not reported as fact)")
    lines.append(f"REASON: {verdict.reason}")
    lines.append(f"SOURCES USED: {', '.join(verdict.sources_used) or 'none'}")
    skipped = "; ".join(f"{n} ({d})" for n, d in verdict.sources_skipped) if verdict.sources_skipped else "none"
    lines.append(f"SOURCES SKIPPED: {skipped}")
    return "\n".join(lines)


def _default_plan_path() -> str:
    return os.path.join(os.path.dirname(THIS_DIR), "01_planning", "output", "plan.json")


def _default_results_path() -> str:
    return os.path.join(os.path.dirname(THIS_DIR), "02_execution", "output", "source_results.json")


def _output_path() -> str:
    return os.path.join(THIS_DIR, "output", "verdict.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 3: reconcile source results into a verdict.")
    parser.add_argument("--plan", default=_default_plan_path())
    parser.add_argument("--results", default=_default_results_path())
    args = parser.parse_args()

    with open(args.plan, encoding="utf-8") as f:
        plan = json.load(f)
    with open(args.results, encoding="utf-8") as f:
        results = [SimpleNamespace(**r) for r in json.load(f)]

    by_name = {r.name: r for r in results}
    verdict = reconcile(by_name["wikidata"], by_name["local_csv"], by_name["wikipedia"], plan["attribute"])

    with open(_output_path(), "w", encoding="utf-8") as f:
        json.dump(asdict(verdict), f, indent=2)

    print(format_report(verdict))
    return 0 if verdict.status == "answered" else 1


if __name__ == "__main__":
    sys.exit(main())
