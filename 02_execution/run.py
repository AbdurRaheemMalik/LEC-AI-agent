#!/usr/bin/env python3
"""
Mechanical implementation of CONTEXT.md in this folder: query Wikidata and
local_csv in parallel (phase 1), then Wikipedia in sequence to corroborate
whatever phase 1 found (phase 2). See CONTEXT.md for why the ordering is
deliberate, not incidental.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Optional

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TIMEOUT = 6.0
DEFAULT_CSV_PATH = os.path.join(THIS_DIR, "references", "local_facts.csv")

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_SUMMARY_API = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

# attribute -> (Wikidata property id, value kind). Mirrors _config/glossary.md.
ATTRIBUTE_PIDS = {
    "capital": ("P36", "entity"),
    "population": ("P1082", "quantity"),
    "currency": ("P38", "entity"),
    "official_language": ("P37", "entity"),
    "area": ("P2046", "quantity"),
    "head_of_government": ("P6", "entity"),
    "head_of_state": ("P35", "entity"),
    "founded": ("P571", "time"),
    "author": ("P50", "entity"),
    "birth_date": ("P569", "time"),
}


@dataclass
class SourceResult:
    name: str
    status: str  # "ok" | "failed" | "timeout" | "skipped"
    value: Optional[str] = None
    detail: str = ""
    latency_s: float = 0.0
    extra: dict = field(default_factory=dict)


def _http_get_json(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": "multi-source-fact-checker/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw)


def _raise_simulated_failure():
    raise urllib.error.HTTPError(
        url=None, code=500, msg="Simulated Internal Server Error (--simulate-failure)", hdrs=None, fp=None
    )


# ---------------------------------------------------------------------------
# Wikidata
# ---------------------------------------------------------------------------

def _wikidata_search_entity(name: str, timeout: float) -> Optional[str]:
    params = urllib.parse.urlencode(
        {"action": "wbsearchentities", "search": name, "language": "en", "format": "json", "limit": 1}
    )
    data = _http_get_json(f"{WIKIDATA_API}?{params}", timeout)
    results = data.get("search") or []
    return results[0]["id"] if results else None


def _wikidata_get_claims(qid: str, timeout: float) -> dict:
    params = urllib.parse.urlencode({"action": "wbgetentities", "ids": qid, "props": "claims", "format": "json"})
    data = _http_get_json(f"{WIKIDATA_API}?{params}", timeout)
    return data["entities"][qid]["claims"]


def _wikidata_get_labels(qids: list[str], timeout: float) -> dict[str, str]:
    if not qids:
        return {}
    params = urllib.parse.urlencode(
        {"action": "wbgetentities", "ids": "|".join(qids), "props": "labels", "languages": "en", "format": "json"}
    )
    data = _http_get_json(f"{WIKIDATA_API}?{params}", timeout)
    return {qid: ent.get("labels", {}).get("en", {}).get("value") or qid for qid, ent in data.get("entities", {}).items()}


def _select_current_claim(claims: list[dict]) -> Optional[dict]:
    """See _config/glossary.md 'current value selection' for the rule this implements."""
    candidates = [c for c in claims if c.get("rank") != "deprecated"]
    candidates = [c for c in candidates if "P582" not in c.get("qualifiers", {})]
    if not candidates:
        return None
    preferred = [c for c in candidates if c.get("rank") == "preferred"]
    pool = preferred or candidates
    if len(pool) == 1:
        return pool[0]

    def sort_key(c):
        quals = c.get("qualifiers", {})
        for pid in ("P585", "P580"):
            if pid in quals:
                return quals[pid][0]["datavalue"]["value"]["time"]
        return ""

    pool.sort(key=sort_key, reverse=True)
    return pool[0]


def _format_time_value(value: dict) -> str:
    raw = value["time"].lstrip("+")
    precision = value.get("precision", 11)
    if precision <= 9:
        return raw.split("-")[0]
    parts = raw.split("T")[0].split("-")
    return f"{parts[0]}-{parts[1]}-{parts[2]}"


def wikidata_source(entity: str, attribute: str, timeout: float = DEFAULT_TIMEOUT, simulate_failure: bool = False) -> SourceResult:
    start = time.monotonic()
    try:
        if simulate_failure:
            _raise_simulated_failure()

        pid, kind = ATTRIBUTE_PIDS[attribute]
        qid = _wikidata_search_entity(entity, timeout)
        if qid is None:
            return SourceResult("wikidata", "failed", detail=f"no Wikidata entity found for '{entity}'", latency_s=time.monotonic() - start)

        claims = _wikidata_get_claims(qid, timeout)
        claim = _select_current_claim(claims.get(pid, []))
        if claim is None:
            return SourceResult("wikidata", "failed", detail=f"'{entity}' has no current {attribute} claim on Wikidata", latency_s=time.monotonic() - start)

        datavalue = claim["mainsnak"]["datavalue"]["value"]
        if kind == "entity":
            value_qid = datavalue["id"]
            display = _wikidata_get_labels([value_qid], timeout).get(value_qid, value_qid)
        elif kind == "quantity":
            display = str(int(round(float(datavalue["amount"]))))
        elif kind == "time":
            display = _format_time_value(datavalue)
        else:
            display = str(datavalue)

        return SourceResult("wikidata", "ok", value=display, detail=f"Wikidata entity {qid}, property {pid}", latency_s=time.monotonic() - start)

    except (socket.timeout, TimeoutError):
        return SourceResult("wikidata", "timeout", detail=f"timed out after {timeout}s", latency_s=time.monotonic() - start)
    except urllib.error.HTTPError as e:
        return SourceResult("wikidata", "failed", detail=f"HTTP {e.code}: {getattr(e, 'reason', e.msg)}", latency_s=time.monotonic() - start)
    except urllib.error.URLError as e:
        return SourceResult("wikidata", "failed", detail=f"network error: {e.reason}", latency_s=time.monotonic() - start)
    except Exception as e:  # noqa: BLE001 - a failed source must never crash the run
        return SourceResult("wikidata", "failed", detail=f"unexpected error: {e}", latency_s=time.monotonic() - start)


# ---------------------------------------------------------------------------
# Wikipedia (corroboration only - see CONTEXT.md)
# ---------------------------------------------------------------------------

def wikipedia_source(entity: str, candidates: dict[str, str], timeout: float = DEFAULT_TIMEOUT, simulate_failure: bool = False) -> SourceResult:
    start = time.monotonic()
    try:
        if simulate_failure:
            _raise_simulated_failure()

        title = urllib.parse.quote(entity.replace(" ", "_"))
        data = _http_get_json(WIKIPEDIA_SUMMARY_API.format(title=title), timeout)
        extract = data.get("extract", "")
        if not extract:
            return SourceResult("wikipedia", "failed", detail="page found but had no summary text", latency_s=time.monotonic() - start)

        matches = {src: (val.lower() in extract.lower()) for src, val in candidates.items() if val}
        corroborated = [src for src, ok in matches.items() if ok]
        snippet = extract[:220] + ("..." if len(extract) > 220 else "")

        return SourceResult(
            "wikipedia", "ok",
            value="; ".join(f"{src}:{'match' if ok else 'no match'}" for src, ok in matches.items()) or "no candidates to check",
            detail=snippet, latency_s=time.monotonic() - start,
            extra={"matches": matches, "corroborated": corroborated},
        )

    except (socket.timeout, TimeoutError):
        return SourceResult("wikipedia", "timeout", detail=f"timed out after {timeout}s", latency_s=time.monotonic() - start)
    except urllib.error.HTTPError as e:
        detail = "page not found on Wikipedia" if e.code == 404 else f"HTTP {e.code}: {getattr(e, 'reason', e.msg)}"
        return SourceResult("wikipedia", "failed", detail=detail, latency_s=time.monotonic() - start)
    except urllib.error.URLError as e:
        return SourceResult("wikipedia", "failed", detail=f"network error: {e.reason}", latency_s=time.monotonic() - start)
    except Exception as e:  # noqa: BLE001
        return SourceResult("wikipedia", "failed", detail=f"unexpected error: {e}", latency_s=time.monotonic() - start)


# ---------------------------------------------------------------------------
# local_csv
# ---------------------------------------------------------------------------

def csv_source(entity: str, attribute: str, csv_path: str, simulate_failure: bool = False) -> SourceResult:
    start = time.monotonic()
    try:
        if simulate_failure:
            raise RuntimeError("Simulated failure (--simulate-failure)")

        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["entity"].strip().lower() == entity.strip().lower() and row["attribute"].strip().lower() == attribute.strip().lower():
                    return SourceResult("local_csv", "ok", value=row["value"].strip(), detail=f"row matched in {csv_path}", latency_s=time.monotonic() - start)
        return SourceResult("local_csv", "failed", detail=f"no row for entity='{entity}', attribute='{attribute}' in {csv_path}", latency_s=time.monotonic() - start)

    except FileNotFoundError:
        return SourceResult("local_csv", "failed", detail=f"file not found: {csv_path}", latency_s=time.monotonic() - start)
    except Exception as e:  # noqa: BLE001
        return SourceResult("local_csv", "failed", detail=f"unexpected error: {e}", latency_s=time.monotonic() - start)


# ---------------------------------------------------------------------------
# orchestration: phase 1 parallel, phase 2 sequential (see CONTEXT.md)
# ---------------------------------------------------------------------------

def execute(entity: str, attribute: str, csv_path: str = DEFAULT_CSV_PATH, timeout: float = DEFAULT_TIMEOUT,
            simulate_failure: Optional[str] = None) -> list[SourceResult]:
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_wd = pool.submit(wikidata_source, entity, attribute, timeout, simulate_failure == "wikidata")
        fut_csv = pool.submit(csv_source, entity, attribute, csv_path, simulate_failure == "local_csv")
        wikidata_result = fut_wd.result()
        csv_result = fut_csv.result()

    candidates = {name: r.value for name, r in (("wikidata", wikidata_result), ("local_csv", csv_result)) if r.status == "ok"}
    if candidates:
        wikipedia_result = wikipedia_source(entity, candidates, timeout, simulate_failure == "wikipedia")
    else:
        wikipedia_result = SourceResult("wikipedia", "skipped", detail="no candidate values to corroborate (wikidata and local_csv both failed)")

    return [wikidata_result, csv_result, wikipedia_result]


def _plan_path() -> str:
    return os.path.join(os.path.dirname(THIS_DIR), "01_planning", "output", "plan.json")


def _output_path() -> str:
    return os.path.join(THIS_DIR, "output", "source_results.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 2: execute queries against the sources named in a plan.")
    parser.add_argument("--plan", default=_plan_path(), help="Path to plan.json from stage 1")
    parser.add_argument("--csv", default=DEFAULT_CSV_PATH, help="Path to the local reference CSV")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--simulate-failure", choices=["wikidata", "wikipedia", "local_csv"], default=None)
    args = parser.parse_args()

    with open(args.plan, encoding="utf-8") as f:
        plan = json.load(f)
    if not plan.get("attribute"):
        print(f"no plan to execute: {plan.get('reason', 'unknown')}", file=sys.stderr)
        return 2

    results = execute(plan["entity"], plan["attribute"], args.csv, args.timeout, args.simulate_failure)

    with open(_output_path(), "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, indent=2)

    for r in results:
        print(f"[{r.name:<10}] {r.status.upper():<8} ({r.latency_s:.2f}s)  {'-> ' + r.value if r.value else ''}  {r.detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
