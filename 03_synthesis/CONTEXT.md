# Stage 3: Synthesis — reconciling into a verdict

## Role

You receive stage 2's `source_results.json` — some sources succeeded, some
may have failed, and the ones that succeeded may or may not agree with
each other. Your job is to turn that into a verdict that is **always
justifiable**: an answer with a confidence level, or an explicit refusal —
never a value you can't trace back to which sources produced it. This is
the stage the whole system exists for; get this one honest even if it
makes the earlier stages look wasted on a given run.

## Inputs

- Layer 4 (working artifact): `../02_execution/output/source_results.json`
- The `attribute` from `../01_planning/output/plan.json` (needed to know
  whether to compare values as numbers-with-tolerance or as exact strings)

## Process — the decision table

Treat Wikidata and local_csv as the two **structured** sources, and
Wikipedia as a **corroboration** signal on top of them.

| Structured sources | Wikipedia | Verdict |
|---|---|---|
| 0 succeeded | — | **Decline.** List every failure and its reason. |
| 1 succeeded | corroborates it | **Answer, MEDIUM confidence** — treat this as 2 independent sources agreeing. |
| 1 succeeded | doesn't corroborate, or unavailable | **Decline.** A single uncorroborated source is not enough. Still show the value, but label it unverified — don't hide it, don't assert it either. |
| 2 succeeded, agree | corroborates | **Answer, HIGH confidence.** |
| 2 succeeded, agree | fails / doesn't corroborate | **Answer, HIGH confidence** anyway — two independent structured databases agreeing is strong on its own; a text-corroboration miss is a soft signal, not a conflict. Note it, don't let it override the agreement. |
| 2 succeeded, **disagree** | corroborates one side | **Answer, MEDIUM confidence**, using the corroborated value — but name both values and the disagreement in the reason. The losing source is "skipped", not "wrong" — never erase it from the record. |
| 2 succeeded, **disagree** | can't break the tie | **Decline.** Show both conflicting values. Do not pick one arbitrarily. |

**Agreement rule**: for `population` and `area`, two values agree if
they're within 10% of each other (sources snapshot at different times).
Every other attribute requires case-insensitive exact string match.

**Every verdict, answered or declined, must state:**
1. the answer (or explicitly, that there isn't one),
2. a confidence level (or explicitly, none),
3. which sources were used,
4. which sources were skipped and why.

Missing any of the four means the verdict isn't done yet.

## Outputs

Write `output/verdict.json`:
`{"status": "answered"|"declined", "answer": ..., "confidence": "HIGH"|"MEDIUM"|null, "reason": "...", "sources_used": [...], "sources_skipped": [["name","reason"], ...]}`

And print the human-readable report to stdout — this is what the user
actually sees.

## Standalone

```bash
python3 03_synthesis/run.py --plan ../01_planning/output/plan.json --results ../02_execution/output/source_results.json
```
