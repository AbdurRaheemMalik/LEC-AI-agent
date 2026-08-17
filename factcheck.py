#!/usr/bin/env python3
"""
Root orchestrator - see CONTEXT.md for the routing rules this follows.

This file is deliberately thin: it loads the three stage modules (see
_stage_loader.py), calls each one's contract function in order, and prints
the combined report. All the actual planning/execution/synthesis logic
lives in 01_planning/, 02_execution/, 03_synthesis/ - each documented by
its own CONTEXT.md and implemented by its own run.py.

Usage:
    python3 factcheck.py "What is the capital of Japan?"
    python3 factcheck.py "What is the capital of France?" --simulate-failure wikidata
"""

from __future__ import annotations

import argparse
import sys

from _stage_loader import load_stage

planning = load_stage("01_planning")
execution = load_stage("02_execution")
synthesis = load_stage("03_synthesis")


def _use_color(no_color: bool) -> bool:
    return (not no_color) and sys.stdout.isatty()


def _paint(text: str, code: str, enabled: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if enabled else text


def run(question: str, csv_path: str, timeout: float, simulate_failure: str | None, no_color: bool) -> int:
    color = _use_color(no_color)
    print(f"QUESTION: {question}")

    # --- stage 1: planning --------------------------------------------
    plan = planning.make_plan(question)
    if plan.attribute is None:
        print(f"\nPLAN: no plan - {plan.reason}")
        print(f"      supported attributes: {', '.join(planning.SUPPORTED_ATTRIBUTES)}")
        print("\nVERDICT: declining to answer.")
        print("REASON: this question isn't in a shape my sources can independently verify "
              "(e.g. 'What is the capital of France?'). I won't guess rather than fabricate a plan.")
        print("SOURCES USED: none")
        print("SOURCES SKIPPED: none (stage 2/3 were never run - see CONTEXT.md: don't run later "
              "stages on a plan that doesn't exist)")
        return 2

    print(f"\nPLAN: entity='{plan.entity}', attribute='{plan.attribute}' (matched: {plan.matched_pattern})")
    print("      phase 1 (parallel): wikidata, local_csv")
    print("      phase 2 (sequential, depends on phase 1's candidate values): wikipedia corroboration")

    # --- stage 2: execution ---------------------------------------------
    results = execution.execute(plan.entity, plan.attribute, csv_path, timeout, simulate_failure)
    by_name = {r.name: r for r in results}

    print()
    status_labels = {
        "ok": _paint("OK     ", "32", color), "failed": _paint("FAILED ", "31", color),
        "timeout": _paint("TIMEOUT", "33", color), "skipped": _paint("SKIPPED", "90", color),
    }
    for r in results:
        label = status_labels.get(r.status, r.status.upper())
        print(f"[{r.name:<10}] {label}  ({r.latency_s:.2f}s)  {'-> ' + r.value if r.value else ''}  {r.detail}")

    # --- stage 3: synthesis ----------------------------------------------
    verdict = synthesis.reconcile(by_name["wikidata"], by_name["local_csv"], by_name["wikipedia"], plan.attribute)

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
    skipped = "; ".join(f"{n} ({d})" for n, d in verdict.sources_skipped) if verdict.sources_skipped else "none"
    print(f"SOURCES SKIPPED: {skipped}")

    return 0 if verdict.status == "answered" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-source fact checker that degrades gracefully.")
    parser.add_argument("question", help="A factual question, e.g. 'What is the capital of Japan?'")
    parser.add_argument("--csv", default=execution.DEFAULT_CSV_PATH, help="Path to the local reference CSV")
    parser.add_argument("--timeout", type=float, default=execution.DEFAULT_TIMEOUT, help="Per-source network timeout in seconds")
    parser.add_argument("--simulate-failure", choices=["wikidata", "wikipedia", "local_csv"], default=None,
                         help="Force one source to fail, as if its endpoint returned HTTP 500 (for demoing degradation)")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color in output")
    args = parser.parse_args()

    return run(args.question, args.csv, args.timeout, args.simulate_failure, args.no_color)


if __name__ == "__main__":
    sys.exit(main())
