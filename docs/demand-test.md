# The Stage 3 demand test

Everything before this was engineering, which I control. This is the part that
decides whether any of it mattered, and it cannot be done by writing more code.

**The gate:** 25 people running it against their own statements, and at least 5
saying the *verdict* — not the storage, not the categorisation — changed
something they did. Below that, Crossfoot is a good idea nobody needs, and the
right ending is to publish it as a finished small tool and stop.

Written down in advance, deliberately. A threshold chosen after the numbers
arrive is not a threshold.

---

## What has to happen first

1. **The repository is private.** Nothing below can run until it is public.
2. **Nothing here has met a real receipt.** Every fixture is text typed in the
   format this parser expected. The posts below say so, because a tool about
   verification that oversells its own verification deserves what it gets.

---

## Where these people actually are

Not Reddit. The strongest evidence in the whole project came from
[Actual Budget #530](https://github.com/actualbudget/actual/issues/530) — 195
reactions asking to attach receipts to transactions — so the audience is that
repository's community, and it needs no karma to speak there.

| Channel | Why | Notes |
|---|---|---|
| **Actual Budget Discord** | Where #530's 195 reactors live. Discussions are off on that repo | The primary channel |
| **Firefly III Discussions** | Enabled, active, and the data-importer crowd is exactly this | `firefly-iii/firefly-iii` → Discussions |
| **plaintextaccounting** (Beancount/ledger community) | The `!` flag integration is native to how they already work | Lowest volume, highest signal |
| **Lemmy /c/selfhosted** | The self-hosting audience without Reddit's karma wall | Secondary |

Announcing in the incumbents' own homes is only acceptable because Crossfoot
**feeds** them and competes with neither. Lead with that or it reads as
spam — because it would be.

---

## Draft — Actual Budget Discord

> Hi — I built a thing that fills a gap next to Actual rather than in it, and
> I'd like to know whether it's worth continuing.
>
> Attaching receipts to transactions was this repo's most-requested feature
> (#530, 195 reactions) and it shipped in 2023. What still isn't there is
> anything that *checks* the receipt: that its line items add up to its own
> subtotal, that subtotal plus tax plus tip equals its printed total, and that
> the total is what actually left your account. Four comparisons between
> numbers the documents already state twice.
>
> **Crossfoot** does those and exports a CSV Actual imports directly, with the
> verdict as a `#hashtag` in the note so you can filter on it. Three states:
> reconciled, does-not-reconcile, and **unchecked** — that third one is the
> point, because every tool I looked at collapses "verified correct" and "we
> couldn't tell" into one silent success, and it never counts unchecked as
> clean.
>
> Runs entirely locally. It has no code capable of making a network request and
> CI asserts that, because these are the most sensitive documents most people
> own.
>
> **Two honest caveats.** It has never met a real receipt — every test fixture
> is text I typed, so I make no accuracy claim. And I don't know whether anyone
> wants this: nobody has ever filed an issue asking for receipt *arithmetic*
> anywhere, so it may well be a good idea nobody needs.
>
> That's actually what I'm asking. If you run it against a month of your own
> statements, does the verdict change anything you'd do? If the answer is
> mostly "no", I'd rather hear it now than build another month on top.
>
> `pip install git+https://github.com/Blahaj-gif/Crossfoot` — it is not on PyPI
> and will not be until somebody other than me has run it.

---

## Draft — Firefly III Discussions

Same substance, different opening, because this audience arrives through the
data importer.

> **Crossfoot: reconcile receipts against a statement, import the verdict into
> Firefly as a tag**
>
> Firefly's importer takes tags as a real column, so this fits without any
> plumbing: Crossfoot reads your receipts and your statement export, checks
> them against each other, and writes a CSV plus the importer's JSON column
> mapping so it's not twenty dropdowns on the first run.
>
> The checks are arithmetic between numbers the documents state twice — line
> items against the printed subtotal, subtotal plus tax and tip against the
> printed total, that total against the amount charged, and the statement's own
> rows against its declared period total. That last one catches a truncated
> export, which is the failure that quietly makes every other verdict on the
> page meaningless.
>
> Every transaction arrives tagged `crossfoot:reconciled`,
> `crossfoot:does-not-reconcile` or `crossfoot:unchecked`. The unchecked ones
> are never silently counted as fine.
>
> No network access anywhere in it — it writes a file, your importer reads it.
>
> Caveat worth stating up front: it has never been run against real receipts,
> only fixtures I wrote, so treat accuracy as unmeasured. I'm looking for
> people willing to point it at one real month and tell me whether the verdict
> is worth anything to them.

---

## What counts as a result

| Signal | Counts as |
|---|---|
| "I ran it and it found a charge I'd been billed twice for" | Strong — even though duplicate detection isn't built yet, that's the ask |
| "It flagged a receipt whose maths was wrong and I got a refund" | Strong |
| "Nice, I'll try it later" | **Zero.** The gate is people who ran it |
| "This should just be part of Actual" | Useful and negative — it says the verdict is a feature, not a product |
| Stars with no usage | Zero |

**The failure mode to guard against** is counting enthusiasm as usage. Five
people saying it's a great idea is the same evidence the five abandoned repos
had, and they all had it before they stopped.

---

## If the gate fails

Not a pivot. One more day making Crossfoot a clean, honest, small tool that
does one unusual thing well, published with the accuracy claims it can actually
support, and then go and find a problem where somebody is already trying to pay
for the answer.

Writing that down now, while it is cheap to accept.
