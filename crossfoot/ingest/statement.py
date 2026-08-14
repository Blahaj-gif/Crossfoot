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
    "amount": ("amount", "value", "transaction amount", "amt",
               # Measured against 33 real exports from open-source importers.
               # A bank that writes its own language writes all of it: the
               # German column is "Betrag" beside "Buchungstag" and
               # "Kontostand", and none of the three was here.
               "betrag", "importe", "importo", "montant", "bedrag", "belopp",
               "kwota", "valor", "iznos", "summa"),
    "debit": ("debit", "withdrawal", "withdrawals", "money out", "paid out",
              "debit amount", "soll", "debito", "debit eur"),
    "credit": ("credit", "deposit", "deposits", "money in", "paid in",
               "credit amount", "haben", "credito"),
    "balance": ("balance", "running balance", "closing balance", "balance after",
                "kontostand", "saldo", "solde", "saldo contabile"),
}

#: What a bank might separate columns with. Comma first because it is the
#: commonest, semicolon second because it is the European standard -- and it is
#: the European standard *because* the comma is the decimal mark there, which
#: is exactly the population this project already goes to some trouble to read.
#: Reading their money format and not their column format was half a job.
_DELIMITERS = (",", ";", "\t", "|")


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


#: A currency in brackets after a column name is a note about the units, not
#: part of the name. N26 exports `"Amount (EUR)"`, which normalised to
#: `amount eur` and matched nothing, so a whole bank's exports were refused for
#: having said which currency they were in.
_QUALIFIER = re.compile(r"\s*[\(\[][^)\]]*[\)\]]\s*")


def _column_map(fieldnames) -> dict:
    """
    Which column is which, by name. Unmapped columns are kept, not discarded --
    a reference number this does not understand is still evidence a human may
    need in the queue.

    A header is tried whole first and only then with a bracketed qualifier
    removed, so that a bank which really does name a column "Amount (Original)"
    does not have it read as the amount by a rule meant for currencies.
    """
    found = {}
    for raw in fieldnames or []:
        candidates = [_normalise(raw)]
        stripped = _normalise(_QUALIFIER.sub(" ", raw or ""))
        if stripped and stripped != candidates[0]:
            candidates.append(stripped)
        for key in candidates:
            matched = False
            for role, names in _HEADERS.items():
                if key in names and role not in found:
                    found[role] = raw
                    matched = True
                    break
            if matched:
                break
    return found


#: How far into a file the header is allowed to be. Real exports open with a
#: blank line or two, or with an account number and a period — Mint's own
#: sample starts with three empty lines. Bounded because "search until you find
#: something that looks like a header" would eventually find one in the data.
_HEADER_SEARCH_LINES = 8


def _from_header(text: str, delimiter: str) -> str:
    """
    The file from its header row onwards, skipping any preamble above it.

    `csv.DictReader` takes the first line as the header, whatever it is. Given
    a file that opens with three blank lines it produces rows keyed on
    `None` — which surfaced as "no amount column found" on a file whose header
    plainly says Amount, and that is a confusing thing to be told.

    A candidate has to map at least two known roles, one of which is a money
    column, before it is believed. That is a deliberately high bar: reading the
    wrong line as a header would misname every column in the file, and a
    preamble line like "Account,12345" would otherwise qualify.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines[:_HEADER_SEARCH_LINES]):
        if not line.strip():
            continue
        try:
            fields = next(csv.reader(io.StringIO(line), delimiter=delimiter))
        except (csv.Error, StopIteration):
            continue
        roles = _column_map(fields)
        if len(roles) >= 2 and ({"amount", "debit", "credit"} & set(roles)):
            return "\n".join(lines[index:])
    # Nothing in the first few lines looks like a header. Hand the file back
    # untouched so the existing error names the real problem — "no amount
    # column found", with the list of what was looked for — rather than a
    # complaint about a header this invented.
    return text


def _delimiter(text: str) -> str:
    """
    What this file separates columns with, decided from its own header row.

    Sniffed rather than assumed, and the assumption it replaces was costly:
    `csv.DictReader` defaults to a comma, so every semicolon-separated export
    arrived as a single enormous column and was refused for having no amount
    in it. That is the European convention, and it is the European convention
    precisely *because* the comma is the decimal mark there — the same
    population this module already goes to real trouble to read money for.
    Reading their decimal separator and not their column separator was half a
    job done twice.

    Decided on the header line alone. A quoted description containing a
    semicolon can outvote the real delimiter further down a file, and the
    header is the one line a bank writes without free text in it.
    """
    line = next((l for l in text.splitlines() if l.strip()), "")
    best, best_count = ",", 0
    for candidate in _DELIMITERS:
        # csv, not str.split, so a delimiter inside a quoted header does not
        # count towards its own case.
        try:
            fields = next(csv.reader(io.StringIO(line), delimiter=candidate))
        except (csv.Error, StopIteration):
            continue
        if len(fields) > best_count:
            best, best_count = candidate, len(fields)
    return best


def parse_csv(text: str) -> dict:
    """
    A bank CSV export as a statement.

    Amounts may arrive as one signed column or as separate debit and credit
    columns; both are normalised to signed cents, money out negative. A row
    carrying both a debit and a credit is refused rather than netted -- that is
    not a transaction, it is two columns misread as one row.
    """
    delimiter = _delimiter(text)
    rows = list(csv.DictReader(io.StringIO(_from_header(text, delimiter)),
                               delimiter=delimiter))
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

    # A running balance is only a chain if the rows are in the order the bank
    # applied them. Found on a real ING España export whose rows arrive in no
    # date order at all: the walk broke immediately and reported "a row is
    # missing here", which was false, and — because a failed completeness check
    # suppresses every finding — the whole audit went silent on a complete
    # file. That is the tool being confidently wrong about somebody's bank
    # statement, which is the one thing it is built not to do.
    #
    # Unrun, not failed. Nothing here can tell whether such a file is short;
    # sorting it first would invent an order the bank did not state, and rows
    # sharing a date have no order to recover.
    dated = [l.get("date") for l in lines if l.get("date")]
    if len(dated) == len(lines) and any(b < a for a, b in zip(dated, dated[1:])):
        return Check("balance_walk", None,
                     detail=("the rows are not in date order, so the running "
                             "balance is not a chain and cannot be walked"))

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
