# The receipt result measured two engines, not the problem

## What was claimed

The README reported *0 of 112 receipts satisfying their own arithmetic* across
six image pipelines, and concluded that photographed receipts are out of reach
here. The engines behind that number were **Tesseract** and **EasyOCR**.

An outside review made the point that six preprocessing pipelines all failing —
or making it worse — is the signature of a ceiling on the **model** side, not
the image side, and that the iterations had been spent on the wrong half of the
problem. It named four engines that had never been tried: PaddleOCR, RapidOCR,
Surya and docTR.

That was worth testing rather than arguing about.

## What was run

**RapidOCR** (`rapidocr-onnxruntime`, CPU, no network — the no-network
principle survives) against the same 112 photographs already committed in
`tests/corpus/photographs`, with no preprocessing at all.

The measure is deliberately **not** a reconciliation rate. Crossfooting is a
conjunction: forty numeric fields at 98% per-field accuracy reconcile about 45%
of the time and at 92% essentially never, so a single pass/fail number collapses
a wide range of engine quality into one zero. What is counted instead is how
much the engine reads at all:

- **any text** — did it return anything
- **three or more money-shaped amounts** — is there enough on the page for
  arithmetic to be possible

## What happened

| | Tesseract / EasyOCR | RapidOCR |
|---|---|---|
| errored | — | **0 of 112** |
| produced any text | — | **100 of 112** |
| produced figures at all | **1 of 112** | — |
| three or more amounts | — | **31 of 112** |
| median line confidence | — | 0.914 |

By kind, and this is the part that matters:

| kind | n | any text | 3+ amounts |
|---|---:|---:|---:|
| supermarket | 9 | 9 | **7** |
| restaurant | 6 | 6 | **5** |
| modern | 8 | 8 | 4 |
| damaged / faded | 6 | 6 | 3 |
| fuel | 5 | 5 | 2 |
| mall retail | 8 | 5 | 2 |
| atm | 8 | 8 | 1 |
| bank teller | 8 | 8 | 1 |
| bank transit | 7 | 7 | 1 |
| historic | 8 | 8 | 0 |
| logo letterhead | 8 | 8 | 0 |
| market | 8 | 4 | 0 |
| yellowed thermal | 8 | 5 | 0 |
| control — not a receipt | 5 | 3 | 0 |

**On the receipts that have line items to crossfoot in the first place —
supermarket and restaurant — it reads amounts off 12 of 15.** One receipt
yielded 51 money-shaped strings. The controls that are not receipts yielded
none, which is the right answer.

## What this does and does not mean

**It does not mean 31 receipts reconcile.** Reading amounts is not the same as
identifying which are line items and which is the total, and every one of them
still has to be exactly right. That work was never built, because the earlier
measurement said there was no point.

**It does mean the earlier conclusion was about two engines rather than about
photographed receipts.** "0 of 112" was true of Tesseract and EasyOCR and is not
a property of the domain. The review's diagnosis — that six preprocessing
pipelines failing points at the model, not the image — is supported.

**And it does not change the no-inference rule.** The rule that makes the
statement audit trustworthy is what makes receipt extraction hard here, and
that remains the honest finding: same principle, opposite outcomes in two
domains. A better engine moves where the wall is; it does not remove it.

## Second pass: can the amounts be resolved into line items and a total?

Reading amounts is necessary and not sufficient. The follow-up asks the
product's own question directly — **does some subset of the amounts sum to
another amount?** — on all 112, with no layout information at all.

| | receipts |
|---|---:|
| a subset sums exactly to the largest amount | **18** |
| within 10 cents, or one known digit confusion away | 3 |
| neither | 10 |
| fewer than three amounts to work with | 81 |

**Half of the exact hits have to be thrown out, and saying so is the point.**
A subset search over *n* amounts tries 2^(n-1) combinations against a target
space of maybe 50,000 cent values, so on a busy receipt a hit is likely by
chance:

| amounts on the page | exact hits | chance of a spurious hit |
|---:|---:|---:|
| 4–8 | **12** | under 0.3% each |
| 9–12 | 2 | 0.5%–4% |
| 14–53 | 4 | 15%–93% |

So the defensible figure is **12 receipts where the arithmetic is available and
the match is not coincidence**, not 18. On the busy pages this method cannot
tell signal from luck, which is itself the finding: a real implementation needs
column positions, not just a bag of numbers.

## The receipt the README named

The README singled out one paper receipt as the only one that produced figures,
and as producing **wrong** ones: *"Tax 6.28 against a printed 6.20, and a total
of 46.17 against a printed 86.17, because the engine read an 8 as a 4."*

That is `mall_retail--shiekh-shoes-at-westminster-mall-receipt-2002.jpg`.
RapidOCR reads it:

```
  79.97          item
   6.20          tax          <- printed 6.20, previously read 6.28
 $86.17          total        <- printed 86.17, previously read 46.17
 100.00          tendered
 Change$ 13.83
```

**79.97 + 6.20 = 86.17**, exactly, and 100.00 − 86.17 = 13.83, exactly. Both
figures the earlier engines got wrong are right, including the specific 8→4
confusion that was called out. The other Westminster receipt in the corpus
(Fanzz) reads 7.99 + 0.62 = 8.61 with a 7.750% tax line, also exact.

One receipt is one receipt. But it is *the* receipt this project chose as its
worked example of the failure, and it is no longer a failure.

## What would come next, if this is picked up

In order, and each measurable before the next:

1. ~~Distance to reconciliation~~ — **done above.** 12 receipts where the
   arithmetic resolves and the match is not coincidence, 3 more within a digit.
2. **Layout, not a bag of numbers.** The busy receipts are where this method
   fails, and it fails because it throws away column positions. RapidOCR returns
   a box per line; using the x-position to separate an amount column from a
   quantity column is the difference between 12 defensible receipts and the
   busy ones being readable at all.
3. **Per-field character error rate** against hand-read ground truth, on the
   receipts layout makes tractable. Still does not exist for any engine.
4. Only then, the **propose-and-confirm** state: arithmetic used as a constraint
   that *proposes* a corrected read, surfaced in the review window that already
   exists, becoming a figure only when a human confirms it. That is not
   inference asserted as fact, which is what the rule forbids.

None of this is scheduled. It is written down because the earlier number is now
known to have been about the wrong thing, and leaving that uncorrected would be
the failure this project is built to avoid.

## Reproducing

```
pip install rapidocr-onnxruntime
python docs/ocr-retest.py            # amounts found, by kind
python docs/ocr-lineitems.py         # does a subset sum to the total
```

Runs in about five minutes on a CPU for all 112, no network.
