# 33 real bank exports

The Stage 1 gate is "20 real exports parse without a **silent** mis-parse", and
the word doing the work is *silent*. A refusal is a fine outcome — this project
is built on refusing. What must not happen is a file that parses into numbers
which are not the numbers in the file.

## Where they came from

Fixtures from open-source importers and parsers: `csv2ofx`, `ofxparse`,
`ofxtools`, `hledger`, `gnucash`. Importer authors commit the file their own
bank gave them, because that is what the importer has to read — so these carry
real header spellings, real delimiters, real date orders and real locale
conventions. Capital One, Schwab, N26 France, GLS Bank, ING España, Outbank,
Mint, Payoneer, PC Mastercard, ANZ, Fidelity, Nubank.

None of the formats was chosen by this project, which is the whole point. The
22-receipt corpus taught that a corpus written by the parser's own author
measures agreement rather than accuracy.

`tests/corpus/bank_exports.json` lists them.

## How they were checked without hand-keying 33 files

Every parsed amount and date must be **traceable**: its digits have to appear in
the raw text of the row it came from. That is weaker than reading each file and
typing what it says — it cannot catch a parser that picks the *wrong* number off
a row — and it is honest about being weaker. It is also what found the bugs.

## Result

| | |
|---|---|
| parsed | **19 of 33** |
| untraceable fields | **0** |
| rows silently dropped | **0** |
| crashes | **0** |

The 14 refusals, every one of them checked by hand:

| why | files |
|---|---|
| not a bank statement | an Amazon order export, an OFX account listing, an OFX profile response, an error response, two investment statements, an empty `<OFX></OFX>` |
| no header at all | an hledger sample of three unnamed columns |
| a header repeated in the middle of the data | a Mint sample — likely two exports concatenated, which this refuses on purpose elsewhere too |
| dates that genuinely cannot be resolved | two files where no row anywhere puts a day above the twelfth, so nothing settles day-first from month-first |

None is a coverage gap. All four gaps that *were* found are fixed below.

## What the files found

**Semicolon-separated exports were read as a single column.** `csv.DictReader`
defaults to a comma, so every European export arrived with one enormous field
and was refused for having no amount in it. That is the European convention, and
it is the European convention *because* the comma is the decimal mark there —
the same population this project already goes to real trouble to read money for.
Reading their decimal separator and not their column separator was half a job
done twice.

**`Amount (EUR)` matched no column.** It normalised to `amount eur`, and the
header table is matched exactly. A whole bank's exports refused for having said
which currency they were in.

**A header below a blank line or a preamble was not found.** Mint's own sample
opens with three empty lines; real exports from high-street banks open with an
account number and a period. `csv.DictReader` took the first line as the header
whatever it was, which surfaced as "no amount column found" on a file whose
header plainly says Amount.

**A running balance was walked on rows that were not in date order.** Found on a
real ING España export. Its rows arrive in no date order, so the balance is not
a chain; the walk broke on the first pair and reported *"a row is missing here"*.
That was false, and because a failed completeness check suppresses every
finding, the whole audit went silent on a complete file.

That last one is the serious one. It is the tool being confidently wrong about
somebody's bank statement, which is the single thing it is built not to do, and
it took a real file to find it. The walk is now **unrun** rather than failed
when the order is not there: sorting first would invent an order the bank never
stated, and rows sharing a date have none to recover.

## What this does not measure

The gate says 20 and this reached 19. More importantly, the traceability check
cannot catch a parser that reads the wrong number off the right row — a debit
column mistaken for a credit, an amount taken from the balance column. Those
need a person reading the file, and nobody has done that for these 33.

And none of them is anybody's real statement, with their real merchants and
their real duplicate charges. That is Stage 2, and it has still not been run.
