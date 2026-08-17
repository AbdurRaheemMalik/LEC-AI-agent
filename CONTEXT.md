# Task routing

## If you're answering a factual question

Run the three stages in order. Each one is a hard boundary — don't skip
ahead, and don't let a later stage quietly redo an earlier stage's job.

1. **[`01_planning/CONTEXT.md`](01_planning/CONTEXT.md)** — turn the
   question into `{entity, attribute}`, or into an explicit refusal if the
   question isn't a shape any source here can verify. Writes
   `01_planning/output/plan.json`.

   **Stop here if planning produced no plan.** Report the refusal
   directly. Do not invoke stage 2 or 3 on a plan that doesn't exist —
   there is nothing for them to work with, and running them anyway would
   just be guessing with extra steps.

2. **[`02_execution/CONTEXT.md`](02_execution/CONTEXT.md)** — query the
   independent sources named in the plan and record exactly what each one
   returned, including failures. Writes
   `02_execution/output/source_results.json`.

3. **[`03_synthesis/CONTEXT.md`](03_synthesis/CONTEXT.md)** — reconcile
   stage 2's results into a verdict: an answer with a confidence level, or
   a refusal, always with sources named. Writes
   `03_synthesis/output/verdict.json`.

## If you're extending the system

- Adding a new source (e.g. a weather API, a second local file): it's a
  **stage 2 change only**. Add the fetch logic to `02_execution/`, add the
  new source's name to the candidate set stage 3 already knows how to
  reconcile. Stage 1 and stage 3 don't need to know a new source exists
  unless it changes what attributes can be planned for.
- Adding a new attribute (e.g. "elevation of X"): touches stage 1 (a new
  pattern) and stage 2 (a new Wikidata property mapping, or a new source
  entirely). Reference the attribute list in
  [`_config/glossary.md`](_config/glossary.md) — it's the single place
  that lists what's currently supported.

## Entry point

`python3 factcheck.py "What is the capital of Japan?"` runs all three
stages in sequence in one process and prints the final report. Each stage
can also be run on its own — see the "Standalone" section of that stage's
`CONTEXT.md`.
