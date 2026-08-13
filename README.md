# Crossfoot

Receipts and statements in. A **verdict** out — not a category.

Every other receipt tool draws you a pie chart of where the money went. The
chart is the part that does not matter, because it is drawn on numbers nobody
checked. Crossfoot's product is the check.

> *Crossfooting* is the auditor's practice of verifying that a row's total and
> its column's total agree — two independently derived numbers about the same
> fact. A receipt states its own totals two or three times over. So does a
> statement. Nothing here needs a model's opinion to know when they disagree.

## Three states, and the third one is the point

| | Means |
|---|---|
| **Reconciled** | A receipt matches this charge, and the receipt's own arithmetic agrees with itself. |
| **Does not reconcile** | A number the document states twice disagrees with itself, or the matched receipt's total is not what was charged. |
| **Unchecked** | No receipt, or the receipt did not state enough to check. |

Every incumbent collapses "verified correct" and "we could not tell" into one
silent success. That is how a 90%-accurate parser feels like a 100%-accurate one
right up until the year you need it to have been right. An unverified number
here is a liability, not a result, and it is never counted as clean.

## The pipeline

| | | Refuses to |
|---|---|---|
| 1 | **Drop** — watched folder, email, or drag-and-drop. Photos, PDFs, CSV/OFX. | accept a statement whose own running balance does not step correctly row to row: that export is truncated, and every verdict downstream would rest on a partial ledger. |
| 2 | **Read** — Docling for layout, a local VLM for the crumpled thermal cases. Every field keeps its confidence and the box it came from. | emit a total it read below threshold. It emits the crop and asks. |
| 3 | **Match** — amount, date window, merchant string. Fuzzy on the name, exact on the cents. | auto-resolve a tie. A guess that looks like a match is worse than a gap that looks like a gap. |
| 4 | **Crossfoot** — the four checks. | widen a tolerance far enough to hide a magnitude error. Rounding gets cents; nothing gets a percent. |
| 5 | **Review** — only failures and unchecked reach a human, ordered by money at risk. | let an assistant clear the queue. Approval is a keystroke in your window; there is no path to it from the model's side. |
| 6 | **Export** — CSV, Beancount, Firefly III, Actual Budget, verdict attached as a tag. | export an *unchecked* row as though it reconciled. |

Step 6 is the strategy. Crossfoot does not compete with Firefly III or Actual
Budget — 52,000 stars between them and no receipt story at all. It feeds them.

## Status

All six steps exist. 145 tests.

```
pip install -e ".[dev]"
pytest

crossfoot check  --statement bank.csv --receipts ./receipts   # read-only
crossfoot review --statement bank.csv --receipts ./receipts   # the only way to decide
```

`check` exits 0 when nothing is outstanding, 1 when something needs a person,
and 2 when the statement itself could not be trusted — so it can be a step in
something larger without the caller parsing prose.

```
2 need you, 946.39 at risk, 1 reconciled, 1 unchecked
-----------------------------------------------------
    failed        842.19  2026-08-14  HOME DEPOT #4471
            1 line items sum to 791.44; the receipt prints a subtotal of 797.44
unverified        104.20  2026-08-09  SUNRISE CAFE SF
            no receipt is matched to this charge
```

Docling is an optional extra (`pip install 'crossfoot[read]'`). Without it,
PDFs are read as plain text and every number from one is marked *degraded* in
the queue rather than quietly used. The checking layer itself is arithmetic and
stdlib: nobody should have to install a machine-learning stack to reconcile
numbers they already have.

### What is deliberately not built

Export (step 6) is designed but unwritten. `split` and `correct` are accepted as
decisions and recorded, but nothing yet consumes them. There is no MCP server —
when there is, it will import the queue and never `review/decisions.py`, which
is the separation a test already enforces.

## The wall

`crossfoot check`, the CLI, the matcher and the queue can all be handed to an
assistant. None of them can clear a queue item: `review/decisions.py` is the
only write path and `review/app.py` is its only importer, checked by a test
that reads the import graph rather than trusting the convention.

Decisions append to `decisions.jsonl`, flushed and fsynced per click, each one
carrying the numbers the person was actually shown. Re-read a document, get a
different total, and the old approval no longer applies to it.

## Why this exists

Searching GitHub for a tool that reconciles receipts against a bank statement
returns five repositories. All five were created between 30 June and 8 August
2026. All five were abandoned within days — 2, 4 and 6 commits. Demand is
evidenced by attempts; supply is empty of finished work.

The honest counterweight: nobody starred any of them, and Firefly III's three
receipt issues and Actual Budget's two are all closed. This is a believed need,
not yet a measured one.
