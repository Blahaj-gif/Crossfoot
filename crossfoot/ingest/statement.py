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
import io
import re

from crossfoot.verdict import Cents, Check, cents

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

    lines = []
    for number, row in enumerate(rows, start=1):
        amount = _row_amount(row, columns, number, has_amount)
        if amount is None:
            continue                       # a blank line, not a broken one
        lines.append({
            "row": number,
            "date": (row.get(columns.get("date", "")) or "").strip(),
            "description": (row.get(columns.get("description", "")) or "").strip(),
            "amount": amount,
            "balance": cents(row.get(columns.get("balance", ""))) if "balance" in columns else None,
            "raw": {k: v for k, v in row.items() if v not in (None, "")},
        })

    if not lines:
        raise StatementError("no row carried a readable amount")
    return {"lines": lines, "source": "csv", "columns": sorted(columns)}


def _row_amount(row, columns, number, has_amount):
    if has_amount:
        return cents(row.get(columns["amount"]))

    debit = cents(row.get(columns.get("debit", ""))) if "debit" in columns else None
    credit = cents(row.get(columns.get("credit", ""))) if "credit" in columns else None
    if debit and credit:
        raise StatementError(
            f"row {number} states both a debit ({debit / 100:.2f}) and a credit "
            f"({credit / 100:.2f}) — two columns have been read as one row")
    # Cents, not a bare int: these travel on into the matcher and the verdict
    # layer, which reads a plain integer as whole currency units.
    if debit:
        return Cents(-abs(debit))
    if credit:
        return Cents(abs(credit))
    return None


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
