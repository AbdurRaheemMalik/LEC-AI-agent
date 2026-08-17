"""
Independent data sources for the fact checker.

Each public *_source() function talks to exactly one independent source and
always returns a SourceResult - it never raises. A failure (bad HTTP status,
timeout, missing file, unexpected shape) is caught and reported as data, not
hidden as an exception, so the caller can always say what happened and why.
"""

from __future__ import annotations

import csv
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_TIMEOUT = 6.0

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_SUMMARY_API = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

# canonical attribute -> (Wikidata property id, value kind)
# value kind drives how a claim's datavalue is turned into a display string.
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
# Wikidata: structured facts
# ---------------------------------------------------------------------------

def _wikidata_search_entity(name: str, timeout: float) -> Optional[str]:
    params = urllib.parse.urlencode(
        {"action": "wbsearchentities", "search": name, "language": "en", "format": "json", "limit": 1}
    )
    data = _http_get_json(f"{WIKIDATA_API}?{params}", timeout)
    results = data.get("search") or []
    if not results:
        return None
    return results[0]["id"]


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
    labels = {}
    for qid, ent in data.get("entities", {}).items():
        lbl = ent.get("labels", {}).get("en", {}).get("value")
        labels[qid] = lbl or qid
    return labels


def _select_current_claim(claims: list[dict]) -> Optional[dict]:
    """Pick the claim that best represents the *current* value of a property:
    drop deprecated claims and ones with a qualifier saying they ended, prefer
    Wikidata's own 'preferred' rank, and break remaining ties by the most
    recent point-in-time/start-time qualifier."""
    candidates = [c for c in claims if c.get("rank") != "deprecated"]
    candidates = [c for c in candidates if "P582" not in c.get("qualifiers", {})]  # P582 = end time
    if not candidates:
        return None
    preferred = [c for c in candidates if c.get("rank") == "preferred"]
    pool = preferred or candidates
    if len(pool) == 1:
        return pool[0]

    def sort_key(c):
        quals = c.get("qualifiers", {})
        for pid in ("P585", "P580"):  # point in time, start time
            if pid in quals:
                return quals[pid][0]["datavalue"]["value"]["time"]
        return ""

    pool.sort(key=sort_key, reverse=True)
    return pool[0]


def _format_time_value(value: dict) -> str:
    raw = value["time"].lstrip("+")
    precision = value.get("precision", 11)
    year = raw.split("-")[0]
    if precision <= 9:  # year-level precision or coarser
        return year
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
        prop_claims = claims.get(pid, [])
        claim = _select_current_claim(prop_claims)
        if claim is None:
            return SourceResult("wikidata", "failed", detail=f"'{entity}' has no current {attribute} claim on Wikidata", latency_s=time.monotonic() - start)

        datavalue = claim["mainsnak"]["datavalue"]["value"]
        if kind == "entity":
            value_qid = datavalue["id"]
            labels = _wikidata_get_labels([value_qid], timeout)
            display = labels.get(value_qid, value_qid)
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
        return SourceResult("wikidata", "failed", detail=f"HTTP {e.code}: {e.reason if hasattr(e, 'reason') else e.msg}", latency_s=time.monotonic() - start)
    except urllib.error.URLError as e:
        return SourceResult("wikidata", "failed", detail=f"network error: {e.reason}", latency_s=time.monotonic() - start)
    except Exception as e:  # noqa: BLE001 - a failed source must never crash the run
        return SourceResult("wikidata", "failed", detail=f"unexpected error: {e}", latency_s=time.monotonic() - start)


# ---------------------------------------------------------------------------
# Wikipedia: free-text corroboration
# ---------------------------------------------------------------------------

def wikipedia_source(entity: str, candidates: dict[str, str], timeout: float = DEFAULT_TIMEOUT, simulate_failure: bool = False) -> SourceResult:
    """Fetch the Wikipedia summary for `entity` and check whether each
    candidate value (keyed by the source that produced it, e.g. {"wikidata":
    "Paris", "local_csv": "Paris"}) appears in the extract text. This never
    invents a value on its own - it only corroborates or fails to
    corroborate values other sources already produced."""
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
            "wikipedia",
            "ok",
            value="; ".join(f"{src}:{'match' if ok else 'no match'}" for src, ok in matches.items()) or "no candidates to check",
            detail=snippet,
            latency_s=time.monotonic() - start,
            extra={"matches": matches, "corroborated": corroborated},
        )

    except (socket.timeout, TimeoutError):
        return SourceResult("wikipedia", "timeout", detail=f"timed out after {timeout}s", latency_s=time.monotonic() - start)
    except urllib.error.HTTPError as e:
        detail = "page not found on Wikipedia" if e.code == 404 else f"HTTP {e.code}: {e.reason if hasattr(e, 'reason') else e.msg}"
        return SourceResult("wikipedia", "failed", detail=detail, latency_s=time.monotonic() - start)
    except urllib.error.URLError as e:
        return SourceResult("wikipedia", "failed", detail=f"network error: {e.reason}", latency_s=time.monotonic() - start)
    except Exception as e:  # noqa: BLE001
        return SourceResult("wikipedia", "failed", detail=f"unexpected error: {e}", latency_s=time.monotonic() - start)


# ---------------------------------------------------------------------------
# Local CSV: user-curated reference data
# ---------------------------------------------------------------------------

def csv_source(entity: str, attribute: str, csv_path: str, simulate_failure: bool = False) -> SourceResult:
    start = time.monotonic()
    try:
        if simulate_failure:
            raise RuntimeError("Simulated failure (--simulate-failure)")

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["entity"].strip().lower() == entity.strip().lower() and row["attribute"].strip().lower() == attribute.strip().lower():
                    return SourceResult("local_csv", "ok", value=row["value"].strip(), detail=f"row matched in {csv_path}", latency_s=time.monotonic() - start)
        return SourceResult("local_csv", "failed", detail=f"no row for entity='{entity}', attribute='{attribute}' in {csv_path}", latency_s=time.monotonic() - start)

    except FileNotFoundError:
        return SourceResult("local_csv", "failed", detail=f"file not found: {csv_path}", latency_s=time.monotonic() - start)
    except Exception as e:  # noqa: BLE001
        return SourceResult("local_csv", "failed", detail=f"unexpected error: {e}", latency_s=time.monotonic() - start)
