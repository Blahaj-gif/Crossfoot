"""
The four things a person actually wants to put this into.

Each writes a file the target's own importer reads. Nothing here opens a
socket — see the module docstring in `rows.py` for why that is a feature and
not a shortcoming.

    generic    a plain CSV, for a spreadsheet or anything else
    actual     Actual Budget's importer: Date / Payee / Notes / Amount
    firefly    Firefly III's data importer, plus the JSON config so the column
               mapping is not twenty dropdowns the first time
    beancount  plain-text accounting, verdict as metadata on the posting
"""
import csv
import io
import json

from crossfoot.export import rows as R

#: Every verdict tag, so a target that needs them enumerated (Firefly's config,
#: a filter, a bulk delete) does not have to hardcode the list.
TAGS = (R.RECONCILED, R.ACCEPTED, R.DISCREPANT, R.AMBIGUOUS, R.UNCHECKED,
        R.DUPLICATE)


#: Characters that make a spreadsheet treat a cell as a formula rather than as
#: text. `=cmd|' /C calc'!A1` in a payee column is a working remote-execution
#: payload the moment somebody opens the export in Excel.
#:
#: The threat is not theoretical for *this* program specifically: a payment
#: descriptor is set by the merchant, the whole purpose of these files is to be
#: opened in something else, and "here is your statement" is a plausible way to
#: hand somebody a crafted CSV in the first place.
_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def _defused(value):
    """
    A cell that cannot become a formula, and a payee that cannot become a row.

    Two separate problems with one answer. A leading `=` is prefixed with an
    apostrophe, which is the documented mitigation and which spreadsheets strip
    on display. A newline is removed, because a description carrying one splits
    into a second CSV record — or, in a beancount ledger, into a second
    *transaction*.

    This alters the data, which this project otherwise refuses to do. The
    exception is deliberate: the alternative is emitting a file whose contents
    execute, and a payee legitimately beginning with `=` does not exist. A
    negative *amount* is untouched, because amounts are written as numbers by
    the caller and never pass through here as text.
    """
    if not isinstance(value, str):
        return value
    flattened = value.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    flattened = "".join(c for c in flattened if c == "\t" or ord(c) >= 32)
    flattened = flattened.replace("\t", " ").strip()
    if flattened.startswith(_FORMULA_LEAD):
        return "'" + flattened
    return flattened


def _csv(fieldnames, records) -> str:
    buffer = io.StringIO()
    # Explicit \n: the default writes \r\n, and a CSV that arrives with mixed
    # endings is the classic reason an importer sees one enormous row.
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow({key: _defused(value) for key, value in record.items()})
    return buffer.getvalue()


def generic(rows) -> str:
    """Everything, named plainly. The format to read if you are not sure."""
    return _csv(["date", "description", "amount", "verdict", "why", "receipt",
                 "checks"], rows)


def actual(rows) -> str:
    """
    Actual Budget's CSV importer: Date, Payee, Notes, Amount.

    The verdict goes in Notes as a `#hashtag`, which is how Actual carries tags
    — it has no separate tag column, and a note that reads as prose is a note
    nobody can filter on. The reason follows the tag, because the tag says
    *what* and the person opening this in April wants *why*.
    """
    return _csv(["Date", "Payee", "Notes", "Amount"], [
        {"Date": row["date"],
         "Payee": row["description"],
         "Notes": _hashtag(row["verdict"]) + (f" {row['why']}" if row["why"] else ""),
         "Amount": row["amount"]}
        for row in rows])


def _hashtag(tag: str) -> str:
    """`crossfoot:does-not-reconcile` as `#crossfoot-does-not-reconcile`."""
    return "#" + tag.replace(":", "-")


def firefly(rows) -> str:
    """
    Firefly III's data importer.

    Tags are a first-class column there and the importer splits on commas, so
    the verdict arrives as a real tag rather than as text inside a description.
    """
    return _csv(["date", "description", "amount", "tags", "notes"], [
        {"date": row["date"],
         "description": row["description"],
         "amount": row["amount"],
         "tags": row["verdict"],
         "notes": " | ".join(p for p in (row["why"], row["receipt"] and
                                         f"receipt: {row['receipt']}",
                                         row["checks"]) if p)}
        for row in rows])


def firefly_config(account_id: str = "") -> str:
    """
    The importer's JSON configuration, so the column mapping is not twenty
    dropdowns the first time and not twenty dropdowns again next month.

    `account_id` is the Firefly asset account these transactions belong to.
    Left blank deliberately when unknown: a wrong account id files somebody's
    whole month against the wrong balance, and an empty one makes the importer
    ask rather than guess.
    """
    return json.dumps({
        "version": 3,
        "source": "crossfoot",
        "date": "Y-m-d",
        "delimiter": "comma",
        "headers": True,
        "default_account": int(account_id) if str(account_id).isdigit() else 0,
        "roles": ["date_transaction", "description", "amount", "tags-comma", "note"],
        "do_mapping": [False, False, False, False, False],
        "mapping": [[], [], [], [], []],
        "duplicate_detection_method": "cell",
        "unique_column_index": 1,
        "unique_column_type": "description",
    }, indent=2) + "\n"


def beancount(rows, account: str = "Assets:Bank:Checking",
              expenses: str = "Expenses:Unknown") -> str:
    """
    Plain-text accounting, with the verdict as metadata on the transaction.

    Beancount's own `!` flag marks a transaction needing attention, and using
    it here is the whole point: a ledger opened in bean-check shows the
    unreconciled ones without anyone having to remember a tag.
    """
    out = []
    for row in rows:
        if not row["date"]:
            continue                    # a dated ledger cannot hold an undated entry
        flag = "*" if row["verdict"] in (R.RECONCILED, R.ACCEPTED) else "!"
        # Flattened before quoting. A description containing a newline used to
        # split the ledger open mid-transaction: the payee ran on to a second
        # line and everything after it was parsed as further directives.
        payee = _defused(row["description"]).replace('"', "'")
        out.append(f'{row["date"]} {flag} "{payee}"')
        out.append(f'  crossfoot-verdict: "{_defused(row["verdict"])}"')
        if row["why"]:
            out.append(f'  crossfoot-why: "{_defused(row["why"]).replace(chr(34), chr(39))}"')
        if row["receipt"]:
            out.append(f'  crossfoot-receipt: "{_defused(row["receipt"]).replace(chr(34), chr(39))}"')
        out.append(f"  {account}  {row['amount']} USD")
        out.append(f"  {expenses}")
        out.append("")
    return "\n".join(out)


TARGETS = {
    "generic": {"render": generic, "suffix": ".csv",
                "note": "a plain CSV — open it in anything"},
    "actual": {"render": actual, "suffix": ".csv",
               "note": "Actual Budget: Tools -> Import, and the verdict "
                       "arrives as a #hashtag in the note"},
    "firefly": {"render": firefly, "suffix": ".csv",
                "note": "Firefly III data importer; the .json beside it is the "
                        "column mapping, so upload both"},
    "beancount": {"render": beancount, "suffix": ".beancount",
                  "note": "unreconciled entries carry beancount's own ! flag"},
}
