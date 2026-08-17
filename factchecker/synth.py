"""
Deterministic synthesis: turns a set of SourceResults into a Verdict.

No LLM, no fuzzy "vibes" - every branch here is an explicit, inspectable
rule, because the brief requires every answer (or refusal) to be
justifiable by naming which sources were used, which were skipped, and why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from factchecker.sources import SourceResult

NUMERIC_ATTRIBUTES = {"population", "area"}
NUMERIC_TOLERANCE = 0.10  # sources rarely agree on population to the digit


@dataclass
class Verdict:
    status: str  # "answered" | "declined"
    answer: Optional[str]
    confidence: Optional[str]  # "HIGH" | "MEDIUM" | None
    reason: str
    sources_used: list[str] = field(default_factory=list)
    sources_skipped: list[tuple[str, str]] = field(default_factory=list)


def values_agree(a: str, b: str, attribute: str) -> bool:
    if attribute in NUMERIC_ATTRIBUTES:
        try:
            na = float(a.replace(",", ""))
            nb = float(b.replace(",", ""))
        except ValueError:
            return a.strip().lower() == b.strip().lower()
        if na == 0 or nb == 0:
            return na == nb
        return abs(na - nb) / max(na, nb) <= NUMERIC_TOLERANCE
    return a.strip().lower() == b.strip().lower()


def reconcile(wikidata: SourceResult, csv: SourceResult, wikipedia: Optional[SourceResult], attribute: str) -> Verdict:
    structured = {"wikidata": wikidata, "local_csv": csv}
    ok = {name: r for name, r in structured.items() if r.status == "ok"}
    failed = {name: r for name, r in structured.items() if r.status != "ok"}
    sources_skipped: list[tuple[str, str]] = [(name, r.detail) for name, r in failed.items()]

    # --- 0 structured sources succeeded -----------------------------------
    if not ok:
        if wikipedia is not None:
            sources_skipped.append(("wikipedia", "no candidate values to corroborate (wikidata and local_csv both failed)"))
        return Verdict(
            status="declined", answer=None, confidence=None,
            reason="No source produced a value: " + "; ".join(f"{n} ({d})" for n, d in sources_skipped),
            sources_used=[], sources_skipped=sources_skipped,
        )

    # --- exactly 1 structured source succeeded -----------------------------
    if len(ok) == 1:
        (name, r), = ok.items()
        value = r.value
        if wikipedia is not None and wikipedia.status == "ok":
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
        wiki_reason = wikipedia.detail if wikipedia is not None else "not queried"
        sources_skipped.append(("wikipedia", wiki_reason))
        return Verdict(
            status="declined", answer=value, confidence=None,
            reason=(f"Only {name} responded ({value}); no second source could corroborate it "
                    f"(wikipedia: {wiki_reason}). A single uncorroborated source is not enough to answer confidently."),
            sources_used=[], sources_skipped=sources_skipped,
        )

    # --- both structured sources succeeded ---------------------------------
    wd_val, csv_val = ok["wikidata"].value, ok["local_csv"].value
    if values_agree(wd_val, csv_val, attribute):
        sources_used = ["wikidata", "local_csv"]
        reason = f"wikidata and local_csv independently agree: {wd_val}."
        if wikipedia is not None and wikipedia.status == "ok":
            if wikipedia.extra.get("corroborated"):
                sources_used.append("wikipedia")
                reason += " Wikipedia's summary text also corroborates this."
            else:
                sources_skipped.append(("wikipedia", "text did not literally contain the value (soft signal, not treated as a conflict)"))
        elif wikipedia is not None:
            sources_skipped.append(("wikipedia", wikipedia.detail))
        return Verdict(status="answered", answer=wd_val, confidence="HIGH", reason=reason,
                        sources_used=sources_used, sources_skipped=sources_skipped)

    # conflict between wikidata and local_csv
    tie_break = None
    if wikipedia is not None and wikipedia.status == "ok":
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

    wiki_note = ""
    if wikipedia is not None and wikipedia.status == "ok":
        wiki_note = " Wikipedia's text did not clearly support either value."
    elif wikipedia is not None:
        wiki_note = f" Wikipedia could not be used to break the tie ({wikipedia.detail})."
    return Verdict(
        status="declined", answer=None, confidence=None,
        reason=(f"wikidata and local_csv disagree (wikidata={wd_val}, local_csv={csv_val}) and no third "
                f"source can break the tie.{wiki_note} Refusing to guess which is correct."),
        sources_used=[],
        sources_skipped=[("wikidata", f"conflicting value: {wd_val}"), ("local_csv", f"conflicting value: {csv_val}")]
        + ([("wikipedia", wikipedia.detail if wikipedia.status != 'ok' else 'inconclusive')] if wikipedia is not None else []),
    )
