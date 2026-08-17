# Stage 1: Planning — which sources to query

## Role

You receive one raw question. Your only job is to decide two things:
**what entity is this about**, and **what attribute of it is being asked**
— and if you can't determine both with confidence, to say so explicitly
rather than pass a guess downstream. A wrong plan poisons every stage after
it, so refusing here is cheap; guessing here is not.

## Inputs

- The question string, exactly as the user typed it.
- Layer 3 reference: [`_config/glossary.md`](../_config/glossary.md) — the
  full list of attributes this system can currently plan for. Nothing
  outside that list can be verified downstream, no matter how well you
  understand the question.

## Process

1. Strip a trailing `?` and surrounding whitespace.
2. Check the question against these shapes, in order, and take the first
   match:

   | Question shape | Attribute |
   |---|---|
   | "capital (city) of X" | `capital` |
   | "population of X" | `population` |
   | "currency of X" | `currency` |
   | "(official) language(s) of / spoken in X" | `official_language` |
   | "area of X" | `area` |
   | "(current) prime minister / chancellor / head of government of X" | `head_of_government` |
   | "(current) president / head of state of X" | `head_of_state` |
   | "who wrote X" | `author` |
   | "when was X founded / established" | `founded` |
   | "when was X born" | `birth_date` |

3. From the matched shape, extract the entity name (the "X"). Strip a
   leading "the/a/an" from it (Wikidata search handles bare names better
   than "the United States").
4. If nothing matched, or the extracted entity is empty: **there is no
   plan.** This is not an error state — it's the correct output for a
   question outside this system's verifiable scope. Say so plainly; do not
   attempt a best-effort guess at entity/attribute from a partial match.

## Outputs

Write `output/plan.json`:

- On a match: `{"entity": "<string>", "attribute": "<one of the glossary keys>", "matched_pattern": "<which shape matched>"}`
- On no match: `{"entity": null, "attribute": null, "reason": "<why nothing matched, e.g. 'question shape not recognized'>"}`

Either way, this is the *only* file stage 2 is allowed to read to learn
what to do — it doesn't see the original question text again.

## Why this is mechanical, not judgment-based

Matching a question to one of ten known shapes is pattern recognition, not
reasoning — it doesn't need an LLM call, and making it deterministic means
the same question always produces the same plan, which is what makes the
rest of the pipeline testable. `run.py` implements exactly the table
above with regular expressions.

## Standalone

```bash
python3 01_planning/run.py "What is the capital of Japan?"
```
Prints the plan and writes it to `01_planning/output/plan.json`.
