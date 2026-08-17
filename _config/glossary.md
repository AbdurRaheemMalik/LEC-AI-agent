# Glossary — supported attributes

The single source of truth for what this system can plan for (stage 1) and
how to fetch it from Wikidata (stage 2). If you add a row here, add the
matching regex pattern in `01_planning/run.py` and the matching PID entry
in `02_execution/run.py` — the three have to move together.

| Attribute key       | Meaning                        | Wikidata property | Value kind |
|----------------------|---------------------------------|--------------------|------------|
| `capital`            | capital city of a place         | P36                | entity     |
| `population`         | population count                | P1082              | quantity   |
| `currency`            | official currency                | P38                | entity     |
| `official_language`  | official language(s)            | P37                | entity     |
| `area`                | land/total area                  | P2046              | quantity   |
| `head_of_government`  | PM / chancellor / etc.          | P6                 | entity     |
| `head_of_state`       | president / monarch / etc.      | P35                | entity     |
| `founded`             | founding / inception date        | P571               | time       |
| `author`              | author of a written work         | P50                | entity     |
| `birth_date`          | date of birth of a person        | P569               | time       |

**Value kinds**, and how stage 2 turns a Wikidata claim into a display
string:
- `entity` — the claim points at another Wikidata item (e.g. capital ->
  the item for "Paris"); stage 2 resolves that item's English label.
- `quantity` — the claim is a number (e.g. population); stage 2 rounds it
  to the nearest integer.
- `time` — the claim is a date; stage 2 shows a year or a full date
  depending on the claim's stated precision.

**Numeric tolerance**: `population` and `area` are compared across sources
with a 10% relative tolerance (see `03_synthesis/CONTEXT.md`), not exact
match, because sources snapshot population at different times.

**"Current value" selection**: Wikidata often carries many historical
claims for one property (a country's population over 60 years, several
past capitals). Stage 2 picks the *current* one by: dropping claims marked
`deprecated`, dropping claims with a "end time" (P582) qualifier since
those are explicitly closed out, preferring Wikidata's own `preferred`
rank, and breaking remaining ties by the latest point-in-time (P585) or
start-time (P580) qualifier.
