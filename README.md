# Multi-source fact checker that degrades gracefully

A small CLI agent that answers factual questions by consulting multiple
independent sources, and — the actual point of this project — knows how to
say "I can't confirm this" instead of guessing when a source fails, times
out, or disagrees.

```
$ python3 factcheck.py "What is the capital of Japan?"

QUESTION: What is the capital of Japan?

PLAN: entity='Japan', attribute='capital'
      phase 1 (parallel): wikidata, local_csv
      phase 2 (sequential, depends on phase 1's candidate values): wikipedia corroboration

[wikidata  ] OK       (0.42s)  -> Tokyo  Wikidata entity Q17, property P36
[local_csv ] OK       (0.00s)  -> Tokyo  row matched in data/local_facts.csv
[wikipedia ] OK       (0.09s)  -> wikidata:match; local_csv:match  Japan is an island country...

VERDICT: Tokyo
CONFIDENCE: HIGH
REASON: wikidata and local_csv independently agree: Tokyo. Wikipedia's summary text also corroborates this.
SOURCES USED: wikidata, local_csv, wikipedia
SOURCES SKIPPED: none
```

## Setup

Python 3.9+, no `pip install` needed — everything is standard library
(`urllib`, `json`, `csv`, `concurrent.futures`). Needs internet access for
the Wikidata and Wikipedia calls.

```bash
python3 factcheck.py "What is the capital of Japan?"
```

## Scope: what questions this can actually verify

"General factual question" is honestly bounded here to **attribute-of-entity
questions** — "what is the X of Y" — because that's the shape of question
free structured APIs can verify without an LLM in the loop making things up.
Supported attributes: `capital`, `population`, `currency`,
`official_language`, `area`, `head_of_government`, `head_of_state`,
`founded`, `author`, `birth_date`. This covers countries, people, companies,
books — genuinely general, not just "country facts" — but a question outside
that shape (`"What is the meaning of life?"`) gets an explicit refusal, not a
guess:

```
$ python3 factcheck.py "What is the meaning of life?"
PLAN: could not map this question to a verifiable (entity, attribute) pair.
VERDICT: declining to answer.
REASON: this question isn't in a shape my sources can independently verify...
```

That refusal path is deliberate, not a limitation to hide — it's the same
"never guess" discipline applied one level earlier, before any source is
even queried.

## Why no local LLM

The brief lists a local LLM as one example source among several ("for
example, a local LLM, a free public API... or a CSV file") — it isn't
required. No Ollama/local model was available in the build environment, and
more importantly: an LLM can't independently *verify* a fact, it can only
assert one, which cuts against the core requirement of never returning an
answer that can't be justified by named, checkable sources. Instead this
uses three sources that are each independently checkable:

1. **Wikidata** — structured facts via property IDs (P36 capital, P1082
   population, P38 currency, etc.), resolved through
   `www.wikidata.org/w/api.php`.
2. **Wikipedia** — free-text corroboration via
   `en.wikipedia.org/api/rest_v1/page/summary/{title}`.
3. **A local CSV** (`data/local_facts.csv`) — a small user-curated reference
   file. This is the source we deliberately break in the demo below.

A local LLM would be a fine *fourth* source to bolt on later (`sources.py`
is built so adding one is just another `*_source()` function returning a
`SourceResult`) — it just isn't one of the two-plus independent sources this
build leans on for actually verifying anything.

## Architecture

```
factcheck.py        CLI: parses args, runs the pipeline, prints the report
factchecker/
  planner.py         question -> Plan(entity, attribute), or None (no guess)
  sources.py          wikidata_source / wikipedia_source / csv_source
  synth.py            SourceResults -> Verdict (deterministic, no LLM)
data/local_facts.csv  curated reference data (the source we break on demand)
tests/                offline unit tests for planner.py and synth.py
```

**Planning.** `planner.py` matches the question against a set of patterns
(`"capital of X"`, `"who wrote X"`, `"when was X founded"`, ...) to decide
*which* entity and attribute are being asked about, and therefore which
sources are even relevant. No match -> no plan -> explicit decline.

**Execution order is a deliberate two-phase plan, not "just run everything
in parallel":**
- **Phase 1 (parallel):** Wikidata and the local CSV are independent
  structured-value sources with no dependency on each other, so they run
  concurrently via `ThreadPoolExecutor`, each with its own timeout and its
  own try/except (one source failing never takes down the run).
- **Phase 2 (sequential, deliberately):** Wikipedia doesn't produce a
  structured value on its own — reliably extracting "the capital" from
  free-text prose without an LLM isn't honest to attempt. Instead it
  corroborates: it checks whether the candidate value(s) phase 1 already
  produced appear in the Wikipedia summary text. That means phase 2 has a
  genuine dependency on phase 1's output, so it runs after — this is the
  agent's decision about ordering, not an accident.

**Synthesis** (`synth.py`, pure functions, no I/O, fully unit-tested) is a
deterministic decision tree:

| Structured sources (Wikidata, CSV) | Wikipedia | Result |
|---|---|---|
| 0 succeeded | — | **Decline.** Every failure reason listed. |
| 1 succeeded | corroborates it | **Answer, MEDIUM confidence** — 2 independent sources effectively agree. |
| 1 succeeded | doesn't corroborate / unavailable | **Decline.** A single uncorroborated source isn't enough. Value shown but explicitly marked unverified. |
| 2 succeeded, agree | corroborates | **Answer, HIGH confidence.** |
| 2 succeeded, agree | fails / doesn't corroborate | **Answer, HIGH confidence** (2 structured DBs agreeing is strong; a text miss is a soft signal, not a conflict — noted, not hidden). |
| 2 succeeded, **disagree** | corroborates one side | **Answer, MEDIUM confidence**, but the conflict and the losing value are named in the report, never hidden. |
| 2 succeeded, **disagree** | can't break the tie | **Decline.** Both conflicting values shown, no arbitrary pick. |

Numeric attributes (population, area) are compared with a 10% relative
tolerance rather than exact match, since sources snapshot at different
times. Everything else is case-insensitive exact match.

## Demoing source failure

Two ways, both real (not mocked in a way that fakes success):

**1. Delete/rename the file** (literal "deleting a file" from the brief):
```bash
mv data/local_facts.csv data/local_facts.csv.bak
python3 factcheck.py "What is the capital of France?"
mv data/local_facts.csv.bak data/local_facts.csv   # restore after
```
`csv_source` catches the real `FileNotFoundError` and reports it; the agent
falls back to Wikidata + Wikipedia agreeing, at reduced (MEDIUM) confidence,
explicitly naming the CSV as skipped and why.

**2. Force a simulated HTTP 500** on any one source, repeatable on demand:
```bash
python3 factcheck.py "What is the capital of Japan?" --simulate-failure wikidata
```

## Demo script (for the 3-minute video)

**Query 1 — everything working (≈45s):**
```bash
python3 factcheck.py "What is the capital of Japan?"
```
Narrate: three independent sources queried, two run in parallel
(Wikidata + local CSV), Wikipedia corroborates afterward, all three agree,
HIGH confidence, and the report names every source used.

**Query 2 — inject a real failure, show graceful degradation (≈90s):**
```bash
mv data/local_facts.csv data/local_facts.csv.bak
python3 factcheck.py "What is the capital of France?"
```
Narrate: the local CSV file is now missing. The agent doesn't crash and
doesn't pretend the CSV worked — it reports `local_csv FAILED: file not
found`, falls back to Wikidata + Wikipedia which independently agree, and
answers at MEDIUM (not HIGH) confidence, explicitly stating the CSV was
skipped and why. Then restore the file:
```bash
mv data/local_facts.csv.bak data/local_facts.csv
```

**Bonus, if time remains (≈30s) — a question it correctly refuses:**
```bash
python3 factcheck.py "What is the meaning of life?"
```
Narrate: out of scope for what these sources can verify, so it declines
outright rather than guessing.

## Testing

```bash
python3 -m unittest discover -s tests -v
```
16 offline unit tests over `planner.py` (question -> plan matching, incl.
the out-of-scope no-plan case) and `synth.py` (every branch of the decision
tree above, using hand-built `SourceResult`s — no network required, so
these run identically in CI).

## Known limitations

- Question understanding is regex/pattern based, not NLP — phrasing outside
  the supported patterns won't match even if a human would understand it.
  This is intentional: a pattern miss produces an honest "I can't verify
  this" rather than a fuzzy LLM guess at intent.
- Wikidata entity resolution takes the top fuzzy-search hit; for very
  ambiguous names (e.g. common words) it can resolve to the wrong entity.
  The report always names the resolved Wikidata QID so this is inspectable,
  not hidden.
- Only English Wikipedia/Wikidata are queried.
