"""
Step 1 — Drop. Reading a statement, and refusing to read half of one.

A statement export is the spine of everything downstream: a charge that is not
in it cannot be reported as unmatched, and a receipt that has no charge to sit
against is simply invisible. So the failure that matters here is not a
misparsed row, it is a **short** file — the export that stopped at 500 rows, the
date range that started a day late, the download that was interrupted.

That failure is silent by construction. Every verdict on a half-read statement
is individually correct and the page as a whole is a lie, because the rows that
were never read are indistinguishable from rows that do not exist.

Two independent defences, both using numbers the bank itself filed:

  * **The balance walk.** Where the export carries a running balance, each row's
    balance must be the previous one plus that row's amount. A missing row
    breaks the chain at exactly the point it was dropped, and says where.
  * **The declared total.** Where the export states a period total or an
    opening and closing balance, the rows must sum to it. This catches a file
    truncated at the *end*, which a balance walk cannot see: the surviving
    chain is perfectly consistent right up to where it stops.

Neither is inferred. Both compare numbers the statement states twice.
"""
import csv
import datetime
import io
import re

from crossfoot.verdict import Cents, Check, cents, detect_decimal_separator

#: Header names seen in the wild, lowercased and stripped of punctuation. Not a
#: guess-by-position scheme: a bank that reorders its columns between exports
#: would silently swap amount and balance, and the two are the same shape.
_HEADERS = {
    "date": ("date", "transaction date", "posted date", "posting date",
             "date posted", "trans date", "value date", "booking date"),
    "description": ("description", "details", "narrative", "payee", "merchant",
                    "memo", "particulars", "transaction description", "name"),
    "amount": ("amount", "value", "transaction amount", "amt"),
    "debit": ("debit", "withdrawal", "withdrawals", "money out", "paid out",
              "debit amount"),
    "credit": ("credit", "deposit", "deposits", "money in", "paid in",
               "credit amount"),
    "balance": ("balance", "running balance", "closing balance", "balance after"),
}


class StatementError(Exception):
    """The file cannot be trusted as a complete statement."""


class AmbiguousDates(StatementError):
    """Nothing in the file says whether 09/08 is September or August."""


_NUMERIC_DATE = re.compile(r"^(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{1,4})")

DAY_FIRST = "dmy"
MONTH_FIRST = "mdy"


def detect_date_order(samples):
    """
    Whether this file writes 09/08 as 9 August or 8 September, from the file.

    The rule the earlier code did not have. It tried `%d/%m/%Y` before
    `%m/%d/%Y` and therefore silently read every US export as European, moving
    dates by up to eleven days -- far enough to push a receipt out of the
    posting window, or into the wrong one.

    Evidence is arithmetic and needs no locale: a first component above twelve
    can only be a day, a second component above twelve can only be a day in the
    second position. ISO dates settle nothing because they are already
    unambiguous. Returns DAY_FIRST, MONTH_FIRST, or None for a file that never
    once put a day above the twelfth in the sample -- which is a real and
    common file, and is why this returns rather than guesses.
    """
    order = None
    for sample in samples:
        match = _NUMERIC_DATE.match(str(sample or "").strip())
        if not match:
            continue
        first, second, third = (int(g) for g in match.groups())
        if len(match.group(1)) == 4:
            continue                       # ISO: year first, nothing to learn
        seen = DAY_FIRST if first > 12 else (MONTH_FIRST if second > 12 else None)
        if seen is None:
            continue
        if order is not None and order != seen:
            raise AmbiguousDates(
                "this file contains dates in both orders — one row puts a day "
                "above the twelfth first and another puts it second. One of "
                "them is being misread and nothing here can tell which.")
        order = seen
    return order


def _iso(value, order):
    """A date string as ISO, or None. Never a guess between the two orders."""
    text = str(value or "").strip()
    if not text:
        return None
    match = _NUMERIC_DATE.match(text)
    if not match:
        return None
    first, second, third = (int(g) for g in match.groups())
    if len(match.group(1)) == 4:
        year, month, day = first, second, third
    else:
        day, month = (first, second) if order == DAY_FIRST else (second, first)
        year = third + (2000 if third < 100 else 0)
    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


def _dates(rows, columns):
    """
    Every date in the file as ISO, having decided the order once.

    Resolved here, at the boundary, because this is the only place the *whole
    document* is in hand. Downstream then never sees an ambiguous date, which
    is better than every consumer having to remember to ask.
    """
    if "date" not in columns:
        return {}
    raw = [row.get(columns["date"]) for row in rows]
    order = detect_date_order(raw)
    if order is None:
        needs_order = [r for r in raw if r and _NUMERIC_DATE.match(str(r).strip())
                       and len(_NUMERIC_DATE.match(str(r).strip()).group(1)) != 4]
        if needs_order:
            raise AmbiguousDates(
                f"the dates in this file (e.g. {str(needs_order[0]).strip()!r}) could be "
                "day-first or month-first and no row settles it — no day above the "
                "twelfth appears anywhere. Re-export with ISO dates, or say which "
                "order it is; guessing moves every date by up to eleven days.")
    return {id(row): _iso(row.get(columns["date"]), order) for row in rows}


def _normalise(header: str) -> str:
    return re.sub(r"[^a-z ]", " ", (header or "").lower()).strip()


def _column_map(fieldnames) -> dict:
    """
    Which column is which, by name. Unmapped columns are kept, not discarded --
    a reference number this does not understand is still evidence a human may
    need in the queue.
    """
    found = {}
    for raw in fieldnames or []:
        key = _normalise(raw)
        for role, names in _HEADERS.items():
            if key in names and role not in found:
                found[role] = raw
                break
    return found


def parse_csv(text: str) -> dict:
    """
    A bank CSV export as a statement.

    Amounts may arrive as one signed column or as separate debit and credit
    columns; both are normalised to signed cents, money out negative. A row
    carrying both a debit and a credit is refused rather than netted -- that is
    not a transaction, it is two columns misread as one row.
    """
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise StatementError("the file contains no rows")

    columns = _column_map(rows[0].keys())
    has_amount = "amount" in columns
    has_split = "debit" in columns or "credit" in columns
    if not has_amount and not has_split:
        raise StatementError(
            "no amount column found — looked for "
            f"{', '.join(sorted(sum(( _HEADERS['amount'], _HEADERS['debit'], _HEADERS['credit']), ())))}")

    # The decimal separator is decided once, from every money cell in the file,
    # and then applied uniformly. Deciding it per value is how "17,31" became
    # $1,731.00, and a file that mixes conventions is a file worth looking at
    # rather than one to average over.
    money_columns = [columns[role] for role in ("amount", "debit", "credit", "balance")
                     if role in columns]
    decimal = detect_decimal_separator(
        row.get(column) for row in rows for column in money_columns)

    dates = _dates(rows, columns)

    lines = []
    for number, row in enumerate(rows, start=1):
        amount = _row_amount(row, columns, number, has_amount, decimal)
        if amount is None:
            continue                       # genuinely blank; `_row_amount` raises otherwise
        lines.append({
            "row": number,
            "date": dates.get(id(row)) or "",
            "description": (row.get(columns.get("description", "")) or "").strip(),
            "amount": amount,
            "balance": _cell(row, columns, "balance", number, decimal),
            "raw": {k: v for k, v in row.items() if v not in (None, "")},
        })

    if not lines:
        raise StatementError("no row carried a readable amount")
    return {"lines": lines, "source": "csv", "columns": sorted(columns),
            "decimal_separator": decimal, "currency": _currency(rows)}


def _cell(row, columns, role, number, decimal):
    """
    One money cell, or a refusal. Never a silent None for a non-empty field.

    A cell that holds something this cannot read is a statement this cannot be
    trusted about, which is the whole argument of the module -- and it was the
    module's own bug: an amount of "(42.00)" returned None, the row was skipped
    as blank, and `accept()` still reported the file usable.
    """
    if role not in columns:
        return None
    raw = row.get(columns[role])
    if raw is None or not str(raw).strip():
        return None
    value = cents(raw, decimal)
    if value is None:
        raise StatementError(
            f"row {number}: the {role} column holds {str(raw).strip()!r}, which "
            "is not an amount this can read. A row that cannot be read is a "
            "statement that cannot be trusted, so it is refused rather than "
            "skipped — every verdict downstream reports on what is *absent* "
            "from this file.")
    return value


def _row_amount(row, columns, number, has_amount, decimal):
    if has_amount:
        return _cell(row, columns, "amount", number, decimal)

    debit = _cell(row, columns, "debit", number, decimal)
    credit = _cell(row, columns, "credit", number, decimal)
    if debit and credit:
        raise StatementError(
            f"row {number} states both a debit ({debit / 100:.2f}) and a credit "
            f"({credit / 100:.2f}) — two columns have been read as one row")
    # Cents, not a bare int: these travel on into the matcher and the verdict
    # layer, which reads a plain integer as whole currency units.
    if debit is not None:
        return Cents(-abs(debit))
    if credit is not None:
        return Cents(abs(credit))
    return None


_CURRENCY_MARK = re.compile(
    r"[$£€¥₹]|(?<![A-Za-z])(?:USD|EUR|GBP|JPY|THB|SGD|AUD|CAD|CHF|SEK|NOK|DKK|"
    r"PLN|CZK|HUF|INR|CNY|HKD|NZD|ZAR|MXN|BRL)(?![A-Za-z])", re.I)

#: Which symbol belongs to which code, so a receipt marked "$" and a statement
#: marked "USD" are not treated as two different currencies.
_SYMBOLS = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "JPY", "₹": "INR"}


def normalise_currency(mark):
    """A symbol or code as a code, or None. `$` is read as USD, ambiguously."""
    if not mark:
        return None
    mark = str(mark).strip()
    return _SYMBOLS.get(mark, mark.upper() if mark.isalpha() else None)


def _currency(rows):
    """
    What this statement is denominated in, if it says so anywhere.

    Most exports do not, which is why this returns None rather than defaulting.
    A default here would be a currency claim nobody made, and the downstream
    check would then compare a receipt against an assumption.
    """
    found = set()
    for row in rows:
        for value in row.values():
            match = _CURRENCY_MARK.search(str(value or ""))
            if match:
                found.add(normalise_currency(match.group(0)))
    found.discard(None)
    return found.pop() if len(found) == 1 else None


_OFX_TRANSACTION = re.compile(r"<STMTTRN>(.*?)</STMTTRN>", re.S | re.I)
_OFX_FIELD = re.compile(r"<([A-Z]+)>([^<\r\n]*)", re.I)


def parse_ofx(text: str) -> dict:
    """
    OFX/QFX, which is SGML and does not close its leaf tags.

    Deliberately regex over a real parser: the leaf tags are unclosed by spec,
    so every XML parser either rejects the file or repairs it by guessing where
    elements end, and a guess about element boundaries in a financial document
    is a guess about which number belongs to which field.
    """
    blocks = _OFX_TRANSACTION.findall(text or "")
    if not blocks:
        raise StatementError("no <STMTTRN> blocks found — is this OFX?")

    lines = []
    for number, block in enumerate(blocks, start=1):
        fields = {k.upper(): v.strip() for k, v in _OFX_FIELD.findall(block)}
        amount = cents(fields.get("TRNAMT"))
        if amount is None:
            raise StatementError(f"transaction {number} states no readable TRNAMT")
        posted = fields.get("DTPOSTED", "")
        lines.append({
            "row": number,
            # OFX dates are YYYYMMDD with an optional time and bracketed zone.
            "date": f"{posted[0:4]}-{posted[4:6]}-{posted[6:8]}" if len(posted) >= 8 else "",
            "description": fields.get("NAME") or fields.get("MEMO") or "",
            "amount": amount,
            "balance": None,
            "raw": fields,
        })

    statement = {"lines": lines, "source": "ofx", "columns": []}
    closing = re.search(r"<LEDGERBAL>.*?<BALAMT>([^<\r\n]*)", text, re.S | re.I)
    if closing:
        statement["closing_balance"] = cents(closing.group(1))
    return statement


def parse(text: str, filename: str = "") -> dict:
    """Route by content, falling back to the extension only to break a tie."""
    looks_ofx = "<STMTTRN>" in (text or "").upper()
    if looks_ofx or filename.lower().endswith((".ofx", ".qfx")):
        return parse_ofx(text)
    return parse_csv(text)


# --------------------------------------------------------------------------
# The two completeness checks
# --------------------------------------------------------------------------

def check_balance_walk(statement) -> Check:
    """
    Each row's balance against the previous one plus that row's amount.

    Names the row where the chain first breaks, because that is where the file
    is short and it is the only actionable thing to say. Later breaks are
    consequences of the first and reporting them all buries the one that
    matters.
    """
    lines = [l for l in statement.get("lines") or [] if l.get("balance") is not None]
    if len(lines) < 2:
        return Check("balance_walk", None,
                     detail="the export carries no running balance to walk")

    for previous, current in zip(lines, lines[1:]):
        expected = previous["balance"] + current["amount"]
        if expected != current["balance"]:
            return Check(
                "balance_walk", False, expected=expected, actual=current["balance"],
                detail=(f"row {current['row']}: {previous['balance'] / 100:.2f} "
                        f"{current['amount'] / 100:+.2f} should leave "
                        f"{expected / 100:.2f}, but the statement says "
                        f"{current['balance'] / 100:.2f} — a row is missing here"))
    return Check("balance_walk", True,
                 detail=f"{len(lines)} balances step correctly")


def check_rows_sum_to_declared_total(statement) -> Check:
    """
    The rows against a total the statement states independently of them.

    Accepts either a declared period total or an opening and closing balance,
    because a file truncated at the *end* leaves a balance walk perfectly
    consistent right up to where it stops -- this is the only check that sees it.
    """
    lines = statement.get("lines") or []
    declared = cents(statement.get("period_total"))
    if declared is None:
        opening = cents(statement.get("opening_balance"))
        closing = cents(statement.get("closing_balance"))
        if opening is None or closing is None:
            return Check("rows_sum_to_declared_total", None,
                         detail=("the statement declares neither a period total "
                                 "nor both an opening and a closing balance"))
        declared = closing - opening

    total = sum(l["amount"] for l in lines)
    ok = total == declared
    return Check("rows_sum_to_declared_total", ok, expected=declared, actual=total,
                 detail=(f"{len(lines)} rows sum to {total / 100:.2f}; the "
                         f"statement declares {declared / 100:.2f}"))


def accept(statement) -> dict:
    """
    Run both completeness checks and say whether the file may be used.

    A failure here stops the pipeline rather than annotating it. Everything
    downstream reports on what is *absent* from the statement, and a short file
    makes every one of those reports wrong in the same invisible direction.
    """
    checks = [check_balance_walk(statement),
              check_rows_sum_to_declared_total(statement)]
    failed = [c for c in checks if c.ok is False]
    return {
        "usable": not failed,
        "checks": checks,
        "problems": [c.detail for c in failed],
        # Honest about the commonest case: a plain CSV with neither a running
        # balance nor a declared total cannot be checked for completeness at
        # all, and saying "verified" there would be the exact lie this module
        # exists to prevent.
        "verified_complete": bool([c for c in checks if c.ok is True]) and not failed,
    }
