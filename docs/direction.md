# Which project this should be

Written after the 55-receipt measurement, which is the first evidence in this
project's life that did not come from a corpus it wrote itself. That
measurement did not just lower a number. It invalidated the premise the
photograph path rested on, and the premise is what the whole product was shaped
around.

The question is no longer "how do we read receipts better". It is "given that
reading receipts is not going to work soon, what is this".

---

## Part 1 — The three options, assessed

### The evidence all three are judged against

**Measured here:**

| | |
|---|---|
| receipts read exactly, own rendered corpus | 17 / 22 |
| totals produced, 55 real photographs | **1 / 55**, and that one is a screenshot |
| any money field, refusal gate switched off | 7 / 55 |
| wrong figures recorded, 55 real photographs | 0 |
| statement path | 529 tests, no OCR anywhere near it |
| **PDF path** | **docling not installed; one test, asserting a PDF is unreadable without it; the reader branch marked `no cover`** |

That last row matters more than it looks. The obvious retreat from "cameras do
not work" is "then use PDFs" — and **the PDF path has never been measured
either**. It is the photograph path twelve months ago: an optional heavy
dependency, an untested branch, and a README sentence asserting it works.
Recommending it on that basis would be repeating, in the same week, the exact
error the 55 receipts just exposed.

**Found by desk research** (which ranks options; it does not settle them —
see *The gate that still has not been run*):

- Actual Budget's [2026 roadmap](https://actualbudget.org/blog/roadmap-for-2026/)
  is plugins, goals UI, mobile parity, a transaction-table rewrite and a debt
  account type. **Receipts, attachments, documents and OCR do not appear.**
  Plugins land in the first months of 2026, which is a distribution channel
  arriving at a useful moment.
- Firefly III's [Paperless-NGX integration discussion](https://github.com/orgs/firefly-iii/discussions/9467):
  4 upvotes, 7 participants. What users actually asked for was **linking a
  document to a transaction, and matching by merchant and date**. There is
  **no mention of OCR, amount extraction, or reconciliation** anywhere in it.
  The maintainer's reply: "the interest seems a little low."
- A live commercial market exists for **auditing a bank statement for recurring
  and duplicate charges** — several products, explicitly "upload your
  statement", "no bank login required". No self-hosted or open-source one
  surfaced.

Read together: the arithmetic-on-a-photograph job has **no evidenced demand
anywhere**, the document-linking job has weak evidenced demand, and the
statement-audit job has demand strong enough that people are being charged for
it.

---

### Option A — Digital-first

*Narrow to PDF and emailed receipts. Mark the camera experimental.*

**Potential.** The arithmetic layer is genuinely good and would finally be fed
clean text. Everything already built keeps working.

**Demand.** Weak, and worse than it looks. The people with emailed PDF invoices
are small businesses, who are served by accounting software that already
reconciles. The consumer with a shoebox of paper is the one who needs this, and
this option is exactly the one that abandons them.

**Structure.** `read/document.py` grows into the real reader; `read/ocr.py`
becomes a marked-experimental branch. Multi-receipt photographs become moot.

**The disqualifying problem.** It substitutes one unmeasured claim for another.
Before this could be recommended, docling would have to be installed, tested
against real PDF invoices, and measured — and docling pulls a deep ML stack
into a project whose stated virtue is that its core has no required
dependencies. That is a large bet placed on an untested assumption to escape a
tested failure.

**Verdict: not until the PDF path is measured.** It might be right afterwards.
It cannot be chosen before.

---

### Option B — Invest in the reading layer

*Per-language models, layout-aware parsing, possibly a local vision model.*

**Potential.** If it worked, the original product works.

**Demand.** None found for the actual output. Nobody asked for a receipt's
arithmetic to be checked. They asked for the document to be attached, and
Actual Budget's most-reacted request for that (195 reactions) was closed as
completed in 2023.

**Structure.** Language detection, per-language Tesseract data, a layout model
for two-column receipts, multi-document segmentation, VAT-table parsing. Each
is real work. A local vision model would read these receipts far better and
would break the property that makes refusal safe: a VLM's errors are
unbounded and unmeasurable in the way a threshold's are not, and the promise
that documents never leave the machine survives only if it is genuinely local,
which means a heavy model.

**The disqualifying problem.** It is the most expensive option, aimed at the
job with the least evidence, against competitors who already do the reading
half better — Paperless-ngx has done OCR document management for years, and
the ecosystem's answer to "extract amounts" is already Paperless plus
automation.

**Verdict: no.** This is building the hard thing nobody asked for.

---

### Option C — Statement-first

*The product is the verdict on the **statement**. Documents are evidence when
they parse, and their absence is itself a finding.*

**Potential.** Everything load-bearing already exists and is measured: statement
parsing, the balance walk, duplicate detection with subscription suppression,
the matcher, the three-state verdict, the hash-chained decision log, the queue.
None of it touches OCR. The 55-receipt result stops being a failure and becomes
a documented boundary: a charge whose document could not be read is
**undocumented**, which is a true and useful answer rather than a broken one.

**Demand.** The best-evidenced of the three. People pay for statement audits
today; no self-hosted option surfaced; and the privacy argument is strongest
precisely here, because a statement is the most sensitive file in the story and
this reads it with no network and no bank login.

**Structure.** The reading layer stops being the critical path and becomes an
optional enrichment. The verdict model is unchanged — *unchecked is never
counted as clean* is exactly what "this charge has no document" means.

**The honest weakness.** The document-linking half has only 4 upvotes behind
it. C's strong leg is the statement audit; its second leg is thinner, and the
plan below is staged so that the strong leg ships first and alone.

**Verdict: this one.**

---

### The multi-receipt decision, folded in

Under A or B it must be solved: segment the image, or refuse. Under C it costs
one sentence — **a photograph containing two documents is reported as
containing two documents, and both charges stay undocumented.** Refusing is
correct here rather than merely cheap: splitting an image and being wrong about
where the split goes would read one receipt's total against another's items,
and the arithmetic would be self-consistent nonsense. That is the silent-pass
shape this project exists to prevent.

---

## Part 2 — The draft

### What it is

> **Crossfoot reads your bank statement and tells you three things: whether the
> statement itself is sound, which charges look wrong, and which charges have
> nothing to back them up.**
>
> It never sees your bank. It never touches the network. And it never counts a
> charge it could not check as a charge that passed.

### The experience

A person exports a CSV from their bank, drops it in a folder, and runs one
command or double-clicks the launcher. They do not configure anything. Within a
second or two they are looking at a page with three sections.

**1. Is this statement whole?** Before any finding, the statement is checked
against itself: does every balance follow from the one before it, does the
declared total match the rows, is there a gap in the dates. A statement that
fails this is said to be incomplete *and nothing else is reported from it*,
because findings from a partial export are worse than no findings.

**2. What looks wrong.** Ranked by money at risk, not by count.

```
  £71.98   PAID TWICE          NOW TV          two charges, 14 Mar and 14 Mar
  £14.99   PRICE ROSE          Spotify         £11.99 → £14.99 from 02 Apr
  £9.99    STILL CHARGING      Audible         12 months, last used …unknown
  £4.50    NEW RECURRING       unrecognised    3 charges, monthly, since Jan
```

Each row opens to the transactions it is made of. Nothing is deleted, nothing
is auto-categorised, and no advice is given about whether to cancel anything.

**3. What has nothing behind it.** Every charge over a threshold the person
sets, in one of three states, and the third is the point of the whole project:

```
  documented     412 charges   a document was found and it agrees
  contradicted     3 charges   a document was found and it does NOT agree
  unchecked       48 charges   no document, or one that could not be read
```

`unchecked` is never folded into `documented`. The count is shown at the top of
the page, permanently, because the number people want to believe is the first
one and the number that matters is the third.

### How it works

```
  statement.csv / .ofx
        │
        ├── parse            headers by content, locale-explicit money,
        │                    date order settled by the file itself
        │
        ├── VALIDATE ────────┬─ balance walk       every balance follows
        │                    ├─ declared total     matches the rows
        │                    └─ date continuity    no silent gap
        │                         │
        │                         └── fails ──► "this export is incomplete",
        │                                        and nothing else is reported
        │
        ├── FINDINGS         duplicates, refunded pairs suppressed,
        │                    subscriptions recognised not flagged,
        │                    price changes, new recurring charges
        │
        ├── DOCUMENTS  (optional, and the whole path may be absent)
        │        │
        │        ├── a folder of files, or a Paperless-ngx URL (read-only)
        │        ├── text / PDF ──► parse ──► crossfoot its arithmetic
        │        └── photograph ──► read ──► usually refused, and that is fine
        │
        ├── MATCH            amount, then date window, then merchant name
        │                    against the bank descriptor
        │
        ├── VERDICT          documented │ contradicted │ unchecked
        │
        ├── QUEUE            a person decides; nothing decides for them
        │
        └── LEDGER           append-only, hash-chained, one file
                             └── EXPORT   CSV / QIF / JSON
```

The arithmetic checks survive unchanged and run on whatever documents do parse.
They stop being the product and become one of the ways a document can be
*contradicted*.

### Infrastructure

Deliberately the same as today, because the current shape is not what failed.

- **Core: Python standard library only.** No required dependency. A statement
  audit runs on a machine with nothing installed.
- **`crossfoot[ui]`: Streamlit.** One optional page. The launcher opens it.
- **`crossfoot[ocr]`: Tesseract + Pillow.** Now genuinely optional, and
  labelled as the experimental path it is.
- **No network, no server, no account, no bank connection.** This is the
  product's main claim and it is enforced by there being no HTTP client in the
  core at all.
- **Paperless-ngx: read-only, optional, explicitly configured.** It is the one
  integration with direct evidence behind it, and it is the *link* those users
  asked for, not an import.
- **Distribution: PyPI, plus an Actual Budget plugin when plugins ship.**

### Workflow pipeline (what runs, in order, with the gate at each step)

| step | input | gate | on failure |
|---|---|---|---|
| 1 intake | a folder | exactly one statement | name the problem, stop |
| 2 parse | statement | every row readable | refuse the file, name the row |
| 3 validate | rows | balances walk, total declared | report incomplete, **suppress findings** |
| 4 findings | rows | — | — |
| 5 documents | a folder | each file readable | mark unreadable, continue |
| 6 match | rows + docs | one document per charge | ambiguous → unchecked |
| 7 verdict | matches | ≥1 check ran | no check → unchecked |
| 8 queue | verdicts | a person | nothing is auto-resolved |
| 9 ledger | decisions | hash chain intact | refuse to append, say so |

Step 3 suppressing step 4 is the design decision with teeth: a duplicate found
in a statement that is missing a fortnight is not a finding, it is an artefact.

### What is expected, and what would falsify it

Stated as numbers before they are measured, because a threshold picked
afterwards is a number chosen to be met.

| claim | how it is measured | fails if |
|---|---|---|
| a real bank export parses | 20 exports, ≥6 institutions, ≥3 countries | any silently mis-parses one row |
| the balance walk catches truncation | truncated exports, synthetic and real | it passes a statement missing rows |
| duplicate detection is worth reading | a hand-labelled set of ≥200 charges | precision < 0.8 — a noisy list is deleted, not tuned |
| subscriptions are not reported as duplicates | same set | any monthly subscription appears |
| matching is honest | hand-labelled charge/document pairs | any charge marked documented against the wrong document |
| **unchecked is never folded in** | every path | one charge counted clean without a check that ran |

The last row is the one that is asserted in CI. It already is.

### Plan

**Stage 0 — say the true thing now (done).** The README states that the
photograph path is not ready. `docs/real-receipts.md` carries the 55-receipt
result including the parts that are bad.

**Stage 1 — the statement audit, alone.** No documents, no OCR, no matching.
`crossfoot audit statement.csv` produces the completeness check and the
findings list. This is the piece with the best-evidenced demand and it has no
dependency on anything that failed.

Most of it is already written, which is the reason to start here rather than an
argument that it is easy:

| piece | state |
|---|---|
| statement parsing, CSV + OFX | built, tested |
| balance walk, declared total | built, tested |
| duplicate charges, refunded pairs suppressed | built (`ingest/duplicates.py`), tested |
| subscriptions recognised, not flagged | built, tested |
| money at risk | built (`at_risk`) |
| **`crossfoot audit`, statement with no receipts** | **not built** — today the CLI is `check`, which expects both |
| **price rose / new recurring charge** | **not built** |
| **findings suppressed when the statement is incomplete** | **not built** — the gate with teeth |
*Gate: 20 real exports parse without a silent mis-parse; duplicate precision
≥ 0.8 on a labelled set. If precision cannot reach 0.8, the finding list is
cut rather than tuned.*

**Stage 2 — the demand test, on Stage 1.** The gate that has always been the
real one, now run against something that works. Actual Budget Discord,
Firefly III discussions, r/selfhosted.
*Gate: 25 people run it on their own statement and 5 say a finding changed
something. Not reached in 8 weeks → this is a tool for its author, and the
README says so.*

**Stage 3 — documents as evidence.** Folder matching and the three-state
verdict, with receipt arithmetic where a document parses. Paperless-ngx
linking if Stage 2 surfaced anyone who wants it.
*Gate: no charge ever marked documented against the wrong document.*

**Stage 4 — measure the PDF path properly, then decide about it.** Install
docling, build a real corpus of PDF invoices, measure it the way the
photographs were measured. Only then does Option A become choosable.
*Gate: if PDFs read no better than photographs, drop document reading entirely
and keep matching by filename, amount and date.*

**Not planned:** camera improvements, a vision model, email intake, a server,
a bank connection, multi-receipt segmentation.

---

## The gate that still has not been run

Everything above is desk research and one measurement. **Not one person other
than the author has run this on their own statement.** The demand test in
[demand-test.md](demand-test.md) has never been executed, and no amount of
further analysis substitutes for it.

Desk research can rank three options. It cannot tell you whether anybody wants
the winner. That is Stage 2, and until Stage 2 reports, the honest description
of this project is: *a well-tested tool that solves a problem its author has,
with reasonable but unconfirmed evidence that others have it too.*
