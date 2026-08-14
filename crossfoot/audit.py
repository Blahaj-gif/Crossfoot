"""
The statement, checked against itself, with no receipt anywhere in it.

This is the piece that survived the measurement. Reading a photographed receipt
works on roughly one real receipt in fifty-five; reading a bank export is a CSV
parser and works. Everything here runs on the export alone, so it produces
something on the first run, before anybody has photographed anything, and it
cannot be broken by an OCR engine because no OCR engine is involved.

**Findings are facts or they are not reported.** That rule threw out the first
draft of this file. It had a "still charging" finding -- a subscription running
for a year, offered as something to look at -- and the tool cannot know whether
you use the thing. Every commercial statement-audit product ships that finding
and it is the one part of them that is guesswork wearing a fact's clothes. What
is left is three things the statement genuinely states:

    paid twice      two identical charges, one merchant, days apart, no refund
    price rose      a recurring charge's amount went up
    new recurring   a merchant that was not billing you monthly now is

and, separately and deliberately not called a finding, an **inventory** of
every recurring charge with what it costs a year. That is the list people
actually want, it is entirely factual, and presenting it as an accusation is
what would make somebody stop reading it.

**Findings are suppressed when the export is incomplete.** A duplicate found in
a statement missing a fortnight is not a finding, it is an artefact of the gap
-- and worse, the rows that were never read cannot be reported as missing, so a
half-read statement produces a short, clean, entirely misleading page. The gate
is the same shape as the verdict layer's: a check that could not run is never
counted as a check that passed.
"""
import datetime

from crossfoot.ingest import statement as S
from crossfoot.ingest.duplicates import (MONTHLY_MAX, MONTHLY_MIN, _billed,
                                         _date, at_risk, suspects)
from crossfoot.match.candidates import name_similarity
from crossfoot.verdict import Cents

#: The three states an export can be in. Deliberately three, and deliberately
#: the same shape as the verdict layer: whole, not whole, and *cannot tell*.
#: Most real exports carry neither a running balance nor a declared total, so
#: `UNVERIFIABLE` is the common case rather than an edge one -- and collapsing
#: it into "whole" would be the exact mistake this project exists to avoid.
WHOLE = "whole"
INCOMPLETE = "incomplete"
UNVERIFIABLE = "unverifiable"

#: How alike two descriptors must be to count as the same merchant across
#: months. Lower than the duplicate checker's floor, because that one accuses a
#: merchant of double-billing and this one only groups a subscription whose
#: descriptor drifts -- "SPOTIFY P0A1B2" one month and "SPOTIFY P9Z8Y7" the
#: next is one subscription, and the digits change every time.
SAME_MERCHANT = 0.72

#: A run has to be this long before it is called recurring. Two charges a month
#: apart is a coincidence a great many people have with their supermarket.
RECURRING_MINIMUM = 3

#: A recurring charge whose amount moves by less than this is not a price rise.
#: Utility bills vary by a few pence every month and reporting that would bury
#: the streaming service that went up by three pounds.
PRICE_NOISE = Cents(50)


def _stable_name(merchant: str) -> str:
    """
    The part of a descriptor that is the same every month.

    Banks put a per-transaction reference in the descriptor, and a great many
    of the subscriptions this is meant to track do it: `SPOTIFY P0A1B2` one
    month and `SPOTIFY P4Z9Q1` the next, `PAYPAL *NETFLIX 1042`, `AMZNMktplace
    M17K2`. Compared whole, those are two merchants — so a single subscription
    was reported as a **newly started** one every time its reference changed,
    and its price rise vanished because the before and after were in different
    groups.

    That is worse than merely missing something. "You started paying for this"
    is an accusation about a thing that did not happen, and the duplicate
    checker's own note applies: a tool that is confidently wrong gets turned
    off, and being turned off is the only way a check fails completely.

    So trailing tokens containing a digit are dropped. A merchant's *name* is
    words; a reference is not. Trailing only, because `7 ELEVEN` and `O2` begin
    with one and are not references.
    """
    tokens = merchant.split()
    while len(tokens) > 1 and any(c.isdigit() for c in tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


def _runs(lines):
    """
    Every merchant's charges, grouped across the whole statement.

    Grouped by name rather than by amount, which is the opposite of the
    duplicate checker: there the amount is the exact thing and the name is
    fuzzy, here the amount is what changes and the name is what persists.
    """
    groups = []
    for line in lines or []:
        billed = _billed(line)
        if billed is None:
            continue
        merchant, amount = billed
        merchant = _stable_name(merchant)
        when = _date(line.get("date"))
        if when is None:
            continue                     # a run needs an order to be a run
        for group in groups:
            if name_similarity(merchant, group["merchant"]) >= SAME_MERCHANT:
                group["charges"].append((when, amount, line))
                break
        else:
            groups.append({"merchant": merchant,
                           "charges": [(when, amount, line)]})
    for group in groups:
        group["charges"].sort(key=lambda c: c[0])
    return groups


def _is_recurring(charges) -> bool:
    """
    Enough charges, spaced near a month.

    The *median* gap rather than every gap, because a real subscription
    occasionally skips or double-posts across a year and demanding that every
    single interval sits in the window loses most of them. The duplicate
    checker uses the strict rule for the opposite reason: there, a wrongly
    recognised subscription *suppresses* a genuine double-bill, so it must be
    sure.
    """
    if len(charges) < RECURRING_MINIMUM:
        return False
    gaps = sorted((b[0] - a[0]).days for a, b in zip(charges, charges[1:]))
    median = gaps[len(gaps) // 2]
    return MONTHLY_MIN <= median <= MONTHLY_MAX


def recurring(lines) -> list:
    """
    Every recurring charge and what it costs a year, most expensive first.

    Not a finding and not an accusation. It is an inventory, which is the thing
    a person actually asked for when they said they wanted to know about their
    subscriptions, and the annual figure is arithmetic rather than an opinion
    about whether they should keep it.
    """
    out = []
    for group in _runs(lines):
        charges = group["charges"]
        if not _is_recurring(charges):
            continue
        latest = charges[-1][1]
        out.append({
            "merchant": group["merchant"],
            "charges": len(charges),
            "latest": Cents(latest),
            "a_year": Cents(latest * 12),
            "first_seen": charges[0][0].isoformat(),
            "last_seen": charges[-1][0].isoformat(),
            "rows": [line for _, _, line in charges],
        })
    out.sort(key=lambda r: -int(r["a_year"]))
    return out


def price_rises(lines) -> list:
    """
    A recurring charge whose amount went up, and by how much.

    Reported for rises only. A subscription that got cheaper is not something
    anybody needs to be told about at the top of a page, and including it would
    dilute the list that exists to be short.
    """
    out = []
    for group in _runs(lines):
        charges = group["charges"]
        if not _is_recurring(charges):
            continue
        first_amount = charges[0][1]
        latest_amount = charges[-1][1]
        rise = latest_amount - first_amount
        if rise <= int(PRICE_NOISE):
            continue
        changed = next((when for when, amount, _ in charges
                        if amount > first_amount + int(PRICE_NOISE)), None)
        out.append({
            "kind": "price_rose",
            "merchant": group["merchant"],
            "was": Cents(first_amount),
            "now": Cents(latest_amount),
            "at_risk": Cents(rise * 12),
            "when": changed.isoformat() if changed else None,
            "rows": [line for _, _, line in charges],
            "why": (f"{group['merchant']} went from {_money(first_amount)} to "
                    f"{_money(latest_amount)}"
                    + (f" on {changed.isoformat()}" if changed else "")
                    + f" — {_money(rise * 12)} a year"),
        })
    out.sort(key=lambda r: -int(r["at_risk"]))
    return out


def new_recurring(lines, settling_days: int = 45) -> list:
    """
    A merchant that was not billing you monthly at the start of this statement
    and is now.

    The settling period exists because every subscription looks new in the
    first weeks of any export -- the statement simply does not reach back far
    enough to show the earlier charges. Without it this would report a person's
    entire subscription list as newly started, every month, which is worse than
    reporting nothing.
    """
    dated = [d for d in (_date(l.get("date")) for l in lines or []) if d]
    if not dated:
        return []
    opens = min(dated)
    cutoff = opens + datetime.timedelta(days=settling_days)

    out = []
    for group in _runs(lines):
        charges = group["charges"]
        if not _is_recurring(charges) or charges[0][0] <= cutoff:
            continue
        latest = charges[-1][1]
        out.append({
            "kind": "new_recurring",
            "merchant": group["merchant"],
            "at_risk": Cents(latest * 12),
            "since": charges[0][0].isoformat(),
            "charges": len(charges),
            "rows": [line for _, _, line in charges],
            "why": (f"{group['merchant']} started charging "
                    f"{_money(latest)} monthly on {charges[0][0].isoformat()} "
                    f"— {_money(latest * 12)} a year"),
        })
    out.sort(key=lambda r: -int(r["at_risk"]))
    return out


def paid_twice(lines, window_days: int = None) -> list:
    """
    The existing duplicate check, in this file's finding shape.

    Nothing about the detection changed; it is the one finding here that was
    already built, already measured and already careful about subscriptions and
    refunds.
    """
    found = suspects(lines) if window_days is None else suspects(lines, window_days)
    out = []
    for pair in found:
        # `at_risk` counts the second charge of a pair, and counts nothing for
        # a pair already reversed by a refund or one with no dates to place it.
        # Reusing it per-pair rather than recomputing keeps one definition of
        # money at stake, which is the number a person will quote back.
        out.append({
            "kind": "paid_twice",
            "merchant": pair.get("merchant", ""),
            "at_risk": Cents(int(at_risk([pair]))),
            "rows": pair.get("charges") or [],
            "why": pair.get("why", ""),
            "detail": pair,
        })
    out.sort(key=lambda r: -int(r["at_risk"]))
    return out


def completeness(statement) -> dict:
    """
    Whether this export can be trusted to be all of itself.

    Delegates to `statement.accept`, which is the same function the pipeline
    gates on, and that is the point. The first version of this ran its own two
    checks — and picked the *weaker* of the two declared-total checks in the
    codebase, the one that does not accept an opening and closing balance in
    place of a period total. Since a balance walk stays perfectly consistent
    right up to where a truncated file stops, that pair is the only thing that
    sees a file cut off at the end. So `crossfoot audit` would have called an
    export whole where `crossfoot check` called it incomplete, and a person
    would have had two commands from one tool disagreeing about whether their
    own bank statement could be trusted.

    Three states out of `accept`'s two fields, because `usable` and
    `verified_complete` are not the same question: most real exports carry
    neither a running balance nor a declared total, so they are usable and
    unverified, and calling that `whole` would be claiming a check ran when
    none did.
    """
    accepted = S.accept(statement)
    checks = accepted["checks"]
    failed = [c for c in checks if c.ok is False]

    if not accepted["usable"]:
        state, why = INCOMPLETE, accepted["problems"][0]
    elif accepted["verified_complete"]:
        state = WHOLE
        why = f"{len([c for c in checks if c.ok])} completeness checks agree"
    else:
        state, why = UNVERIFIABLE, (
            "this export carries neither a running balance nor a declared "
            "total, so there is no way to tell from the file whether rows are "
            "missing")
    return {"state": state, "checks": checks, "failed": failed, "why": why}


def audit(statement, window_days: int = None) -> dict:
    """
    Everything the statement says about itself.

    Findings are withheld entirely when the export is incomplete. That is not
    caution for its own sake: a duplicate found in a statement missing a
    fortnight is an artefact of the gap, and the rows that were never read
    cannot be reported as missing — so a half-read statement otherwise produces
    a short, clean and entirely misleading page. Somebody reads that page and
    concludes their account is fine.
    """
    lines = statement.get("lines") or statement.get("transactions") or []
    whole = completeness(statement)

    if whole["state"] == INCOMPLETE:
        return {
            "completeness": whole,
            "findings": [],
            "recurring": [],
            "at_risk": Cents(0),
            "suppressed": True,
            "why": ("findings are withheld because this export is not "
                    "complete: " + whole["why"]),
            "rows": len(lines),
        }

    findings = paid_twice(lines, window_days) + price_rises(lines) \
        + new_recurring(lines)
    findings.sort(key=lambda f: -int(f["at_risk"]))
    return {
        "completeness": whole,
        "findings": findings,
        "recurring": recurring(lines),
        "at_risk": Cents(sum(int(f["at_risk"]) for f in findings)),
        "suppressed": False,
        "why": whole["why"],
        "rows": len(lines),
    }


def _money(c) -> str:
    c = int(c)
    sign = "-" if c < 0 else ""
    c = abs(c)
    return f"{sign}{c // 100}.{c % 100:02d}"
