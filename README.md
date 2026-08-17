# Multi-source fact checker that degrades gracefully

A small agent that answers factual questions by consulting multiple
independent sources — and, the actual point of this project, knows how to
say "I can't confirm this" instead of guessing when a source fails, times
out, or disagrees.

```
$ python3 factcheck.py "What is the capital of Japan?"

QUESTION: What is the capital of Japan?

PLAN: entity='Japan', attribute='capital' (matched: capital(?:\s+city)?\s+of\s+(.+))
      phase 1 (parallel): wikidata, local_csv
      phase 2 (sequential, depends on phase 1's candidate values): wikipedia corroboration

[wikidata  ] OK       (0.42s)  -> Tokyo  Wikidata entity Q17, property P36
[local_csv ] OK       (0.00s)  -> Tokyo  row matched in 02_execution/references/local_facts.csv
[wikipedia ] OK       (0.09s)  -> wikidata:match; local_csv:match  Japan is an island country...

VERDICT: Tokyo
CONFIDENCE: HIGH
REASON: wikidata and local_csv independently agree: Tokyo. Wikipedia's summary text also corroborates this.
SOURCES USED: wikidata, local_csv, wikipedia
SOURCES SKIPPED: none
```

## How to run it

Python 3.9+, no `pip install` needed — everything is standard library
(`urllib`, `json`, `csv`, `concurrent.futures`). Needs internet access for
the Wikidata and Wikipedia calls.

```bash
python3 factcheck.py "What is the capital of Japan?"
```

Force a source to fail, to see graceful degradation on demand:

```bash
python3 factcheck.py "What is the capital of France?" --simulate-failure wikidata
```

Run the offline unit test suite (no network needed):

```bash
python3 -m unittest discover -s tests -v
```

Run any single stage on its own — see "Architecture" below for why this
works:

```bash
python3 01_planning/run.py "What is the population of Germany?"
python3 02_execution/run.py --plan 01_planning/output/plan.json
python3 03_synthesis/run.py --plan 01_planning/output/plan.json --results 02_execution/output/source_results.json
```

## Architecture: folder structure as the agent's architecture

Instead of one monolithic script or a multi-agent framework, this is
organized the way Jake Van Cleef's *Interpretable Context Methodology*
describes it: the pipeline is **three numbered stage folders**, each with
a `CONTEXT.md` that is the actual spec for that stage — inputs, process,
outputs, written as instructions a reader (human or agent) can follow —
and a `run.py` that's one faithful, mechanical implementation of that
spec. Root-level `CLAUDE.md` and `CONTEXT.md` give the workspace identity
and routing, the same way they would for a Claude Code skill.

```
CLAUDE.md                 workspace identity ("what is this, where do I go")
CONTEXT.md                 task routing ("run stage 1, then 2, then 3")
_config/glossary.md        shared reference: supported attributes, Wikidata property IDs

01_planning/
  CONTEXT.md                contract: question -> {entity, attribute}, or an explicit refusal
  run.py                     mechanical regex matcher implementing that contract
  output/plan.json           what this run decided

02_execution/
  CONTEXT.md                 contract: query the sources named in the plan, record what happened
  run.py                     wikidata_source / wikipedia_source / csv_source + phase 1/2 orchestration
  references/local_facts.csv the local, user-curated source — deliberately breakable for the demo
  output/source_results.json what each source returned or how it failed

03_synthesis/
  CONTEXT.md                  contract: the full decision table for reconciling results into a verdict
  run.py                       mechanical implementation of that table
  output/verdict.json          the final answer/refusal, with reasons

_stage_loader.py              the one bit of "finding the correct files" plumbing in code
factcheck.py                  thin orchestrator: loads the 3 stage modules, runs them in order, prints the report
tests/                        offline unit tests over 01_planning and 03_synthesis (no network)
```

**Stages talk to each other only through files in `output/`** — stage 2
reads stage 1's `plan.json`, stage 3 reads stage 2's
`source_results.json`. No stage imports another stage's code. That's why
each stage above can also be run completely standalone from the command
line: the contract is genuinely file-in, file-out, not just an internal
function call dressed up in folders.

**Why markdown for the "what to do", Python only for the mechanical
part:** deciding *what a stage should do* — which question shapes count as
"capital of X", how to reconcile two disagreeing sources, when a text
corroboration counts as a soft signal versus a hard conflict — is
documented as prose in each `CONTEXT.md`, because that's what a person (or
another agent extending this later) needs to read to understand or change
the system's judgment calls. Actually *doing* the work — an HTTP request,
a regex match, a 10%-tolerance number comparison — doesn't need
"judgment," so it's ordinary deterministic code in `run.py`. The
`CONTEXT.md` is the authority; `run.py` is required to match it, not the
reverse.

## Sources, and why no local LLM

1. **Wikidata** — structured facts by property ID (P36 capital, P1082
   population, etc. — full list in
   [`_config/glossary.md`](_config/glossary.md)).
2. **local_csv** — a small hand-curated reference file
   (`02_execution/references/local_facts.csv`). This is the source
   deliberately broken in the demo below.
3. **Wikipedia** — free-text summary, used only to *corroborate* whatever
   candidate value(s) Wikidata/local_csv already produced (see
   `02_execution/CONTEXT.md` for why it can't stand alone as a
   structured-value source).

No local LLM is used, by design, not by necessity. The brief lists one as
an *example* source, not a requirement, and an LLM can assert a fact but
can't independently verify one — using it as a "source" would work against
the core requirement that every answer be justifiable by named, checkable
sources. `02_execution/run.py` is built so a fourth source (an LLM or
otherwise) is just another `*_source()` function returning the same
`SourceResult` shape.

## Demoing a source failure

```bash
mv 02_execution/references/local_facts.csv 02_execution/references/local_facts.csv.bak
python3 factcheck.py "What is the capital of France?"
mv 02_execution/references/local_facts.csv.bak 02_execution/references/local_facts.csv   # restore after
```
`csv_source` catches the real `FileNotFoundError` and reports it; the
agent falls back to Wikidata + Wikipedia agreeing, at reduced (MEDIUM, not
HIGH) confidence, explicitly naming the CSV as skipped and why. Or force
any single source to fail on demand:
```bash
python3 factcheck.py "What is the capital of Japan?" --simulate-failure wikidata
```

## What I'd do next with more time

- **Replace regex planning with LLM-assisted planning, kept auditable.**
  The pattern list in `01_planning/CONTEXT.md` covers ten question shapes
  well; real users phrase things ten other ways. The fix isn't to drop the
  contract-file architecture, it's to let a model read
  `01_planning/CONTEXT.md` itself and produce the same `plan.json` shape —
  the file was written to be followable by a model as much as by `run.py`,
  so this is a swap-in, not a redesign.
- **A fourth, genuinely independent source** — a free weather/news API for
  time-sensitive facts, or a second structured database (e.g. REST
  Countries) as a check on Wikidata specifically, since right now Wikidata
  and Wikipedia are correlated (same underlying editorial community) even
  though they're separately queried.
- **Confidence calibration against ground truth.** Right now HIGH/MEDIUM
  is a rule of thumb (3/3, 2/3, or 2/2-plus-text-corroboration). Running
  this against a labeled set of questions with known-correct answers would
  turn "MEDIUM" into an actual calibrated probability instead of a label.
- **Caching + rate-limit handling.** Wikidata/Wikipedia calls aren't
  cached, so repeated questions re-fetch every time and there's no
  backoff if a source starts rate-limiting mid-run — fine for a demo,
  not for real usage volume.
- **Broader attribute coverage without a linear blow-up in patterns** —
  right now every new attribute is a new regex in
  `01_planning/CONTEXT.md`/`run.py` and a new PID row in
  `_config/glossary.md`. Past a few dozen attributes this should become a
  small routing table (or the LLM-planning swap above) rather than more
  regex.
- **A conflict-resolution UI**, not just CLI text — when two sources
  disagree and there's no tiebreaker, the current behavior is a clean
  refusal in the terminal; a real product would let the user pick a
  source to trust and remember that preference.

## Known limitations

- Question understanding is pattern-based, not free-form NLP — phrasing
  outside the ten supported shapes produces an honest refusal rather than
  a guess. Intentional (see above), not hidden.
- Wikidata entity resolution takes the top fuzzy-search hit; for very
  ambiguous names it can resolve to the wrong entity. The report always
  names the resolved Wikidata QID, so this is inspectable, not silent.
- English Wikipedia/Wikidata only.
