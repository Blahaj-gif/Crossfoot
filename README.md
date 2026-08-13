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

| | Built | Refuses to |
|---|---|---|
| 1 | **Drop** — a statement file (CSV or OFX) and a folder of receipts, both named on the command line. | accept a statement whose own running balance does not step correctly row to row, or whose rows do not sum to its declared period total: that export is truncated, and every verdict downstream would rest on a partial ledger. |
| 2 | **Read** — Docling for layout where installed, plain text otherwise. Every field keeps its confidence and the line it came from. | use a total it read below threshold. It names the field and shows you the line. |
| 3 | **Match** — amount, date window, merchant string. Fuzzy on the name, exact on the cents. | auto-resolve a tie. A guess that looks like a match is worse than a gap that looks like a gap. |
| 4 | **Crossfoot** — the four checks. | widen a tolerance far enough to hide a magnitude error. Rounding gets cents; nothing gets a percent. |
| 5 | **Review** — only failures and unchecked reach a human, ordered by money at risk. | let an assistant clear the queue. Approval is a keystroke in your window; there is no path to it from the model's side. |
| 6 | **Export** — CSV, Beancount, Firefly III, Actual Budget, verdict attached as a tag. | export an *unchecked* row as though it reconciled. |

**Not built, and named here so the table above is not read as a promise:** no
watched folder, no email intake, no drag-and-drop; no image handling at all, so
no crops and no pixel boxes — a field's provenance is the line of text it came
from; and no local vision model, so a photographed thermal receipt is only as
readable as whatever text your reader can get out of it. Those were in the
design and are not in the code.

Step 6 is the strategy. Crossfoot does not compete with Firefly III or Actual
Budget — 52,000 stars between them and no receipt verification at all. It feeds
them.

## Status

All six steps exist. 341 tests.

```
pip install -e ".[dev]"
pytest

crossfoot check  --statement bank.csv --receipts ./receipts   # read-only
crossfoot review --statement bank.csv --receipts ./receipts   # the only way to decide
crossfoot export --statement bank.csv --receipts ./receipts --to actual --out ledger.csv
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

## Into the tool you already use

Crossfoot is not a budgeting app and has no intention of becoming one. It hands
the verdict to whatever you already run, attached to the transaction, where it
will still be legible next April.

| `--to` | What you get |
|---|---|
| `actual` | **Actual Budget**'s importer: Date / Payee / Notes / Amount. The verdict arrives as `#crossfoot-unchecked` in the note, because Actual reads hashtags out of notes and a verdict written as prose is one nobody can filter on. |
| `firefly` | **Firefly III**'s data importer, with tags as a real column — plus a `.json` beside the CSV holding the column mapping, so it is not twenty dropdowns the first time and twenty again next month. |
| `beancount` | Plain-text accounting. Unreconciled entries carry beancount's own `!` flag, so `bean-check` surfaces them without anyone remembering a tag. |
| `generic` | A plain CSV with every check that ran. Open it in anything. |

```
2026-08-14 ! "HOME DEPOT #4471"
  crossfoot-verdict: "crossfoot:does-not-reconcile"
  crossfoot-why: "1 line items sum to 791.44; the receipt prints a subtotal of 797.44"
  crossfoot-receipt: "The_Home_Depot.txt"
  Assets:Bank:Checking  -842.19 USD
  Expenses:Unknown
```

Five verdicts leave, not three. `crossfoot:accepted-by-you` is its own state —
a person looked at a discrepancy and made a call, and exporting that as either
"reconciled" or "unchecked" would lose the only fact that matters about it.

**Nothing here phones anything.** Every exporter writes a file the target's own
importer reads. That is the property the project is for, not a limitation
worked around: receipts and statements are the most sensitive documents most
people own, and a tool that promises they never leave the machine should have
no code capable of sending them. CI asserts the absence of the imports.

Docling is an optional extra (`pip install 'crossfoot[read]'`). Without it,
PDFs are read as plain text and every number from one is marked *degraded* in
the queue rather than quietly used. The checking layer itself is arithmetic and
stdlib: nobody should have to install a machine-learning stack to reconcile
numbers they already have.

### What is deliberately not built

`split` and `correct` are accepted as decisions and recorded, but nothing yet
consumes them. There is no MCP server — when there is, it will import the queue
and the *ledger reader*, never the writer, which is the separation CI already
enforces.

Nothing here has met a real receipt. Every fixture is text typed in the format
this parser expected, which is a mirror rather than a test — so no accuracy
claim is made, and the six defects an afternoon of attacking it produced are
the reason that caveat is at the top rather than the bottom.

## The wall

`crossfoot check`, `crossfoot export`, the matcher and the queue can all be
handed to an assistant. None of them can clear a queue item.

Reading the decision log and writing to it are two modules. `review/ledger.py`
verifies and reads and contains no function that appends; `review/decisions.py`
is the write path and `review/app.py` is its only importer. The split exists
because the exporter genuinely needs to read the log — and if reading meant
importing the writer, every consumer of the ledger would have `record` one
attribute away and the boundary would be a convention again. CI reads the
import graph on every push.

It is a repository boundary, not a security one, and worth saying in the same
breath: any process on this machine can import the writer and pass the string
`"human"`. What makes that visible afterwards is the hash chain, not the split.

Decisions append to `decisions.jsonl`, flushed and fsynced per click, each one
carrying the numbers the person was actually shown. Re-read a document, get a
different total, and the old approval no longer applies to it.

## Whether this should exist

Searching GitHub for a tool that reconciles receipts against a bank statement
returns five repositories. All five were created between 30 June and 8 August
2026, and all five were abandoned within days — 2, 4 and 6 commits. The first
reading was that finishing is therefore the moat.

Looking harder made that weaker rather than stronger. Actual Budget's
most-reacted feature request is
[attaching receipts to transactions](https://github.com/actualbudget/actual/issues/530)
— 195 reactions — and it was **closed as completed in 2023**, with four later
duplicates closed the same way. The professional version of the problem is real
and expensive (bank reconciliation runs about 11 hours per client per month in
firms that do bookkeeping) and is served by Dext, Expensify, Ramp, Concur, BILL
and others. Meanwhile *nobody, anywhere, has filed an issue asking for a tool
that checks a receipt's own arithmetic* — which is the only thing Crossfoot
does that those don't.

So the empty field may be empty because the part people want is elsewhere and
already built, and five abandoned repositories are as consistent with "everyone
discovers there is nothing here" as with "nobody finishes things".

That question is not settled by writing more of this. It is settled by
[the demand test](docs/demand-test.md), whose threshold was written down before
any results arrived: 25 people running it on their own statements, and 5 saying
the *verdict* changed something they did. If that fails, the right ending is to
leave this as a small finished tool and go and find a problem somebody is
already trying to pay for.
