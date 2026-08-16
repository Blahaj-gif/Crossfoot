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
import re
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


#: Separators a number may carry, and nothing else. Anything outside this set
#: plus digits and a sign means the field was not money.
_SEPARATORS = ".,"

#: Currency marks and accounting furniture stripped before a number is read.
#: Not a formatting nicety: a statement column of "$-842.19" or "842.19 CR"
#: parsed to None, and a None amount used to make the row disappear.
_FURNITURE = re.compile(r"[$£€¥₹\s ']|(?<![A-Za-z])(?:USD|EUR|GBP|JPY|THB|SGD|AUD|CAD|CHF|SEK|NOK|DKK|PLN|CZK|HUF|INR|CNY|HKD|NZD|ZAR|MXN|BRL)(?![A-Za-z])",
                        re.I)


def _groups_correctly(whole: str, separator: str) -> bool:
    """
    Whether the whole part is grouped the way a thousands separator groups.

    "1.234.567" is one million two hundred thirty-four thousand five hundred
    and sixty-seven. "1.2" is not a number at all, and without this check it
    was quietly flattened to "12" -- so `cents("1.2.3")` returned 12.30 rather
    than admitting the field was never money.
    """
    if separator not in whole:
        return whole.isdigit() or whole == ""
    groups = whole.split(separator)
    if not all(g.isdigit() for g in groups):
        return False
    # A leading group of "0" is not a group. No locale writes one thousand as
    # "0.001" — and without this, that string was read as grouped digits and
    # came back as 1.00. Found while testing absurd magnitudes; it matters at
    # the small end, where a fuel receipt's per-unit "0.001" became a pound.
    if len(groups) > 1 and groups[0].lstrip("0") == "":
        return False
    return 1 <= len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:])


def detect_decimal_separator(samples) -> str:
    """
    Which character is the decimal point across a whole document.

    A single value cannot always say. "1.005" is one thousand and five to a
    German bank and three decimal places to nobody -- but in a file that also
    contains "17.31", the point is plainly the decimal point and "1.005" is a
    field to refuse rather than read as 1,005.

    Evidence, strongest first: any value carrying both separators settles it
    outright; otherwise a separator followed by one or two digits is a decimal
    point. Values that disagree return "" -- ambiguous, decide nothing -- which
    is the honest answer for a file that mixes conventions and a good reason to
    look at it.
    """
    votes = set()
    for sample in samples:
        text = _FURNITURE.sub("", str(sample or "").strip())
        last_point, last_comma = text.rfind("."), text.rfind(",")
        if last_point >= 0 and last_comma >= 0:
            return "." if last_point > last_comma else ","
        position = max(last_point, last_comma)
        if position < 0:
            continue
        trailing = text[position + 1:]
        if trailing.isdigit() and 1 <= len(trailing) <= 2:
            votes.add(text[position])
    return votes.pop() if len(votes) == 1 else ""


def _decimal_separator(text: str):
    """
    Which character is the decimal point in this one value, from the value.

    The rule the earlier code did not have, and the reason it read the ordinary
    European receipt total "17,31" as **$1,731.00**: it stripped every comma and
    read whatever was left.

      * Both separators present -- the **later** one is the decimal point.
        "1,234.56" and "1.234,56" are the same amount written two ways, and
        which comes last settles it with no ambiguity at all.
      * One separator, followed by exactly **three** digits -- it is a thousands
        separator. Money is not written to three decimal places, so "1,234" and
        "1.234" both mean one thousand two hundred and thirty four.
      * One separator, followed by one or two digits -- it is the decimal point.
      * No separator -- nothing to decide.

    Returns the character, or None when the value carries no separator. Raises
    nothing: an unreadable value is `cents`'s problem, not this function's.

    Known limit, stated rather than hidden: the three-digit rule assumes a
    two-decimal currency. Dinars and the dirham are filed to three, and this
    would read 1.234 KWD as 1,234. Out of scope until a corpus contains one.
    """
    last_point, last_comma = text.rfind("."), text.rfind(",")
    if last_point >= 0 and last_comma >= 0:
        return "." if last_point > last_comma else ","
    position = max(last_point, last_comma)
    if position < 0:
        return None
    separator = text[position]
    trailing = text[position + 1:]
    if len(trailing) == 3 and trailing.isdigit():
        return None                 # a thousands separator; the value is whole
    return separator


def cents(value, decimal: str = ""):
    """
    A money field as an integer number of cents, or None if it is not one.

    `decimal` is the separator the surrounding *document* uses, where the
    caller knows it — `detect_decimal_separator` over the whole column. Passing
    it turns the one genuinely ambiguous shape into a refusal instead of a
    guess: in a file whose decimal point is ".", the value "1.005" has three
    decimal places and is not money, where the same string alone is far more
    likely to be a European one thousand and five.

    Returns None rather than raising or coercing to zero. A missing total and a
    total of nothing are different facts, and treating an unreadable field as
    0.00 is how a receipt that could not be read reconciles perfectly against a
    charge of nothing.

    Reads the decimal separator out of the value itself rather than assuming a
    locale -- see `_decimal_separator`. Accepts the accounting conventions a
    real export uses: a currency mark, parentheses for negative, and a trailing
    CR or DR. Each of those used to produce None, and a None amount used to make
    the whole row vanish from the statement.

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
    if isinstance(value, float):
        text = repr(value)
    elif isinstance(value, Decimal):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        return None

    text = _FURNITURE.sub("", text.strip())
    if not text:
        return None

    sign = 1
    # Accounting negatives. "(42.00)" is a debit of forty-two, and it is the
    # commonest export convention this could not read.
    if text.startswith("(") and text.endswith(")"):
        sign, text = -1, text[1:-1].strip()
    upper = text.upper()
    for mark, direction in (("CR", 1), ("DR", -1)):
        if upper.endswith(mark):
            sign *= direction
            text = text[: -len(mark)].strip()
            break
    if text.startswith("-"):
        sign, text = -sign, text[1:].strip()
    elif text.startswith("+"):
        text = text[1:].strip()

    if not text or any(c not in "0123456789" + _SEPARATORS for c in text):
        return None

    separator = _decimal_separator(text)
    # The document overrules the value. Where the file's decimal point is known
    # to be ".", "1.005" is three decimal places rather than a European
    # thousand, and three decimal places in a two-decimal currency is a field
    # to refuse rather than round.
    if decimal and decimal in text:
        separator = decimal
    elif decimal and separator == decimal:
        separator = None

    if separator is None:
        grouping = "." if "." in text else ","
        if not _groups_correctly(text, grouping):
            return None
        digits = text.replace(".", "").replace(",", "")
        if not digits.isdigit():
            return None
        return Cents(sign * int(digits) * 100)

    whole, _, fraction = text.rpartition(separator)
    if not fraction.isdigit():
        return None
    other = "," if separator == "." else "."
    if not _groups_correctly(whole, other):
        return None
    whole = whole.replace(other, "")

    try:
        amount = Decimal(f"{whole or '0'}.{fraction}")
    except InvalidOperation:
        return None
    if not amount.is_finite():
        return None
    scaled = amount * 100
    # A third of a cent is not a rounding artefact of a two-decimal field; it is
    # a field that was never money. Say so rather than silently truncating.
    if scaled != scaled.to_integral_value():
        return None
    return Cents(sign * int(scaled))


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


#: Symbol to code, so a receipt marked "$" and a statement marked "USD" are not
#: mistaken for two currencies. "$" is read as USD, which is a guess about
#: Canada, Australia and Singapore — so it is only ever used to establish
#: *sameness*, never to claim a document is American.
_CURRENCY_CODES = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "JPY", "₹": "INR"}


def _currency_of(document):
    mark = (document or {}).get("currency")
    if not mark:
        return None
    mark = str(mark).strip()
    return _CURRENCY_CODES.get(mark, mark.upper() if mark.isalpha() else None)


def check_parts_do_not_exceed_the_total(receipt) -> Check:
    """
    Tax and tip are summed *into* the total, so neither can be larger than it.

    Arithmetic, not a heuristic, and it exists because a photograph found the
    gap. A French receipt's "TVA 5,5%  0,20" came off the page as "8,20", and
    the receipt reconciled: the total was read correctly, the charge matched
    it, and the tax was compared with nothing at all because that receipt
    prints no subtotal this recognises. A tax of 8.20 inside a total of 3.80 is
    impossible on its face, and nothing was saying so.

    Deliberately only tax and tip. A discount can legitimately be most of the
    price, and a single line item can exceed the total when a discount follows
    it, so a rule covering those would fire on ordinary receipts. These two
    cannot exceed the total without something having been misread.

    Compared on magnitudes: a refund receipt is negative throughout, and it is
    still true there that the parts cannot outgrow the whole.
    """
    total = cents((receipt or {}).get("total"))
    if total is None or not total:
        return Check("parts_within_total", None,
                     detail="the receipt states no total to compare against")

    compared = []
    for name in ("tax", "tip"):
        part = cents((receipt or {}).get(name))
        if part is None:
            continue
        compared.append(name)
        if abs(part) > abs(total):
            return Check("parts_within_total", False, expected=abs(total),
                         actual=abs(part),
                         detail=(f"the {name} reads as {_money(abs(part))} inside a "
                                 f"total of {_money(abs(total))}, which cannot be "
                                 "right — one of the two was misread"))

    if not compared:
        # A receipt stating only a total has no parts, so "the parts fit inside
        # it" is vacuously true and means nothing. Returning a pass here made a
        # receipt with a single number reconcile on the strength of a
        # comparison that never happened, which is the exact failure this
        # module is built to refuse.
        return Check("parts_within_total", None,
                     detail="the receipt states no tax or tip to compare")

    return Check("parts_within_total", True,
                 detail=f"{' and '.join(compared)} fit inside the total")


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

    # Currency was read off the receipt, stored, and consulted by nothing --
    # which is worse than not reading it, because it looked handled. Two
    # amounts in different currencies are not equal and are not unequal; there
    # is no comparison to make without a rate, so the check does not run.
    theirs = _currency_of(receipt)
    ours = _currency_of(charge)
    if theirs and ours and theirs != ours:
        return Check("receipt_matches_charge", None,
                     detail=(f"the receipt is in {theirs} and the charge in {ours} — "
                             "comparing them needs the rate and the fee the bank "
                             "applied, neither of which is in either document"))

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
        check_parts_do_not_exceed_the_total(receipt),
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
