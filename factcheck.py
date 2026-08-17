#!/usr/bin/env python3
"""
Multi-source fact checker that degrades gracefully.

Usage:
    python3 factcheck.py "What is the capital of Japan?"
    python3 factcheck.py "What is the capital of France?" --simulate-failure wikidata
    python3 factcheck.py "What is the population of Germany?" --csv data/local_facts.csv

See README.md for the full design writeup and the demo script.
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from factchecker import planner, synth
from factchecker.sources import DEFAULT_TIMEOUT, SourceResult, csv_source, wikidata_source, wikipedia_source

DEFAULT_CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "local_facts.csv")


def _use_color(no_color: bool) -> bool:
    return (not no_color) and sys.stdout.isatty()


def _paint(text: str, code: str, enabled: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if enabled else text


def _status_label(status: str, color: bool) -> str:
    return {
        "ok": _paint("OK     ", "32", color),
        "failed": _paint("FAILED ", "31", color),
        "timeout": _paint("TIMEOUT", "33", color),
        "skipped": _paint("SKIPPED", "90", color),
    }.get(status, status.upper())


def run(question: str, csv_path: str, timeout: float, simulate_failure: str | None, no_color: bool) -> int:
    color = _use_color(no_color)
    print(f"QUESTION: {question}")

    plan = planner.make_plan(question)
    if plan is None:
        print("\nPLAN: could not map this question to a verifiable (entity, attribute) pair.")
        print(f"      Supported attributes: {', '.join(planner.SUPPORTED_ATTRIBUTES)}")
        print("\nVERDICT: declining to answer.")
        print("REASON: this question isn't in a shape my sources can independently verify "
              "(e.g. 'What is the capital of France?'). I won't guess rather than fabricate a plan.")
        print("SOURCES USED: none   SOURCES SKIPPED: none (no plan was made)")
        return 2

    print(f"\nPLAN: entity='{plan.entity}', attribute='{plan.attribute}'")
    print(f"      phase 1 (parallel): wikidata, local_csv")
    print(f"      phase 2 (sequential, depends on phase 1's candidate values): wikipedia corroboration")

    # --- phase 1: independent structured sources, run in parallel ---------
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_wd = pool.submit(wikidata_source, plan.entity, plan.attribute, timeout, simulate_failure == "wikidata")
        fut_csv = pool.submit(csv_source, plan.entity, plan.attribute, csv_path, simulate_failure == "local_csv")
        wikidata_result: SourceResult = fut_wd.result()
        csv_result: SourceResult = fut_csv.result()

    # --- phase 2: wikipedia corroborates whatever candidates phase 1 found -
    candidates = {name: r.value for name, r in (("wikidata", wikidata_result), ("local_csv", csv_result)) if r.status == "ok"}
    if candidates:
        wikipedia_result = wikipedia_source(plan.entity, candidates, timeout, simulate_failure == "wikipedia")
    else:
        wikipedia_result = None  # nothing to corroborate; don't even make the call

    print()
    for r in (wikidata_result, csv_result):
        print(f"[{r.name:<10}] {_status_label(r.status, color)}  ({r.latency_s:.2f}s)  "
              f"{'-> ' + r.value if r.value else ''}  {r.detail}")
    if wikipedia_result is not None:
        r = wikipedia_result
        print(f"[{r.name:<10}] {_status_label(r.status, color)}  ({r.latency_s:.2f}s)  "
              f"{'-> ' + r.value if r.value else ''}  {r.detail}")
    else:
        print(f"[wikipedia ] {_status_label('skipped', color)}  (0.00s)  no candidate values to corroborate")

    verdict = synth.reconcile(wikidata_result, csv_result, wikipedia_result, plan.attribute)

    print()
    if verdict.status == "answered":
        print(f"VERDICT: {_paint(verdict.answer, '1;32', color)}")
        print(f"CONFIDENCE: {verdict.confidence}")
    else:
        print(_paint("VERDICT: cannot answer with confidence", "1;31", color))
        if verdict.answer:
            print(f"  (unverified single-source value seen: {verdict.answer} - not reported as fact)")
    print(f"REASON: {verdict.reason}")
    print(f"SOURCES USED: {', '.join(verdict.sources_used) or 'none'}")
    if verdict.sources_skipped:
        skipped_str = "; ".join(f"{n} ({d})" for n, d in verdict.sources_skipped)
        print(f"SOURCES SKIPPED: {skipped_str}")
    else:
        print("SOURCES SKIPPED: none")

    return 0 if verdict.status == "answered" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-source fact checker that degrades gracefully.")
    parser.add_argument("question", help="A factual question, e.g. 'What is the capital of Japan?'")
    parser.add_argument("--csv", default=DEFAULT_CSV_PATH, help="Path to the local reference CSV (default: data/local_facts.csv)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Per-source network timeout in seconds")
    parser.add_argument("--simulate-failure", choices=["wikidata", "wikipedia", "local_csv"], default=None,
                         help="Force one source to fail, as if its endpoint returned HTTP 500 (for demoing degradation)")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color in output")
    args = parser.parse_args()

    return run(args.question, args.csv, args.timeout, args.simulate_failure, args.no_color)


if __name__ == "__main__":
    sys.exit(main())
