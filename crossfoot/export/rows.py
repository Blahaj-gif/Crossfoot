"""
Step 6 — Export. The verdict travels with the transaction, or nothing does.

This is the step the whole project was pointed at and never built, and it is
the one with evidence behind it: Actual Budget's most-reacted feature request
was attaching receipts to transactions, and Firefly III and Actual have 52,000
stars between them and no receipt story of their own. Crossfoot does not
compete with a budgeting tool. It feeds one.

**Nothing here phones anything.** Every exporter writes a file the target's own
importer reads. That is not a limitation worked around, it is the property the
project is for: receipts and statements are the most sensitive documents most
people own, and a tool that promises they never leave the machine should have
no code capable of sending them. CI asserts the absence of the imports.

The refusal that shapes the whole module: **an unchecked row is never exported
as though it reconciled.** Every row carries its verdict as a tag the target
can filter on, so a ledger that says clean is clean and one that says nothing
was checked says so in the transaction itself, where it will still be visible
next April.
"""
from crossfoot import verdict as V
from crossfoot.review import queue as Q

#: The vocabulary that leaves this machine. Prefixed, because these land in
#: somebody's ledger beside tags they chose themselves and must be obviously
#: ours, greppable, and safe to bulk-delete if they stop wanting them.
RECONCILED = "crossfoot:reconciled"
DISCREPANT = "crossfoot:does-not-reconcile"
UNCHECKED = "crossfoot:unchecked"
ACCEPTED = "crossfoot:accepted-by-you"
AMBIGUOUS = "crossfoot:more-than-one-receipt"
DUPLICATE = "crossfoot:possible-duplicate"

#: A fourth state that only exists here. A person looked at a discrepancy and
#: accepted it -- the merchant's arithmetic really was wrong, or the tip was
#: added later -- and that is neither "reconciled" nor "unchecked". Exporting it
#: as either would lose the one fact that a human made a call.
_FROM_STATE = {
    Q.DUPLICATE: DUPLICATE,
    Q.FAILED: DISCREPANT,
    Q.AMBIGUOUS: AMBIGUOUS,
    Q.UNVERIFIED: UNCHECKED,
    Q.FILED: RECONCILED,
}


def _money(cents_value) -> str:
    """Cents as a signed decimal string. Never a float: this is going in a ledger."""
    if cents_value is None:
        return ""
    sign = "-" if cents_value < 0 else ""
    whole, fraction = divmod(abs(int(cents_value)), 100)
    return f"{sign}{whole}.{fraction:02d}"


def rows_for(items, decided=()) -> list:
    """
    Every charge as an export row, verdict included, in statement order.

    `items` is every queue item — filed and outstanding both. A reconciled
    charge leaves the review queue because nobody needs to look at it; it does
    not leave the *ledger*, because it is still a transaction that happened.
    Exporting only the interesting ones would hand somebody a ledger missing
    most of their spending.

    `decided` is the decision log. A human's accept is carried through as its
    own state rather than being flattened into either neighbour.
    """
    by_seen = {}
    for entry in decided or ():
        key = tuple(sorted((entry.get("seen") or {}).items()))
        by_seen[key] = entry

    rows = []
    for item in items:
        charge = item.get("charge") or {}
        receipt = item.get("receipt") or {}
        key = tuple(sorted((item.get("seen") or {}).items()))
        decision = by_seen.get(key)

        tag = _FROM_STATE.get(item["state"], UNCHECKED)
        note = item.get("why", "")
        if decision and decision.get("action") in ("accept_as_printed", "correct"):
            tag = ACCEPTED
            note = (f"you accepted this on {decision.get('at', '')[:10]}"
                    + (f": {decision['note']}" if decision.get("note") else "")
                    + f" — {note}")

        rows.append({
            "date": charge.get("date", ""),
            "description": charge.get("description", ""),
            "amount": _money(V.cents(charge.get("amount"))),
            "verdict": tag,
            "why": note,
            "receipt": receipt.get("source") or receipt.get("merchant") or "",
            # Every check that actually ran, so a person opening the transaction
            # in April can see what was compared rather than trusting a word.
            "checks": "; ".join(
                f"{c.name}={'ok' if c.ok else 'FAILED' if c.ok is False else 'unrun'}"
                for c in item.get("checks", [])),
        })
    return rows


def counts(rows) -> dict:
    """How many of each verdict left, for the line the exporter prints."""
    out = {}
    for row in rows:
        out[row["verdict"]] = out.get(row["verdict"], 0) + 1
    return out


def summary(rows) -> str:
    """
    One line, and it never rounds the unchecked away.

    "142 transactions exported" is the sentence every other tool prints, and it
    is true and useless: exported having been checked, or exported having been
    looked at and not understood?
    """
    tally = counts(rows)
    parts = [f"{tally[tag]} {tag.split(':', 1)[1]}"
             for tag in (DUPLICATE, RECONCILED, ACCEPTED, DISCREPANT, AMBIGUOUS,
                         UNCHECKED)
             if tally.get(tag)]
    return f"{len(rows)} transactions: " + ", ".join(parts)
