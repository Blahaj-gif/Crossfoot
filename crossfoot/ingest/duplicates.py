"""
Being billed twice, which is the finding a person most wants and the one that
needs no receipt at all.

Everything else in Crossfoot compares a receipt against a statement. This
compares the statement against **itself**, so it works on the first run, before
anyone has photographed anything — and it is the only check here that can hand
somebody money back rather than merely telling them their paperwork is tidy.

The rule that shapes it, the same one as everywhere else: **nothing here
asserts a duplicate.** Two identical charges are a fact; whether they are one
purchase billed twice or two coffees on a Saturday is not in the statement and
cannot be derived from it. So this reports pairs and says exactly what makes
them suspicious, and a person decides. A tool that confidently accused a
merchant would be wrong often enough to be turned off, and being turned off is
the only way this check fails completely.

What raises suspicion, in order of weight:

  * **The same day.** Two identical amounts at one merchant hours apart is the
    classic double-tap: a card terminal that timed out and was run again.
  * **A large amount.** Two £4.20 coffees is a Saturday. Two £842 hardware
    charges is not, and the difference is not a threshold anyone can set for
    everybody -- so magnitude is reported, never used to suppress.

What *lowers* it, and is subtracted rather than left for a person to notice:

  * **A regular interval.** A charge repeating close to monthly is a
    subscription, and flagging twelve of them every year is how somebody learns
    to skim past this section.
  * **A refund of the same amount afterwards.** It was already put right. Still
    worth showing, because it says the merchant does this -- but as a note, not
    an alarm.
"""
import datetime

from crossfoot.match.candidates import name_similarity, normalise_merchant
from crossfoot.verdict import cents

#: How far apart two identical charges can be and still be worth pairing. Three
#: days covers a terminal retried the next morning and a card that posted late,
#: without reaching across a fortnight and pairing two genuine visits.
DEFAULT_WINDOW_DAYS = 3

#: A repeat this close to a month apart is a subscription, not a double-bill.
#: The tolerance is generous because billing dates drift across month lengths
#: and weekends, and a false *suppression* here is cheaper than an alarm that
#: fires twelve times a year until somebody stops reading it.
MONTHLY_MIN = 26
MONTHLY_MAX = 35


def _date(value):
    text = str(value or "").strip()[:10]
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


#: How alike two descriptors must be to count as one merchant. Higher than the
#: matcher's floor on purpose: pairing a receipt to a charge merely misfiles
#: something a person can see, and pairing two charges here *accuses a merchant*
#: of billing twice. The cost of the two mistakes is not the same.
SAME_MERCHANT = 0.8


def _billed(line):
    """(merchant, amount) for a row that is money out with a nameable merchant."""
    amount = cents(line.get("amount"))
    if amount is None or amount >= 0:
        return None                 # money in is not something you were billed
    merchant = normalise_merchant(line.get("description", ""))
    if not merchant:
        # Every word was payment-network furniture. "POS PURCHASE CARD 4471"
        # and "POS PURCHASE CARD 9930" are unrelated charges that survive
        # normalisation as the same nothing, and pairing on amount alone would
        # accuse a merchant this cannot even name.
        return None
    return merchant, abs(int(amount))


def _cluster(rows):
    """
    Rows of one amount split into merchants, allowing for a bank that writes
    the same shop two ways.

    "SQ *BLUE BOTTLE 0042" and "SQ *BLUE BOTTLE COFFEE" normalise to different
    strings and are the same till. Exact grouping missed precisely the pairs
    worth catching -- but the amount already had to match to the cent before
    reaching here, so accepting a close name costs very little and catching a
    real double-bill is the whole point.
    """
    clusters = []
    for merchant, row in rows:
        for cluster in clusters:
            if name_similarity(merchant, cluster["merchant"]) >= SAME_MERCHANT:
                cluster["rows"].append(row)
                break
        else:
            clusters.append({"merchant": merchant, "rows": [row]})
    return clusters


def _looks_like_a_subscription(dates) -> bool:
    """
    Every gap in the run sits near a month.

    Checked across the whole run rather than pairwise: three charges 30 days
    apart are obviously a subscription, and the pair-at-a-time view would have
    to rediscover that for each pair.
    """
    if len(dates) < 2:
        return False
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    return all(MONTHLY_MIN <= gap <= MONTHLY_MAX for gap in gaps)


def _refund_after(lines, merchant, amount, after):
    """A credit of the same size from the same merchant, later. Already put right."""
    for line in lines:
        value = cents(line.get("amount"))
        if value is None or value <= 0 or abs(int(value)) != amount:
            continue
        if normalise_merchant(line.get("description", "")) != merchant:
            continue
        when = _date(line.get("date"))
        if when is None or after is None or when >= after:
            return line
    return None


def suspects(lines, window_days: int = DEFAULT_WINDOW_DAYS) -> list:
    """
    Pairs of identical charges close together, with what makes each suspicious.

    Undated rows are grouped but never paired: without a date there is no
    "close together", and pairing on amount alone would flag every second visit
    to a lunch place. They are reported as an unpairable group instead, because
    the alternative is silence about rows that genuinely might be duplicates.
    """
    # By amount first, because the amount is exact and therefore a perfect
    # bucket; the merchant is fuzzy and only has to be decided within a bucket.
    by_amount = {}
    for line in lines or []:
        billed = _billed(line)
        if billed is not None:
            merchant, amount = billed
            by_amount.setdefault(amount, []).append((merchant, line))

    found = []
    for amount, entries in by_amount.items():
        if len(entries) < 2:
            continue

        for cluster in _cluster(entries):
            rows, merchant = cluster["rows"], cluster["merchant"]
            if len(rows) < 2:
                continue

            dated = sorted(((_date(r.get("date")), r) for r in rows
                            if _date(r.get("date"))), key=lambda pair: pair[0])
            undated = [r for r in rows if _date(r.get("date")) is None]

            if _looks_like_a_subscription([d for d, _ in dated]):
                continue            # a subscription, not a double-bill

            for (first_date, first), (second_date, second) in zip(dated, dated[1:]):
                gap = (second_date - first_date).days
                if gap > window_days:
                    continue
                refund = _refund_after(lines, merchant, amount, second_date)
                found.append({
                    "merchant": first.get("description", ""),
                    "amount": amount,
                    "days_apart": gap,
                    "charges": [first, second],
                    "refunded_by": refund,
                    "why": _why(first, second, gap, amount, refund),
                })

            if undated and len(rows) > 1:
                found.append({
                    "merchant": rows[0].get("description", ""),
                    "amount": amount,
                    "days_apart": None,
                    "charges": rows,
                    "refunded_by": None,
                    "why": (f"{len(rows)} charges of the same amount at this "
                            "merchant, and the statement gives no dates to tell "
                            "how far apart they were"),
                })

    # Largest first. Two £4.20 coffees and two £842 hardware charges are the
    # same shape and not remotely the same problem.
    found.sort(key=lambda s: -s["amount"])
    return found


def _why(first, second, gap, amount, refund) -> str:
    when = "the same day" if gap == 0 else f"{gap} day{'s' if gap != 1 else ''} apart"
    money = f"{amount // 100}.{amount % 100:02d}"
    text = (f"two charges of {money} at this merchant, {when} "
            f"({first.get('date', '?')} and {second.get('date', '?')})")
    if refund is not None:
        text += (f" — and a refund of the same amount on {refund.get('date', '?')}, "
                 "so this one was already put right")
    return text


def at_risk(found) -> int:
    """
    Cents you may have paid twice — the *second* charge of each pair, not both.

    Counting both would double what is actually at stake, which is the kind of
    exaggeration that makes a person stop believing the rest of the numbers.
    Pairs already reversed by a refund are excluded: that money came back.
    """
    return sum(s["amount"] for s in found
               if s["refunded_by"] is None and s["days_apart"] is not None)
