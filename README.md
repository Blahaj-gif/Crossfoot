# Crossfoot

**Reads your bank statement and tells you what looks wrong — without connecting
to your bank.**

Every other money tool draws you a pie chart of where it went. The chart is
drawn on numbers nobody checked. Crossfoot's product is the check, and the third
answer — *I could not tell* — which no other tool will give you.

![Crossfoot audits a bank statement, then refuses to report anything once one balance is altered](https://raw.githubusercontent.com/Blahaj-gif/Crossfoot/main/docs/demo.svg)

```
git clone https://github.com/Blahaj-gif/Crossfoot && cd Crossfoot
pip install .
crossfoot audit examples/statement.csv
```

Python 3.10 or newer and **nothing else** — no account, no bank connection, no
receipts, no optional packages. Not on PyPI yet, so it is a clone.

There is a statement in the box, because the first step should not be "export
your own banking for a tool you found five minutes ago". Then point it at your
own export:

```
crossfoot audit ~/Downloads/statement.csv
```

Exit code 0 when nothing is outstanding, 1 when something needs you, 2 when the
file could not be trusted — so it can be a step in something larger without the
caller parsing prose.

## What it finds

Three things, and each is a fact the statement states rather than a guess about
your life:

| | |
|---|---|
| **Paid twice** | Two identical charges at one merchant, days apart, with no refund after. The card terminal that timed out and was run again. |
| **Price rose** | A recurring charge whose amount went up, and what the difference costs in a year. |
| **New recurring** | A merchant that was not billing you monthly at the start of the file and is now. |

Then, separately and deliberately **not** called a finding, an inventory of
every recurring charge with its annual cost. Whether you still want a
subscription is not in the statement, and a tool that says "you are not using
this" is guessing at the one thing it cannot see.

Nothing asserts a duplicate either. Two identical charges are a fact; whether
that is one purchase billed twice or two coffees on a Saturday is not in the
file. It shows the pair, says what makes it suspicious, and you decide. A run
whose gaps all sit near a month is a subscription and is not flagged; a refund
of the same amount afterwards means it was already put right, so it is shown at
**zero** at risk.

## What it refuses to do

**If the export is not whole, it reports nothing at all.**

Where a file carries a running balance, each row's balance must be the previous
one plus that row's amount. Where it states a period total, or an opening and a
closing balance, the rows must sum to it. Break either and the audit goes
silent — that is the second panel above.

A duplicate found in a statement with rows missing is an artefact of the gap,
and the rows that were never read cannot be reported as missing. Without that
gate the page is short, clean and wrong, and somebody reads it and concludes
their account is fine.

Most exports carry neither a balance nor a total. Those are reported as
**unverifiable**, not whole — a check that could not run is never counted as a
check that passed. That rule is the whole project in one line.

## Three states, and the third one is the point

| | Means |
|---|---|
| **Reconciled** | A document matches this charge and its own arithmetic agrees with itself. |
| **Does not reconcile** | A number stated twice disagrees with itself, or the matched total is not what was charged. |
| **Unchecked** | No document, or it did not state enough to check. |

Every incumbent collapses "verified correct" and "we could not tell" into one
silent success. That is how a 90%-accurate parser feels like a 100%-accurate one
right up until the year you needed it to have been right.

## Receipts, honestly

Crossfoot began as a receipt checker. Then the receipts were measured.

**On 55 photographs of real receipts, 52 were refused and one produced a
total — and that one was a screenshot rather than paper.** Zero wrong figures
were recorded, which is the safety property working exactly as designed and is
also not a useful result: a tool that answers once in 55 cannot be wrong often.

So **do not point a camera at this today.** Expensify, Dext and QuickBooks read
a photographed receipt far better, because they have cloud OCR and people
checking the output. If your problem is paper into a computer, use one of those.

What does work: **text-layer PDFs**, read with the standard library and no
dependency at all. Of 24 real PDFs, 16 were scans — a photograph in a wrapper,
refused by name — and 6 carried text. Drop those in a folder beside the
statement and `crossfoot check` matches them to charges and crossfoots their
arithmetic.

Full numbers, including the bad ones:
[docs/real-receipts.md](https://github.com/Blahaj-gif/Crossfoot/blob/main/docs/real-receipts.md).

## Into the tool you already use

Crossfoot is not a budgeting app and has no intention of becoming one. It hands
the verdict to whatever you already run, attached to the transaction.

| `--to` | What you get |
|---|---|
| `actual` | **Actual Budget**'s importer. The verdict arrives as `#crossfoot-unchecked` in the note, because Actual filters on hashtags and a verdict written as prose is one nobody can filter on. |
| `firefly` | **Firefly III**'s importer, tags as a real column, plus a `.json` holding the column mapping so it is not twenty dropdowns every month. |
| `beancount` | Unreconciled entries carry beancount's own `!` flag, so `bean-check` surfaces them without anyone remembering a tag. |
| `generic` | A plain CSV with every check that ran. |

```
crossfoot export --inbox ./inbox --to actual --out ledger.csv
```

Five verdicts leave, not three: `crossfoot:accepted-by-you` is its own state,
because a person looked at a discrepancy and made a call, and exporting that as
either "reconciled" or "unchecked" loses the only fact that matters about it.

## Nothing here phones anything

Every exporter writes a file the target's own importer reads. Receipts and
statements are the most sensitive documents most people own, and a tool that
promises they never leave the machine should have no code capable of sending
them. CI asserts the absence of the imports on every push.

To be exact about what that covers: it is a claim about *Crossfoot's* code, not
about what an optional dependency does on its own account. The review window is
Streamlit, whose defaults bind to every interface and send usage telemetry, so
it is started with `--server.address=127.0.0.1` and stats switched off. Before
that flag it was a login-less page of financial documents reachable by anyone on
the same wifi.

**Email intake is deliberately not built.** Fetching from a mailbox means IMAP,
which means this project contains code that opens a socket, and it means holding
a mail credential for a mailbox containing far more than receipts. Every mail
client can already save attachments to a folder, and the inbox sorts by content.

## Installing more than the core

| Extra | For |
|---|---|
| *(none)* | CSV and OFX statements, text-layer PDFs, plain-text receipts. The whole audit. |
| `crossfoot[ocr]` | Photographs, via Tesseract. Needs the system binary. See the measurement above first. |
| `crossfoot[ocr-heavy]` | Photographs with no system package, via EasyOCR. Much larger. |
| `crossfoot[ui]` | The review window, for matching documents to charges. |

Nothing degrades silently. A scanned PDF, or a photograph the engine was unsure
of, is marked **degraded** and its numbers are shown as evidence rather than
used as figures. A photograph with no OCR engine installed is *refused*, because
reading a JPEG as text yields noise a parser will cheerfully find amounts in.

### If you would rather not use a terminal

Double-click `launch/crossfoot.bat` (Windows) or `launch/crossfoot.command`
(macOS). On Linux run `./launch/crossfoot.sh` — whether a desktop runs a script
from a double-click varies, and claiming otherwise would be claiming a behaviour
that depends on which one you have.

They are ordinary text files you can read before running them, on purpose. This
program reads your bank statements, and a script you can open in Notepad is a
better thing to trust than a downloaded binary. That is why there is no `.exe`.

## Why not Expensify, Dext, QuickBooks or Smart Receipts

The blunt half first: **for getting a receipt into a computer they are better
and you should use one.** That is the measurement above, not an opinion.

They are built to get data *in*. None is built to tell you the data is wrong.

- **No bank connection, ever.** QuickBooks reconciles by connecting to your
  bank; the free web tools that audit statements want you to upload one.
- **It refuses.** The others must always produce an answer — an expense report
  with a blank line is a failed product. This one has a third state.
- **First run, nothing installed, no receipts.** All five need you to have been
  using them already.
- **No vendor.** The decision log is one hash-chained file on your disk.

The nearest real competitors are not on that list. They are the free web tools
that scan an uploaded statement, and the answer to those is that you are
uploading your bank statement to a stranger.

## What it actually gets right

Every number here was measured, and the workings are in `docs/`.

**Real bank exports** — 33 fixtures from open-source importers (Capital One,
Schwab, N26 France, GLS Bank, ING España, Outbank, Mint, ANZ, Nubank), none of
whose formats this project chose:

| | |
|---|---|
| parsed | **19 of 33** |
| a parsed field that cannot be traced back to its raw row | **0** |
| rows silently dropped | **0** |
| refusals that turned out to be wrong | **0** |

→ [docs/bank-exports.md](https://github.com/Blahaj-gif/Crossfoot/blob/main/docs/bank-exports.md), including the four bugs they
found — the worst being a running balance walked on rows that were not in date
order, which reported "a row is missing here" on a complete file and silenced
the whole audit with it.

**Receipts** — a corpus of 22, whose expected values were keyed by reading the
paper rather than by running the parser. As text, all 22 read exactly. As
images, damaged eleven ways: 17 of 22 on a clean render, 12 on low resolution,
1 when every damage is applied at once — and **zero** wrong figures recorded on
any of the eleven.

**On real paper that figure does not transfer**, and the reason is worth
knowing: those 22 receipts were written for this project, so every label in them
was a label the parser already knew. Real receipts say `TOTAAL`, `UKUPNO`,
`Te betalen`. → [docs/real-receipts.md](https://github.com/Blahaj-gif/Crossfoot/blob/main/docs/real-receipts.md)

589 tests, run on every push.

## The wall

`crossfoot audit`, `check`, `export`, the matcher and the queue can all be
handed to an assistant. None of them can clear a queue item.

Reading the decision log and writing to it are two modules: `review/ledger.py`
reads and contains no function that appends, `review/decisions.py` is the write
path, and `review/app.py` is its only importer. CI reads the import graph on
every push. It is a repository boundary, not a security one — any process on
this machine can import the writer. What makes that visible afterwards is the
hash chain, not the split.

Decisions append to `decisions.jsonl`, fsynced per click, each carrying the
numbers the person was actually shown. Re-read a document, get a different
total, and the old approval no longer applies to it.

## Whether this should exist

Searching GitHub for a tool that reconciles receipts against a bank statement
returns five repositories. All five were created between 30 June and 8 August
2026 and abandoned within days — 2, 4 and 6 commits. The first reading was that
finishing is therefore the moat.

Looking harder made that weaker. Actual Budget's most-reacted feature request is
[attaching receipts to transactions](https://github.com/actualbudget/actual/issues/530),
with 195 reactions, **closed as completed in 2023**. The professional version of
the problem is real, expensive, and served by Dext, Expensify, Ramp and BILL.
That same community's request for duplicate detection has **3 votes**. And
*nobody, anywhere, has filed an issue asking for a tool that checks a receipt's
own arithmetic.*

So the empty field may be empty because the part people want is elsewhere and
already built, and five abandoned repositories are as consistent with "everyone
discovers there is nothing here" as with "nobody finishes things".

That is not settled by writing more of this. It is settled by
[the demand test](https://github.com/Blahaj-gif/Crossfoot/blob/main/docs/demand-test.md), whose threshold was written down before
any results arrived: 25 people running it on their own statements, and 5 saying
the *verdict* changed something they did. If that fails, the right ending is to
leave this as a small finished tool and go and find a problem somebody is
already trying to pay for.

## Licence

MIT. See [docs/direction.md](https://github.com/Blahaj-gif/Crossfoot/blob/main/docs/direction.md) for where this is going and why.
