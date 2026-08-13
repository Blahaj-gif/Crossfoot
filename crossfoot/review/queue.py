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
imports nothing that does -- `crossfoot.review.decisions` is a separate module
reached only from the review UI. That separation is structural rather than
polite: an assistant given the whole of this file still cannot clear an item.
"""
from crossfoot import verdict as V

#: Queue states, in the order a person cares about them.
FAILED = "failed"
AMBIGUOUS = "ambiguous"
UNVERIFIED = "unverified"
FILED = "filed"

_RANK = {FAILED: 0, AMBIGUOUS: 1, UNVERIFIED: 2, FILED: 3}


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


def build(matches) -> dict:
    """
    The queue, and the counts that go above it.

    `needs_you` is ordered by money at risk. `filed` is a number, not a list:
    the reconciled rows are the ones nobody has to look at, and rendering them
    is how a queue stops being read.
    """
    items = [item_for(m) for m in matches or []]
    needs_you = [i for i in items if i["state"] != FILED]
    needs_you.sort(key=lambda i: (_RANK[i["state"]], -abs(i["at_risk"])))

    filed = [i for i in items if i["state"] == FILED]
    unverified = [i for i in items if i["state"] == UNVERIFIED]

    return {
        "needs_you": needs_you,
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
    return (f"{len(needs_you)} need you, {money // 100}.{money % 100:02d} at risk, "
            f"{len(filed)} reconciled, {len(unverified)} unchecked")
