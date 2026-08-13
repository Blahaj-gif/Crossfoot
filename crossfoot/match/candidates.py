"""
Step 3 — Match. Finding which receipt belongs to which charge, and refusing to
decide when more than one could.

The rule that shapes everything here: **fuzzy on the name, exact on the cents.**
A merchant string is a marketing decision rendered through a payment network and
truncated to a fixed width; it is evidence, not identity. The amount is the same
number filed by two parties about one event, and if it differs by a penny they
are not the same event.

The second rule: a tie stays a tie. Two coffees at the same café for the same
amount on the same day is a completely ordinary Saturday, and picking whichever
sorted first would produce a ledger that looks reconciled and is wrong in a way
nobody can ever detect. Ambiguity is returned intact and costs a human two
seconds.

`difflib` rather than rapidfuzz, deliberately: it is stdlib, the volumes here
are a few thousand comparisons, and a dependency bought for speed nobody needs
is a dependency that has to be maintained forever.
"""
import datetime
import difflib
import re

from crossfoot.verdict import cents

#: How far a receipt's date may sit from the posting date, in days. Card
#: transactions post one to three business days after the swipe, and a weekend
#: pushes that further; five covers it. Widening this does not find more
#: matches, it finds more ties.
DEFAULT_WINDOW_DAYS = 5

#: Below this, a name similarity is not evidence of anything.
NAME_FLOOR = 0.45

#: How close a character-level ratio must be before it counts as evidence at
#: all. Set high because merchant names are short and share an alphabet:
#: "sunset bar" against "sunrise cafe" scores 0.64 on raw character overlap,
#: which was enough to attach one merchant's receipt to another's charge. Above
#: this the ratio means a typo or a truncation; below it, it means both strings
#: are made of letters.
RATIO_FLOOR = 0.8

#: Payment-network furniture. Present on almost every descriptor and shared by
#: unrelated merchants, so leaving it in makes everything look alike.
_NOISE = re.compile(
    r"\b(pos|purchase|debit|credit|card|visa|mastercard|amex|payment|pmt|"
    r"transaction|txn|ref|auth|recurring|online|www|com|inc|llc|ltd|co|"
    r"store|shop|no|nr|id|xx+|\d{4,})\b", re.I)


def normalise_merchant(text: str) -> str:
    """
    A descriptor reduced to the part that identifies a merchant.

    "SQ *BLUE BOTTLE 0042 SAN FRANCISCO CA" and "Blue Bottle Coffee" have to
    reach each other, and "POS PURCHASE CARD 4471" and "POS PURCHASE CARD 9930"
    must not -- which is the same operation done well or badly.
    """
    lowered = (text or "").lower()
    lowered = re.sub(r"\bsq \*|\btst\*|\bsp \*|\bpp\*|\bpaypal \*", " ", lowered)
    lowered = re.sub(r"[^a-z0-9 ]", " ", lowered)
    lowered = _NOISE.sub(" ", lowered)
    return " ".join(lowered.split())


def name_similarity(a: str, b: str) -> float:
    """
    0..1 between two normalised descriptors.

    Token containment carries this; the character ratio is only a backstop for
    a typo or a truncation. A truncated descriptor is a *prefix* of the real
    name far more often than it is a near-miss of it, and a pure edit ratio
    scores "blue bottle" against "blue bottle coffee roasters" far lower than
    the pair deserves.

    The ratio is floored at `RATIO_FLOOR` rather than used raw, which is a
    correction: "sunset bar" and "sunrise cafe" share no token and no meaning
    and still scored 0.64 on character overlap alone -- enough to attach one
    merchant's receipt to another merchant's charge. Two short strings made of
    the same alphabet are not two names for the same shop.
    """
    left, right = normalise_merchant(a), normalise_merchant(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_tokens, right_tokens = set(left.split()), set(right.split())
    shared = left_tokens & right_tokens
    if shared:
        containment = len(shared) / min(len(left_tokens), len(right_tokens))
    else:
        containment = 0.0
    ratio = difflib.SequenceMatcher(None, left, right).ratio()
    return max(containment, ratio if ratio >= RATIO_FLOOR else 0.0)


def _as_date(value):
    if isinstance(value, datetime.date):
        return value
    text = str(value or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y",
                "%d.%m.%Y", "%Y%m%d"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def candidates(receipts, charge, window_days: int = DEFAULT_WINDOW_DAYS) -> list:
    """
    Every receipt that could be this charge, best first. Never fewer than all
    of them, and never silently one.

    Amount is a gate, not a score: a receipt whose total is not the charged
    amount to the cent is not a worse candidate, it is not a candidate. What is
    scored is only what is left -- how close the date is and how much the names
    look alike.
    """
    charged = cents(charge.get("amount"))
    if charged is None:
        return []
    # Money *in* gets no receipt, ever. A receipt reconciles a payment, and a
    # credit is not one -- so pairing a $50 refund with the $50 purchase
    # receipt it reverses would reconcile the two documents that most need to
    # stay apart. Salary, transfers and refunds reach the queue unchecked,
    # which is what they are.
    if charged > 0:
        return []
    charge_date = _as_date(charge.get("date"))
    wanted = abs(charged)

    out = []
    for receipt in receipts or []:
        total = cents(receipt.get("total"))
        if total is None or abs(total) != wanted:
            continue

        days = None
        if charge_date is not None:
            receipt_date = _as_date(receipt.get("date"))
            if receipt_date is not None:
                days = abs((charge_date - receipt_date).days)
                if days > window_days:
                    continue

        left = normalise_merchant(charge.get("description", ""))
        right = normalise_merchant(receipt.get("merchant", ""))
        similarity = name_similarity(charge.get("description", ""),
                                     receipt.get("merchant", ""))
        out.append({
            "receipt": receipt,
            "name_similarity": round(similarity, 3),
            # Whether the name test means anything here. Two names that both
            # survive normalisation can be compared; a blank descriptor or a
            # receipt with no merchant cannot, and a similarity of zero there
            # is an absence of evidence rather than evidence of a mismatch.
            "comparable_names": bool(left and right),
            "days_apart": days,
            # Date proximity breaks ties between equally-named candidates; it
            # never promotes a candidate the amount gate already let through.
            "score": round(similarity - 0.01 * (days or 0), 4),
        })

    out.sort(key=lambda c: (-c["score"], c["days_apart"] if c["days_apart"] is not None else 99))
    return out


def resolve(found: list) -> dict:
    """
    One match, or an honest refusal.

    Returns `{"receipt": ..., "why": ...}` only when a single candidate is
    clearly ahead. Two candidates that are equally plausible come back as
    `{"receipt": None, "ambiguous": [...]}` and go to a human, because the
    alternative -- picking one -- produces a ledger that reads as reconciled
    and is wrong in a way no later check can find.
    """
    if not found:
        return {"receipt": None, "ambiguous": [], "why": "no receipt matches this amount"}

    best = found[0]
    if best["name_similarity"] < NAME_FLOOR and best["comparable_names"]:
        # A lone candidate used to be accepted here however badly it was named,
        # on the reasoning that amount plus date is decent evidence. It is not,
        # when both documents *do* name a merchant and the names have nothing
        # in common: a receipt from Sunrise Cafe was being attached to a charge
        # from Sunset Bar simply because nothing else cost fifty dollars that
        # week. Where a name cannot be compared -- an unnamed receipt, a blank
        # descriptor -- the test is skipped rather than failed.
        return {"receipt": None, "ambiguous": found,
                "why": (f"{len(found)} receipt(s) match the amount and none matches "
                        "the merchant name well enough to choose between them")}

    rivals = [c for c in found[1:] if c["score"] >= best["score"] - 1e-9]
    if rivals:
        return {"receipt": None, "ambiguous": [best] + rivals,
                "why": (f"{len(rivals) + 1} receipts fit this charge equally well "
                        "— same amount, same window, indistinguishable names")}

    return {"receipt": best["receipt"], "ambiguous": [],
            "why": (f"one receipt matches to the cent, name similarity "
                    f"{best['name_similarity']:.2f}"
                    + (f", {best['days_apart']} days apart" if best["days_apart"] is not None else ""))}


def match_all(receipts, charges, window_days: int = DEFAULT_WINDOW_DAYS) -> list:
    """
    Every charge paired with its receipt, its ambiguity, or nothing.

    A receipt already resolved to a charge is withdrawn: one payment, one
    receipt. Without that, a monthly subscription's single receipt matches all
    twelve charges and eleven of them reconcile against a document that is not
    about them.

    Assignment is by **confidence, not by statement order**. Walking the
    statement top to bottom let whichever charge happened to be listed first
    take a receipt it barely matched, and left the charge that matched it
    perfectly with nothing: a $50 Sunset Bar line consumed the Sunrise Cafe
    receipt because it appeared two rows higher. So every candidate set is
    computed first, the most confident pairing in the whole month is taken, and
    the sets are recomputed without that receipt -- repeatedly, until no
    confident pairing is left. Order of rows in the file then changes nothing.
    """
    charges = list(charges or [])
    remaining = list(receipts or [])
    assigned = {}

    while True:
        best = None
        for index, charge in enumerate(charges):
            if index in assigned:
                continue
            outcome = resolve(candidates(remaining, charge, window_days))
            if outcome["receipt"] is None:
                continue
            score = max((c["score"] for c in candidates(remaining, charge, window_days)
                         if c["receipt"] is outcome["receipt"]), default=0.0)
            if best is None or score > best[0]:
                best = (score, index, outcome["receipt"])
        if best is None:
            break
        _, index, receipt = best
        assigned[index] = receipt
        remaining = [r for r in remaining if r is not receipt]

    # One final pass, so that what each unmatched charge is *told* reflects the
    # receipts actually left rather than the ones it was competing for.
    results = []
    for index, charge in enumerate(charges):
        if index in assigned:
            receipt = assigned[index]
            found = candidates([receipt], charge, window_days)
            results.append({"charge": charge, "receipt": receipt, "ambiguous": [],
                            "why": resolve(found)["why"], "candidates": found})
        else:
            found = candidates(remaining, charge, window_days)
            results.append({"charge": charge, **resolve(found), "candidates": found})
    return results
