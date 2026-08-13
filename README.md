# Crossfoot

Receipts and statements in. A **verdict** out, not a category.

Every other receipt tool draws you a pie chart of where the money went. The
chart is the part that does not matter, because it is drawn on numbers nobody
checked. Crossfoot's product is the check.

> *Crossfooting* is the auditor's practice of verifying that a row's total and
> its column's total agree: two independently derived numbers about the same
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
| 1 | **Drop.** Drag the bank export and the receipts into the window, or into one folder. Which file is which is decided by *reading* them, so their names do not matter. | accept a statement whose own running balance does not step correctly row to row, or whose rows do not sum to its declared period total: that export is truncated, and every verdict downstream would rest on a partial ledger. |
| 2 | **Read.** Docling for PDFs, Tesseract or EasyOCR for photographs, plain text otherwise. Every field keeps its confidence, the line it came from, and (from a photograph) the rectangle on the page. | use a total it read below threshold. It names the field and shows you the crop of the actual paper it was read from. |
| 3 | **Match.** Amount, date window, merchant string. Fuzzy on the name, exact on the cents. | auto-resolve a tie. A guess that looks like a match is worse than a gap that looks like a gap. |
| 4 | **Crossfoot.** The four checks. | widen a tolerance far enough to hide a magnitude error. Rounding gets cents; nothing gets a percent. |
| 5 | **Review.** Only failures and unchecked reach a human, ordered by money at risk. | let an assistant clear the queue. Approval is a keystroke in your window; there is no path to it from the model's side. |
| 6 | **Export.** CSV, Beancount, Firefly III, Actual Budget, verdict attached as a tag. | export an *unchecked* row as though it reconciled. |

Step 6 is the strategy. Crossfoot does not compete with Firefly III or Actual
Budget. They have 52,000 stars between them and no receipt verification at
all. It feeds them.

## Status

All six steps exist. 495 tests, including a corpus of 22 receipts run both as
text and as images through Tesseract. See *What it actually gets right* below
for the numbers.

### If you would rather not use a terminal

Download this repository, then **double-click** `launch/crossfoot.bat`
(Windows), `launch/crossfoot.command` (macOS) or `launch/crossfoot.sh` (Linux).
The first run sets itself up and takes a minute; every run after opens the
window. You still need Python installed. The script says so, and points you at
python.org if you do not.

They are ordinary text files you can read before running them, on purpose.
This program reads your bank statements; a script you can open in Notepad is a
better thing to trust than a downloaded binary, and it is why there is no
`.exe` here.

### The window

```
crossfoot            opens it, and it does everything:
                     drop the files in, see what does not add up,
                     decide, and download the result
crossfoot doctor     what this computer can read, and how to fix what it cannot
```

Nothing is uploaded. The window is a page served by your own machine to your
own browser.

### From the command line, if you prefer

```
pip install -e ".[dev]" && pytest

crossfoot check  --inbox ./inbox                      # read-only
crossfoot export --inbox ./inbox --to actual --out ledger.csv

# --statement FILE --receipts DIR still works if you keep them apart
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

## Being billed twice

The one finding here that needs no receipt at all, so it works on the first run
before you have photographed anything — and the only one that can hand you
money back rather than telling you your paperwork is tidy.

```
2 possibly billed twice, 7 need you, 1740.75 at risk, 0 reconciled, 5 unchecked
-------------------------------------------------------------------------------
possible duplicate        842.19  2026-08-14  HOME DEPOT #4471
            two charges of 842.19 at this merchant, the same day
possible duplicate          4.20  2026-08-06  SQ *BLUE BOTTLE 0042
            two charges of 4.20 at this merchant, the same day
```

Nothing asserts a duplicate. Two identical charges are a fact; whether that is
one purchase billed twice or two coffees on a Saturday is not in the statement.
So it shows the pair and says what makes it suspicious, and you decide.

Suppressed, because an alarm that fires twelve times a year teaches people to
skim: a run whose gaps all sit near a month is a subscription, and a refund of
the same amount afterwards means it was already put right — still shown,
because it says the merchant does this, but not counted as at risk.

## Into the tool you already use

Crossfoot is not a budgeting app and has no intention of becoming one. It hands
the verdict to whatever you already run, attached to the transaction, where it
will still be legible next April.

| `--to` | What you get |
|---|---|
| `actual` | **Actual Budget**'s importer: Date / Payee / Notes / Amount. The verdict arrives as `#crossfoot-unchecked` in the note. Actual reads hashtags out of notes, and a verdict written as prose is one nobody can filter on. |
| `firefly` | **Firefly III**'s data importer, with tags as a real column, plus a `.json` beside the CSV holding the column mapping, so it is not twenty dropdowns the first time and twenty again next month. |
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

Five verdicts leave, not three. `crossfoot:accepted-by-you` is its own state.
A person looked at a discrepancy and made a call, and exporting that as either
"reconciled" or "unchecked" would lose the only fact that matters about it.

**Nothing here phones anything.** Every exporter writes a file the target's own
importer reads. That is the property the project is for, not a limitation
worked around: receipts and statements are the most sensitive documents most
people own, and a tool that promises they never leave the machine should have
no code capable of sending them. CI asserts the absence of the imports.

## Reading what you actually have

| Extra | For |
|---|---|
| *(none)* | CSV and OFX statements, plain-text receipts. The checking layer is arithmetic and stdlib — nobody should install a machine-learning stack to reconcile numbers they already have. |
| `crossfoot[ocr]` | Photographs, via Tesseract. Needs the tesseract binary; fast and accurate, and it reports a confidence and a rectangle per word. |
| `crossfoot[ocr-heavy]` | Photographs with no system package, via EasyOCR. Much larger install. |
| `crossfoot[read]` | PDFs, via Docling. |
| `crossfoot[ui]` | The review window. |

Nothing degrades silently. A PDF read without Docling, or a photograph the
engine was unsure about, is marked **degraded** and its numbers are shown as
evidence rather than used as figures. A photograph with no OCR engine installed
is *refused*, because reading a JPEG as text yields binary noise that a parser
will cheerfully find amounts in.

Every engine runs locally on data already on your machine. There is
deliberately no cloud OCR backend: an OCR API is the one line of code that
would turn "your receipts never leave this machine" into a lie, and EasyOCR is
constructed with `download_enabled=False` so it cannot fetch weights either.

### What is deliberately not built

**Email intake, and it is not an oversight.** Fetching receipts from a mailbox
means IMAP, which means this project contains code that opens a socket. "No
code here is capable of making a network request", asserted by CI, is doing
more work for the people this is for than an email feature would. It would also
mean holding a mail credential, which is a second secret to protect, for access
to a mailbox containing far more than receipts.

It is also unnecessary. Every mail client can save attachments to a folder, and
the inbox sorts by content, so a rule in *your* mail client drops receipts
straight in and Crossfoot never sees your mail. Same outcome, none of the cost.

`split` and `correct` are accepted as decisions and recorded, but nothing yet
consumes them. There is no MCP server — when there is, it will import the queue
and the *ledger reader*, never the writer, which is the separation CI already
enforces.

## What it actually gets right

Two measurements, both on the same 22-receipt corpus, whose expected values
were written by reading the paper rather than by running the parser.

**As text**, every field on all 22 reads exactly as stated, and none of them
reconciles on a wrong reading.

**As images**, rendered and then damaged eleven ways, read with Tesseract:

| | read exactly | silent passes |
|---|---|---|
| uneven lighting | 18 / 22 | **0** |
| sensor noise | 18 / 22 | **0** |
| clean | 17 / 22 | **0** |
| faded (thermal paper in a wallet) | 17 / 22 | **0** |
| folded across the middle | 17 / 22 | **0** |
| photographed at an angle | 16 / 22 | **0** |
| blurred | 15 / 22 | **0** |
| JPEG at quality 30 | 15 / 22 | **0** |
| rotated | 13 / 22 | **0** |
| low resolution | 12 / 22 | **0** |
| **all of it at once** | 1 / 22 | **0** |

The second column is the only one that is asserted, and it means something
narrower than it used to: a field the tool **recorded a number for** where the
number is not what the paper says. A field it declined to record is counted
against the first column, printed, and not asserted on — refusing puts no
figure in anybody's ledger, and that is the entire mechanism by which the
second column stays at zero. The two were counted as one thing until a
photograph made the difference matter.

Tesseract misreads digits: a zero becomes an eight, a `0.50` becomes `Q.50`. It
happens on a quarter of these receipts and, across eleven kinds of damage,
**not once does a wrong figure come out reconciled**. The tool is not promising
to read your receipt perfectly. It is promising to tell you when it did not.

Three things make that hold. The bank statement is a CSV, so OCR cannot corrupt
it, and a receipt misread even *consistently* still fails against a number that
was never photographed. A photograph the engine could not make out is refused
as a whole rather than mined for whichever fields happened to survive. And a
receipt has one decimal mark — an amount printed with the other one has been
misread, and is dropped rather than believed.

Low resolution used to read 2 of 22. A phone at arm's length gives the engine
fewer pixels per character than it needs, and below that density it stops
reading letters and starts reading shapes: `TOTAL` as `oral`, `SUBTOTAL` as
`susToTAL`. The amounts survive, because digits are simpler, and the labels do
not — so no line has a label and a number on it. Reading such a page a second
time, enlarged, takes it to 12. Enlarging *everything* was measured first and
was a clear loss: accuracy fell on seven of the eleven and wrong figures
appeared on nine, including on a clean render, because a second reading of an
already-legible photograph is not a better reading, it is a different wrong one.

**All of it at once is still the honest bad news.** A badly degraded photograph
comes back unchecked with a reason, which is the correct answer and not a
useful one.

### On real paper: the number above does not transfer

**55 photographs of real receipts. 52 refused. One produced a total, and it is
a bill-pay screenshot rather than paper.** With the refusal gate switched off
entirely, 7 of the 55 produce any money field at all. Nothing crashed, nothing
recorded a wrong figure, and the median receipt took 0.8 seconds.

The full method, the buckets, and the file-by-file result are in
[docs/real-receipts.md](docs/real-receipts.md); `tests/corpus/batch.json`
carries the source and licence of every image so it can be repeated.

**Why the 17 of 22 above is not a forecast of that.** The 22-receipt corpus is
rendered from receipt text written for this project. Its expected values were
keyed by reading rather than by running the parser — which was the precaution
taken at the time, and it is not enough, because the receipts and the parser
had the same author. Every label in that corpus was a label the parser already
knew. Real receipts say `TOTAAL`, `UKUPNO`, `Te betalen`, `합계`.

So the safety property holds on real paper exactly as designed, and it is close
to vacuous there: a tool that answers once in 55 cannot be wrong often. The
checking layer works. **The reading layer does not yet feed it**, and no parser
fix in this pass moved the result — the Dutch `TOTAAL` was added to the label
list, and on the same receipt the engine read the amount beside it as `e.74`.

Six of the 55 were keyed field by field, and they found two bugs the rendered
corpus structurally could not:

- A flat, sharp, entirely legible scan produced **zero words** at every page
  segmentation mode. The receipt was lying on a blue desk mat, and Tesseract
  binarises the whole frame against one threshold, so the mat decided where the
  threshold fell and the ink landed on the wrong side of it. Finding the paper
  and cropping to it takes the same file to 114 words at 71% confidence. A
  rendered receipt is paper edge to edge and has no desk in it, so no amount of
  damage applied to one could ever have shown this.
- `TOTAL INCLUDES VAT OF   1.77` was read as the total, and by the rule that a
  later `TOTAL` beats an earlier one it overwrote the real one. The receipt
  reported a total of 1.77 against a charge of 19.50. That phrasing is printed
  on VAT-inclusive receipts across most of the world.

And one it cannot fix by patching. **A photograph can contain two receipts** —
one Lidl picture in the batch has two, side by side. Nothing here has a concept
of that: the paper-finder draws one box around both, and two receipts' fields
would be read as one. That needs a design decision rather than a patch, and it
is not made yet.

**So: should you point a camera at this today? No.** Feed it PDFs and emailed
receipts, where the text is text and none of the above applies, and feed it
your statement, which is a CSV that OCR cannot touch. The photograph path is
measured, honest and not ready.

If you photograph a few of your own receipts and they come out wrong, that is
still the most useful bug report this project can receive.

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
[attaching receipts to transactions](https://github.com/actualbudget/actual/issues/530),
with 195 reactions, and it was **closed as completed in 2023**, with four later
duplicates closed the same way. The professional version of the problem is real
and expensive (bank reconciliation runs about 11 hours per client per month in
firms that do bookkeeping) and is served by Dext, Expensify, Ramp, Concur, BILL
and others. Meanwhile *nobody, anywhere, has filed an issue asking for a tool
that checks a receipt's own arithmetic* , which is the only thing Crossfoot
does that those do not.

So the empty field may be empty because the part people want is elsewhere and
already built, and five abandoned repositories are as consistent with "everyone
discovers there is nothing here" as with "nobody finishes things".

That question is not settled by writing more of this. It is settled by
[the demand test](docs/demand-test.md), whose threshold was written down before
any results arrived: 25 people running it on their own statements, and 5 saying
the *verdict* changed something they did. If that fails, the right ending is to
leave this as a small finished tool and go and find a problem somebody is
already trying to pay for.
