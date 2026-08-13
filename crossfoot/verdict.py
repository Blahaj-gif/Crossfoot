"""
The four checks, and the three answers they can produce.

A receipt is not one number. It is a column of line items, a subtotal, a tax
line, sometimes a tip and a discount, and a total -- and the document states
enough of those that the arithmetic between them can be verified without
trusting any single reading of any single field. Then the statement states the
amount that actually left the account, which is a fifth number about the same
event, filed by a different party.

That redundancy is the whole product. It is also why this module contains no
model, no heuristic and no scoring: every check here is arithmetic between
numbers two documents already committed to.

Three answers, never two:

    RECONCILED      the numbers agree
    DISCREPANT      two numbers about the same fact disagree
    UNCHECKED       the documents did not state enough to check

The third is what every incumbent throws away. Collapsing "verified" and "could
not tell" into one silent success is how a parser that is right nine times in
ten feels like one that is right every time, until the year it matters.

On tolerance
------------
Money is counted in cents and compared exactly, with one deliberate exception:
a per-unit price times a quantity, or a VAT-inclusive line, rounds at each row,
so a receipt of *n* priced lines may legitimately be off by up to *n* cents
against its own subtotal. That allowance is bounded by the number of rows and
never by a percentage, because the failure this exists to catch -- a magnitude
misread, a decimal point in the wrong place, a currency read as another -- is
off by a factor, and a percentage tolerance is exactly the shape that hides it.
"""
from decimal import Decimal, InvalidOperation

RECONCILED = "reconciled"
DISCREPANT = "does_not_reconcile"
UNCHECKED = "unchecked"

#: Cents of slack per priced line item, for per-unit rounding. Not a fudge
#: factor: it scales with rows, so it can never grow to hide an error that
#: scales with magnitude.
ROUNDING_ALLOWANCE_PER_LINE = 1


class Check:
    """
    One comparison between two numbers the documents both state.

    `ok` is tri-state for the same reason the verdict is: a check that could not
    run is not a check that passed.
    """

    __slots__ = ("name", "ok", "expected", "actual", "detail")

    def __init__(self, name, ok, expected=None, actual=None, detail=""):
        self.name = name
        self.ok = ok
        self.expected = expected
        self.actual = actual
        self.detail = detail

    @property
    def gap(self):
        """Cents between the two numbers, or None if the check did not run."""
        if self.expected is None or self.actual is None:
            return None
        return self.actual - self.expected

    def __repr__(self):
        state = {True: "ok", False: "FAIL", None: "unchecked"}[self.ok]
        return f"<Check {self.name} {state} {self.detail}>"


class Cents(int):
    """
    An amount that has already been counted in cents.

    This exists because of a bug, and the bug is worth the type. `cents(12)`
    reads a document's "12" as twelve units — twelve dollars — which is right
    for a field read off a receipt and catastrophic for a value some other
    module already converted. The receipt reader and the statement parser both
    hand their amounts on in cents, so a total of 1731 was re-read as $1,731
    and every charge in an imported statement was inflated a hundredfold.

    Marking the converted value makes the boundary safe by construction rather
    than by everyone remembering which side they are on. `cents()` returns one
    of these and passes one straight back out untouched.
    """

    __slots__ = ()

    def __repr__(self):
        return f"Cents({int(self)})"


def cents(value):
    """
    A money field as an integer number of cents, or None if it is not one.

    Returns None rather than raising or coercing to zero. A missing total and a
    total of nothing are different facts, and treating an unreadable field as
    0.00 is how a receipt that could not be read reconciles perfectly against a
    charge of nothing.

    Floats are accepted because upstream parsers produce them, and are routed
    through `str` so that 19.99 is nineteen ninety-nine rather than
    19.989999999999998.
    """
    # Before the int branch, because Cents *is* an int and would otherwise be
    # multiplied by a hundred on every hop between modules.
    if isinstance(value, Cents):
        return value
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Cents(value * 100)
    try:
        amount = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError, AttributeError):
        return None
    if not amount.is_finite():
        return None
    scaled = amount * 100
    # A third of a cent is not a rounding artefact of a two-decimal field; it is
    # a field that was never money. Say so rather than silently truncating.
    if scaled != scaled.to_integral_value():
        return None
    return Cents(int(scaled))


def _sum_lines(lines):
    """
    (total_cents, priced_line_count) over a receipt's line items.

    Returns None for the total if any line is unreadable: a subtotal check run
    over the lines that happened to parse is a check that gets easier the worse
    the parse was, which is the opposite of what it is for.
    """
    if not lines:
        return None, 0
    running = 0
    for line in lines:
        amount = cents(line.get("amount") if isinstance(line, dict) else line)
        if amount is None:
            return None, 0
        running += amount
    return running, len(lines)


def check_lines_sum_to_subtotal(receipt) -> Check:
    """Column against row: the items against the number that claims to be them."""
    lines_total, count = _sum_lines(receipt.get("lines"))
    subtotal = cents(receipt.get("subtotal"))
    if lines_total is None or subtotal is None:
        return Check("lines_sum_to_subtotal", None,
                     detail="the receipt does not state both line items and a subtotal")
    allowance = ROUNDING_ALLOWANCE_PER_LINE * count
    ok = abs(lines_total - subtotal) <= allowance
    return Check("lines_sum_to_subtotal", ok, expected=subtotal, actual=lines_total,
                 detail=(f"{count} line items sum to {_money(lines_total)}; the "
                         f"receipt prints a subtotal of {_money(subtotal)}"))


def check_subtotal_builds_the_total(receipt) -> Check:
    """
    Subtotal + tax + tip + fees - discount against the printed total.

    The adjustments are optional and absent is treated as zero -- but only the
    adjustments. A missing *subtotal* or *total* leaves the check unrun, because
    those are the two numbers being compared, and defaulting either to zero
    would manufacture a comparison out of an absence.
    """
    subtotal = cents(receipt.get("subtotal"))
    total = cents(receipt.get("total"))
    if subtotal is None or total is None:
        return Check("subtotal_builds_total", None,
                     detail="the receipt does not state both a subtotal and a total")

    built = subtotal
    parts = [f"subtotal {_money(subtotal)}"]
    for field, sign, label in (("tax", 1, "tax"), ("tip", 1, "tip"),
                               ("fees", 1, "fees"), ("discount", -1, "discount")):
        raw = receipt.get(field)
        if raw is None:
            continue
        amount = cents(raw)
        if amount is None:
            return Check("subtotal_builds_total", None,
                         detail=f"the {label} line is present but unreadable")
        built += sign * amount
        parts.append(f"{'-' if sign < 0 else '+'} {label} {_money(abs(amount))}")

    ok = built == total
    return Check("subtotal_builds_total", ok, expected=total, actual=built,
                 detail=" ".join(parts) + f" = {_money(built)}, "
                        f"against a printed total of {_money(total)}")


def check_receipt_matches_the_charge(receipt, charge) -> Check:
    """
    The receipt's total against the amount that actually left the account.

    The one check that crosses documents, and the only one that can catch a
    merchant charging something other than what they printed.

    Compared as **magnitudes**, because the two documents do not share a sign
    convention and neither is wrong about it. A statement writes money out as
    negative; a receipt prints what you paid as a positive number and has no
    notion of direction at all. Comparing them signed fails every purchase ever
    made, which is how this was found.

    Direction is not thereby ignored, it is handled one step earlier: the
    matcher offers no receipt for a money-*in* line, because a receipt
    reconciles a payment and a credit is not one. Without that, a $50 refund
    would reconcile perfectly against the $50 purchase receipt it reverses.
    """
    total = cents(receipt.get("total")) if receipt else None
    charged = cents((charge or {}).get("amount"))
    if total is None or charged is None:
        return Check("receipt_matches_charge", None,
                     detail=("no receipt is matched to this charge" if total is None
                             else "the statement line states no amount"))
    ok = abs(total) == abs(charged)
    return Check("receipt_matches_charge", ok, expected=abs(charged), actual=abs(total),
                 detail=(f"receipt total {_money(abs(total))} against "
                         f"{_money(abs(charged))} charged"))


def check_statement_lines_sum_to_its_total(statement) -> Check:
    """
    A statement's own rows against the period total it declares.

    Catches the truncated export, which is the failure that quietly makes every
    other verdict on the page meaningless: rows that were never read cannot be
    reported as unmatched, so a half-read statement reconciles beautifully.
    """
    rows = statement.get("lines") or statement.get("transactions")
    declared = cents(statement.get("period_total"))
    if not rows or declared is None:
        return Check("statement_sums_to_period_total", None,
                     detail="the statement declares no period total")
    running = 0
    for row in rows:
        amount = cents(row.get("amount") if isinstance(row, dict) else row)
        if amount is None:
            return Check("statement_sums_to_period_total", None,
                         detail="a statement row states no readable amount")
        running += amount
    ok = running == declared
    return Check("statement_sums_to_period_total", ok, expected=declared,
                 actual=running,
                 detail=(f"{len(rows)} rows sum to {_money(running)}; the "
                         f"statement declares {_money(declared)}"))


def reconcile(receipt=None, charge=None) -> dict:
    """
    Everything knowable about one charge, and the verdict that follows.

    The rule for combining checks is deliberately not a score. One failure is a
    failure; no failures and no successful checks is *unchecked*, not a pass.
    A verdict that improves as the evidence thins is not a verdict.
    """
    receipt = receipt or {}
    checks = [
        check_lines_sum_to_subtotal(receipt),
        check_subtotal_builds_the_total(receipt),
        check_receipt_matches_the_charge(receipt, charge),
    ]
    failed = [c for c in checks if c.ok is False]
    passed = [c for c in checks if c.ok is True]

    if failed:
        state = DISCREPANT
    elif passed:
        state = RECONCILED
    else:
        state = UNCHECKED

    return {
        "verdict": state,
        "checks": checks,
        "failed": failed,
        "at_risk": cents((charge or {}).get("amount")),
        "why": _why(state, failed, checks),
    }


def _why(state, failed, checks) -> str:
    """
    One line a person reads in the queue, before any number.

    For an unchecked item this is not simply the first unrun check. With no
    receipt at all every check is unrun, and the first one in the list says
    "the receipt does not state both line items and a subtotal" -- true, and a
    baffling thing to read about a charge that has no receipt. The absence of
    the document outranks anything missing inside it.
    """
    if state == DISCREPANT:
        return failed[0].detail
    if state == RECONCILED:
        return f"{len([c for c in checks if c.ok])} checks agree"

    across = next((c for c in checks if c.name == "receipt_matches_charge"), None)
    if across is not None and across.ok is None and "no receipt" in across.detail:
        return across.detail
    return next((c.detail for c in checks if c.ok is None), "nothing to check")


def _money(c) -> str:
    """Cents as a signed amount. No currency symbol: the ledger knows, this does not."""
    if c is None:
        return "—"
    sign = "-" if c < 0 else ""
    c = abs(c)
    return f"{sign}{c // 100}.{c % 100:02d}"
