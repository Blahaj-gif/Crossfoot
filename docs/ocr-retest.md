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

## What would come next, if this is picked up

In order, and each measurable before the next:

1. **Per-field character error rate** on the 31, against hand-read ground
   truth. That is the number that says whether arithmetic is even worth
   attempting, and it does not exist yet for any engine.
2. **Distance to reconciliation** — how many receipts are off by exactly one
   digit. The Westminster receipt was a single 4↔8 confusion. If a meaningful
   share sit at distance one, the bar is misplaced rather than unreachable.
3. Only then, the **propose-and-confirm** state: arithmetic used as a constraint
   that *proposes* a corrected read, surfaced in the review window that already
   exists, becoming a figure only when a human confirms it. That is not
   inference asserted as fact, which is what the rule forbids.

None of this is scheduled. It is written down because the earlier number is now
known to have been about the wrong thing, and leaving that uncorrected would be
the failure this project is built to avoid.

## Reproducing

```
pip install rapidocr-onnxruntime
python docs/ocr-retest.py            # writes ocr_retest.json
```

Runs in about five minutes on a CPU for all 112, no network.
