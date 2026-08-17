# Stage 2: Execution — querying the sources

## Role

You receive a plan (`{entity, attribute}`) from stage 1. Your job is to
query every source that's relevant to this attribute and record exactly
what happened — value returned, or failure, with a human-readable reason.
**You do not decide what the final answer is.** That's stage 3's job. Your
only responsibility is faithful, transparent execution: if a source fails,
say so and why; never substitute a guess, a cached value, or a "probably
fine" placeholder for a source that didn't actually respond.

## Inputs

- Layer 4 (working artifact): `../01_planning/output/plan.json`
- Layer 3 (reference material):
  [`references/local_facts.csv`](references/local_facts.csv) — the local,
  user-curated fact source (columns: `entity,attribute,value`)
- Layer 3 (reference material):
  [`../_config/glossary.md`](../_config/glossary.md) — attribute → Wikidata
  property ID mapping

## Sources

1. **Wikidata** (`www.wikidata.org/w/api.php`) — structured facts, looked
   up by property ID per the glossary. Independent of the other two: it's
   a different database with its own editorial process.
2. **local_csv** (`references/local_facts.csv`) — a small hand-curated
   reference file. Independent of Wikidata/Wikipedia: whoever maintains
   this file is not pulling from them.
3. **Wikipedia** (`en.wikipedia.org/api/rest_v1/page/summary/{title}`) —
   free-text summary. It cannot produce a structured value on its own
   (extracting "the capital" reliably from prose without an LLM isn't
   honest to attempt), so it plays a different role: **corroboration**. It
   checks whether the candidate value(s) that Wikidata/local_csv already
   produced literally appear in its summary text.

## Process

**Phase 1 — parallel.** Wikidata and local_csv have no dependency on each
other, so query them concurrently. Give each its own timeout (default 6s)
and its own error handling — one source failing must never prevent the
other from completing or crash the run.

**Phase 2 — sequential, and deliberately so.** Wikipedia depends on
phase 1's output (it corroborates *those* candidate values), so it runs
only after phase 1 finishes. If phase 1 produced zero candidate values
(both Wikidata and local_csv failed), **skip Wikipedia entirely** — there
is nothing for it to corroborate, and querying it anyway would just waste
a call and produce a meaningless result.

**Failure handling**, for every source: catch the specific failure mode
and record it plainly —
- HTTP error (including a simulated 500 via `--simulate-failure`, used for
  demoing degradation) → `"failed"`, detail = status/reason
- timeout → `"timeout"`, detail = timeout duration
- file not found (local_csv) → `"failed"`, detail = the missing path
- no matching row / no matching Wikidata claim → `"failed"`, detail = why

A source that raises an exception you didn't anticipate is still a
`"failed"` result with the exception message as detail — it is never
allowed to crash the pipeline or be silently swallowed.

## Outputs

Write `output/source_results.json`: one record per source —
`{"name": ..., "status": "ok"|"failed"|"timeout", "value": ..., "detail": ..., "latency_s": ..., "extra": {...}}`.
Wikipedia's `extra.corroborated` lists which source names it was able to
corroborate.

## Standalone

```bash
python3 02_execution/run.py --plan ../01_planning/output/plan.json
python3 02_execution/run.py --plan ../01_planning/output/plan.json --simulate-failure wikidata
```
