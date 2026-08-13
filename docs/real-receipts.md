# 55 real receipts, and what they say about the accuracy figure

The README quotes 17 of 22 on a clean render and 12 of 22 on a low-resolution
one. Both numbers are true and neither transfers, and this is the measurement
that shows why.

## The corpus that flattered itself

The 22-receipt corpus is rendered from receipt text **written for this
project**. Its expected values were keyed by reading the paper rather than by
running the parser, which was the precaution taken at the time, and it is not
enough: the receipts and the parser were written by the same author, so every
label in the corpus is a label the parser already knew. `SUBTOTAL`, `TAX`,
`TIP`, `TOTAL`. Agreement between two things one person wrote measures
consistency, not accuracy.

Real receipts say `TOTAAL`, `UKUPNO`, `Te betalen`, `합계`, `TOTAL INCLUDES
VAT OF`.

## The batch

55 photographs from Wikimedia Commons, every one freely licensed, chosen to
spread across kinds rather than sampled at random — a random draw would have
been three quarters Dutch fuel stations, because one person photographed a lot
of them, and an accuracy figure from that measures one till.

| bucket | n | what is in it |
|---|---|---|
| supermarket | 11 | Lidl, Aldi, Ekoplaza, Bọn Bini, Family Dollar, Tesco 1994 |
| historic | 8 | NARA receipts 1706–1802, handwritten; telegraph company 1944 |
| restaurant | 8 | Nepal, Croatia, Hong Kong, Mariupol, Switzerland, Korea |
| bank_transit | 7 | CTBC Bank, Suruga Bank Visa, taxi, metro, USPS |
| damaged_faded | 7 | a 1988 Intershop slip, one titled "receipt that was badly scanned" |
| fuel | 5 | AVIA, TinQ, Fieten Olie, a German Tankquittung |
| control_not_a_receipt | 5 | a blank white till receipt (an artwork), a roll of thermal paper, a bill of lading |
| electronic | 4 | a bank transfer confirmation, a bill-pay screenshot |

`tests/corpus/batch.json` carries the file list, the source URL and the licence
of each, so the measurement can be repeated. The images are not in the
repository.

## What happened

| | |
|---|---|
| refused as unreadable | **52 of 55** |
| produced a total | **1** — and it is a bill-pay screenshot, not paper |
| produced *any* money field with the refusal gate switched off | **7 of 55** |
| recorded a figure that is wrong | **0** |
| crashed | 0 |
| slowest | 5.0s; median 0.8s |

The safety property holds on real paper exactly as designed, and it is close to
vacuous there: a tool that answers once in 55 cannot be wrong often. **The
honest summary is that the checking layer works and the reading layer does not
yet feed it.**

## Where it actually fails

Taking the ten receipts whose numbers were keyed by hand, and asking whether
the total was legibly present in the text the engine returned:

- **The engine did not return the amount at all** — 4 of 10. A crumpled Tony's
  Pizzeria receipt, a Family Dollar receipt photographed in blue shade, the
  1988 Intershop slip twice.
- **The engine returned it and misread a digit** — the Papua New Guinea
  receipt: `TOTAL 19.30` where the paper says `19.50`. Loud rather than silent,
  and still wrong.
- **The engine returned it and the parser did not know the word** — the AVIA
  fuel receipt prints `TOTAAL`. That is now fixed, and fixing it changed
  nothing, because on the same receipt the engine read the amount beside it as
  `e.74`.
- **Read correctly** — 1 of 10. A USPS receipt from 2002.

That last group of one is the number to keep in mind. **The reading layer is
the binding constraint; the parser is not.** Every parser fix in this pass was
correct and none of them moved the result.

## Three bugs this found

- **A reading of two words scored 100% confident and "not degraded"**, because
  the doubt test is a *ratio* and two certain words contain no doubt. It was
  the most trusted reading in the batch, off a receipt the engine had almost
  entirely failed to read. There is now a floor under how little counts as a
  reading.
- **An engine that is installed but will not load was reported as "not
  installed"**, sending somebody to reinstall working software. Found live: a
  file named `select.py` in the working directory shadows the standard
  library's `select`, which breaks `socket`, which breaks what pytesseract
  imports. `doctor` now says which of the two it is.
- **A photograph can contain two receipts.** One Lidl picture has two, side by
  side. Nothing in this project has a concept of that: the paper-finder draws
  one box around both, and the fields of two receipts would be read as one.
  Not fixed — it needs a design decision, not a patch.

## What this does not measure

Nobody's own receipts. These were chosen partly because they were licensed,
which is not how a person's camera roll is chosen. A photograph taken
deliberately, in good light, of a receipt the photographer intends to check, is
a different and probably easier population than a photograph uploaded to
Commons to illustrate an article.
