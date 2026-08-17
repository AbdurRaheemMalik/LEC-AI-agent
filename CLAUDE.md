# Multi-source fact checker — workspace identity

## What this is

An agent that answers factual questions ("what is the X of Y") by
consulting multiple independent sources and reasoning honestly about
disagreement or failure. It never guesses, never reports a failed source as
having succeeded, and never gives a verdict it can't justify by naming
which sources it used and which it skipped.

## How the workspace is organized

This project follows a **folder-as-architecture** pattern: instead of one
big program or a multi-agent framework, the pipeline is three numbered
stages, each its own folder. One agent (you, or `factcheck.py` acting
mechanically) moves through the stages in order, reading only the context
it needs at each step:

```
01_planning/    decide what's being asked and which sources apply
02_execution/   query those sources and record what happened
03_synthesis/   reconcile the results into a verdict, honestly
```

Each stage folder has a `CONTEXT.md` — that file is the authority on what
that stage does, what it reads, and what it writes. `run.py` in each folder
is the mechanical implementation of that contract: deterministic work
(regex matching, HTTP calls, arithmetic tolerance checks) that doesn't
need judgment, so it's code, not prose. The `CONTEXT.md` files are the
actual spec; `run.py` is one faithful implementation of it, not the other
way round.

Stages talk to each other only through files in `output/` — stage 2 reads
stage 1's `output/plan.json`, stage 3 reads stage 2's
`output/source_results.json`. No stage imports another stage's code. That
boundary is deliberate: it's what makes each stage independently
inspectable and independently runnable.

## Where to go next

Read [`CONTEXT.md`](CONTEXT.md) at the root for how a question is routed
through the three stages, or jump straight to a stage's own `CONTEXT.md`
if you already know which part you're working on.
