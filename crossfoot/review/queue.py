"""
Step 4 — Review. What reaches a person, and in what order.

Two decisions define this module.

**Only failures and unchecked items are in it.** A reconciled charge is filed
and never mentioned again. A queue that shows everything is a queue nobody
reads, and the 347 rows that agree with themselves are precisely the ones that
need no attention.

**Ordered by money at risk, not by date or arrival.** Sorting by count treats a
$3.20 rounding artefact and an $842 discrepancy as equals, which they are only
to a computer. Whoever is doing this has twenty minutes on a Sunday; the
ordering decides what those minutes buy.

This module **reads**. It contains no function that writes a decision, and it
imports nothing that does -- the write path is a separate module reached only
from the review UI, and CI asserts that it stays that way.

Structural, and worth being exact about how far that goes. An assistant handed
the whole of this file has no reachable path to clearing an item, which is the
property this buys. It is **not** a security boundary: any process on the
machine can import the write path directly and pass the string "human". What
stops that being invisible is the hash chain on the log, not this separation.
"""
from crossfoot import verdict as V

#: Queue states, in the order a person cares about them.
FAILED = "failed"
#: Two identical charges close together. Ranked above everything else because
#: it is the only finding here that can hand somebody money back, and because
#: it needs no receipt -- it is what a person sees on their very first run.
DUPLICATE = "possible duplicate"
AMBIGUOUS = "ambiguous"
UNVERIFIED = "unverified"
FILED = "filed"

_RANK = {DUPLICATE: 0, FAILED: 1, AMBIGUOUS: 2, UNVERIFIED: 3, FILED: 4}


def item_for(match) -> dict:
    """
    One matched charge as a queue item, verdict included.

    `match` is what `crossfoot.match.candidates.match_all` produces: a charge,
    a resolved receipt or None, and any ambiguity behind it.
    """
    charge = match.get("charge") or {}
    receipt = match.get("receipt")
    ambiguous = match.get("ambiguous") or []

    result = V.reconcile(receipt, charge)
    if result["verdict"] == V.DISCREPANT:
        state = FAILED
    elif ambiguous:
        state = AMBIGUOUS
    elif result["verdict"] == V.RECONCILED:
        state = FILED
    else:
        state = UNVERIFIED

    return {
        "state": state,
        "verdict": result["verdict"],
        "charge": charge,
        "receipt": receipt,
        "ambiguous": ambiguous,
        "checks": result["checks"],
        "at_risk": result["at_risk"] or 0,
        "why": _why(state, result, match),
        # Every number a person will be shown, captured now. A decision taken
        # against figures that have since changed is a decision about something
        # else, and `decisions.record` refuses one.
        "seen": {
            "charge_amount": V.cents(charge.get("amount")),
            "receipt_total": V.cents((receipt or {}).get("total")),
            "verdict": result["verdict"],
        },
    }


def _why(state, result, match):
    if state == AMBIGUOUS:
        return match.get("why") or "more than one receipt fits this charge"
    return result["why"]


def _charge_key(charge):
    """
    What identifies one statement row across the two views of it.

    The matcher works on derived charge dicts and the duplicate finder works on
    raw statement lines: different objects describing the same row. The row
    number is what both carry and the only thing that is unique -- keying on
    date, description and amount marked *both* halves of every duplicate pair,
    because two identical charges are identical.
    """
    row = charge.get("row")
    if row is not None:
        return ("row", row)
    return ("value", str(charge.get("date", "")), str(charge.get("description", "")),
            int(V.cents(charge.get("amount")) or 0))


def _mark_duplicates(items, duplicates):
    """
    Annotate the rows a double-bill involves. Never add rows.

    The first version appended a queue item per suspected duplicate, which
    meant the charge appeared twice in the export -- so importing the result
    would have created a duplicate transaction in somebody's ledger. From the
    duplicate detector. One row per statement line, always; being flagged is
    something that happens *to* a row.

    Only the second charge of a pair is marked. The first one is not suspicious
    on its own -- it is an ordinary purchase that happens to have been followed
    by an identical one -- and flagging both doubles the apparent problem.
    """
    by_key = {}
    for item in items:
        by_key.setdefault(_charge_key(item["charge"]), []).append(item)

    for suspect in duplicates or ():
        for item in by_key.get(_charge_key(suspect["charges"][-1]), []):
            item["duplicate_of"] = suspect["charges"][0]
            item["refunded_by"] = suspect["refunded_by"]
            # The receipt verdict survives underneath. A row can be both a
            # possible double-bill and a receipt that disagrees with itself,
            # and the person needs to be told both.
            item["why"] = (suspect["why"] + (f" — also: {item['why']}"
                                             if item["state"] != UNVERIFIED else ""))
            item["state"] = DUPLICATE
            item["seen"] = dict(item["seen"], duplicate_of=_charge_key(
                suspect["charges"][0]))
    return items


def build(matches, duplicates=()) -> dict:
    """
    The queue, and the counts that go above it.

    `needs_you` is ordered by money at risk. `filed` is a number, not a list:
    the reconciled rows are the ones nobody has to look at, and rendering them
    is how a queue stops being read.
    """
    items = _mark_duplicates([item_for(m) for m in matches or []], duplicates)
    needs_you = [i for i in items if i["state"] != FILED]
    needs_you.sort(key=lambda i: (_RANK[i["state"]], -abs(i["at_risk"])))

    filed = [i for i in items if i["state"] == FILED]
    unverified = [i for i in items if i["state"] == UNVERIFIED]

    return {
        "needs_you": needs_you,
        "duplicates": len([i for i in items if i["state"] == DUPLICATE]),
        # Both, and they are not redundant. `filed` is a count because the
        # review UI must not render 347 rows nobody has to look at -- a queue
        # that shows everything is a queue nobody reads. `filed_items` exists
        # because the *ledger* still needs them: a reconciled charge leaves the
        # queue, it does not stop having happened, and exporting only the
        # interesting ones hands somebody a ledger missing most of their money.
        "filed_items": filed,
        "filed": len(filed),
        "unverified": len(unverified),
        "at_risk": sum(abs(i["at_risk"]) for i in needs_you),
        "headline": _headline(needs_you, filed, unverified),
    }


def _headline(needs_you, filed, unverified):
    """
    The line at the top, which must never round the unchecked away.

    "347 reconciled" on its own is the sentence every other tool prints, and it
    is true and misleading in the same breath: it is 347 out of how many, and
    what happened to the rest?
    """
    if not needs_you:
        return (f"{len(filed)} reconciled, nothing outstanding"
                if not unverified else
                f"{len(filed)} reconciled, {len(unverified)} unchecked, "
                "which is not the same as clean")
    money = sum(abs(i["at_risk"]) for i in needs_you)
    doubled = [i for i in needs_you if i["state"] == DUPLICATE]
    # The duplicate count leads when there is one, because "you may have paid
    # this twice" is a different sentence from "your paperwork is incomplete"
    # and burying it behind a tally is how it gets skimmed past.
    lead = (f"{len(doubled)} possibly billed twice, " if doubled else "")
    return (lead + f"{len(needs_you)} need you, {money // 100}.{money % 100:02d} at risk, "
            f"{len(filed)} reconciled, {len(unverified)} unchecked")
