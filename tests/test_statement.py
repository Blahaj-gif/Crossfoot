"""
Step 1 — the short file, which is the only statement failure that matters.

A misparsed row shows up as a weird number somebody notices. A file that stops
early shows up as nothing at all: the rows that were never read cannot be
reported as unmatched, so a half-read statement produces a page of individually
correct verdicts that is collectively a lie.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot.ingest import statement as S
from crossfoot.verdict import Cents


def _csv(*rows, header="Date,Description,Amount,Balance"):
    return "\n".join([header, *rows]) + "\n"


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def test_a_signed_amount_column():
    parsed = S.parse_csv(_csv("2026-03-14,HOME DEPOT #4471,-842.19,1157.81"))
    assert parsed["lines"][0]["amount"] == -84219
    assert parsed["lines"][0]["balance"] == 115781
    assert parsed["lines"][0]["description"] == "HOME DEPOT #4471"


def test_split_debit_and_credit_columns_become_signed():
    text = _csv("2026-03-14,HOME DEPOT,842.19,,1157.81",
                "2026-03-15,SALARY,,3000.00,4157.81",
                header="Date,Description,Debit,Credit,Balance")
    lines = S.parse_csv(text)["lines"]
    assert lines[0]["amount"] == -84219
    assert lines[1]["amount"] == 300000


def test_a_row_with_both_a_debit_and_a_credit_is_refused_not_netted():
    """That is not a transaction. It is two columns read as one row."""
    text = _csv("2026-03-14,ODD,10.00,4.00,0.00",
                header="Date,Description,Debit,Credit,Balance")
    with pytest.raises(S.StatementError, match="one row"):
        S.parse_csv(text)


def test_columns_are_found_by_name_not_by_position():
    """
    A bank that reorders its columns between exports would otherwise swap
    amount and balance silently, and the two are the same shape.
    """
    text = _csv("1157.81,-842.19,HOME DEPOT,2026-03-14",
                header="Balance,Amount,Narrative,Posting Date")
    line = S.parse_csv(text)["lines"][0]
    assert line["amount"] == -84219 and line["balance"] == 115781
    assert line["description"] == "HOME DEPOT"


def test_a_file_with_no_amount_column_at_all_is_refused():
    with pytest.raises(S.StatementError, match="no amount column"):
        S.parse_csv(_csv("2026-03-14,HOME DEPOT", header="Date,Description"))


def test_an_unrecognised_column_is_kept_as_evidence():
    """A reference number this does not understand is still evidence."""
    text = _csv("2026-03-14,HOME DEPOT,-842.19,AUTH-9930X",
                header="Date,Description,Amount,Auth Code")
    assert S.parse_csv(text)["lines"][0]["raw"]["Auth Code"] == "AUTH-9930X"


def test_ofx_is_read_with_unclosed_leaf_tags():
    """
    OFX leaves its leaf tags unclosed by spec. Every XML parser either rejects
    the file or repairs it by guessing where elements end, and a guess about
    element boundaries in a financial document is a guess about which number
    belongs to which field.
    """
    text = """
    <OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>
    <STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260314120000[-5:EST]
    <TRNAMT>-842.19<FITID>001<NAME>HOME DEPOT #4471</STMTTRN>
    <STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260602<TRNAMT>-263.88
    <FITID>002<NAME>ADOBE INC</STMTTRN>
    <LEDGERBAL><BALAMT>1157.81<DTASOF>20260630</LEDGERBAL>
    </STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
    """
    parsed = S.parse_ofx(text)
    assert [l["amount"] for l in parsed["lines"]] == [-84219, -26388]
    assert parsed["lines"][0]["date"] == "2026-03-14"
    assert parsed["lines"][0]["description"] == "HOME DEPOT #4471"
    assert parsed["closing_balance"] == 115781


def test_routing_reads_the_content_before_the_extension():
    ofx = "<STMTTRN><TRNAMT>-1.00<NAME>X</STMTTRN>"
    assert S.parse(ofx, filename="export.csv")["source"] == "ofx"


# --------------------------------------------------------------------------
# The balance walk
# --------------------------------------------------------------------------

def test_a_complete_chain_of_balances_walks():
    text = _csv("2026-03-01,A,-10.00,90.00",
                "2026-03-02,B,-20.00,70.00",
                "2026-03-03,C,5.00,75.00")
    assert S.check_balance_walk(S.parse_csv(text)).ok is True


def test_a_dropped_row_breaks_the_walk_where_it_was_dropped():
    """The one failure this exists for, and it names the row."""
    text = _csv("2026-03-01,A,-10.00,90.00",
                "2026-03-03,C,5.00,75.00")     # the -20.00 row is gone
    check = S.check_balance_walk(S.parse_csv(text))
    assert check.ok is False
    assert "row 2" in check.detail
    assert "missing" in check.detail


def test_only_the_first_break_is_reported():
    """Later breaks are consequences of the first; listing them buries it."""
    text = _csv("2026-03-01,A,-10.00,90.00",
                "2026-03-02,B,-20.00,50.00",
                "2026-03-03,C,-5.00,20.00")
    detail = S.check_balance_walk(S.parse_csv(text)).detail
    assert "row 2" in detail and "row 3" not in detail


def test_an_export_with_no_balance_column_is_unchecked_not_passed():
    text = _csv("2026-03-01,A,-10.00", header="Date,Description,Amount")
    assert S.check_balance_walk(S.parse_csv(text)).ok is None


# --------------------------------------------------------------------------
# The declared total
# --------------------------------------------------------------------------

def test_rows_that_sum_to_the_declared_movement_pass():
    parsed = S.parse_csv(_csv("2026-03-01,A,-10.00,90.00",
                              "2026-03-02,B,-20.00,70.00"))
    parsed["opening_balance"] = "100.00"
    parsed["closing_balance"] = "70.00"
    assert S.check_rows_sum_to_declared_total(parsed).ok is True


def test_truncation_at_the_end_is_caught_here_and_nowhere_else():
    """
    A file cut short at the end leaves a balance walk perfectly consistent
    right up to where it stops. Only the declared total sees it.
    """
    parsed = S.parse_csv(_csv("2026-03-01,A,-10.00,90.00",
                              "2026-03-02,B,-20.00,70.00"))
    parsed["opening_balance"] = "100.00"
    parsed["closing_balance"] = "20.00"       # a -50.00 row was never exported
    assert S.check_balance_walk(parsed).ok is True
    check = S.check_rows_sum_to_declared_total(parsed)
    assert check.ok is False
    assert check.gap == 5000


def test_a_statement_declaring_nothing_is_unchecked():
    parsed = S.parse_csv(_csv("2026-03-01,A,-10.00,90.00"))
    assert S.check_rows_sum_to_declared_total(parsed).ok is None


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------

def test_a_broken_statement_is_not_usable():
    parsed = S.parse_csv(_csv("2026-03-01,A,-10.00,90.00",
                              "2026-03-03,C,5.00,75.00"))
    result = S.accept(parsed)
    assert result["usable"] is False
    assert result["problems"]


def test_a_plain_csv_is_usable_but_never_claims_to_be_verified_complete():
    """
    Neither a running balance nor a declared total. Nothing here can know
    whether it is whole, and saying "verified" would be exactly the lie this
    module exists to prevent.
    """
    parsed = S.parse_csv(_csv("2026-03-01,A,-10.00", header="Date,Description,Amount"))
    result = S.accept(parsed)
    assert result["usable"] is True
    assert result["verified_complete"] is False


def test_a_walked_statement_is_verified_complete():
    parsed = S.parse_csv(_csv("2026-03-01,A,-10.00,90.00",
                              "2026-03-02,B,-20.00,70.00"))
    assert S.accept(parsed)["verified_complete"] is True


# --------------------------------------------------------------------------
# What 33 real bank exports found
# --------------------------------------------------------------------------
#
# Fixtures from open-source importers — Capital One, Schwab, N26 France, GLS
# Bank, ING España, Outbank, Mint, ANZ, Nubank. None of the formats below was
# invented here, which is the point: the 22-receipt corpus taught that a corpus
# written by the parser's own author measures agreement, not accuracy.

def test_a_semicolon_separated_export_is_read():
    """
    The European convention, and it is the European convention *because* the
    comma is the decimal mark there — the same population this module already
    goes to real trouble to read money for. `csv.DictReader` defaults to a
    comma, so every one of those files arrived as a single enormous column and
    was refused for having no amount in it. Reading their decimal separator
    and not their column separator was half a job done twice.
    """
    text = ("Datum;Beschreibung;Betrag;Kontostand\n"
            "2026-01-05;Kaffee;-4,20;95,80\n"
            "2026-01-06;Buch;-10,00;85,80\n")
    statement = S.parse_csv(text)
    assert len(statement["lines"]) == 2
    assert int(statement["lines"][0]["amount"]) == -420
    assert int(statement["lines"][0]["balance"]) == 9580


def test_a_column_named_for_its_currency_is_still_the_amount():
    """
    N26 exports `"Amount (EUR)"`, which normalised to `amount eur` and matched
    nothing — a whole bank's exports refused for having said which currency
    they were in.
    """
    text = ('"Booking Date","Partner Name","Amount (EUR)"\n'
            '2026-01-05,"Kaffee",-4.20\n'
            '2026-01-06,"Buch",-10.00\n')
    statement = S.parse_csv(text)
    assert len(statement["lines"]) == 2
    assert int(statement["lines"][0]["amount"]) == -420


def test_a_qualifier_does_not_turn_an_unrelated_column_into_the_amount():
    """The header is tried whole first, so this stays what it says it is."""
    assert S._column_map(["Date", "Amount", "Amount (Original)"])["amount"] == "Amount"


def test_blank_lines_above_the_header_are_skipped():
    """
    Mint's own sample opens with three of them. `csv.DictReader` took the first
    blank line as the header and produced rows keyed on None, which surfaced as
    "no amount column found" on a file whose header plainly says Amount.
    """
    text = "\n\n\nDate,Description,Amount\n2026-01-05,Kaffee,-4.20\n"
    assert len(S.parse_csv(text)["lines"]) == 1


def test_a_preamble_above_the_header_is_skipped():
    """Real exports open with an account number and a period."""
    text = ("Account,12345678\nPeriod,January 2026\n\n"
            "Date,Description,Amount\n2026-01-05,Kaffee,-4.20\n")
    assert len(S.parse_csv(text)["lines"]) == 1


def test_a_file_with_no_amount_column_still_says_so():
    """
    The header search must not invent one. A file that genuinely has no money
    column should get the original message naming what was looked for, not a
    complaint about a header this picked out of the data.
    """
    with pytest.raises(S.StatementError) as raised:
        S.parse_csv("Name,Note\nAda,hello\nGrace,hi\n")
    assert "no amount column" in str(raised.value)


def test_rows_out_of_date_order_leave_the_balance_walk_unrun_not_failed():
    """
    A false alarm found on a real ING España export, and the worst kind this
    module can produce.

    Its rows arrive in no date order, so the running balance is not a chain.
    The walk broke on the first pair and reported "a row is missing here" —
    false — and because a failed completeness check suppresses every finding,
    the whole audit went silent on a complete file.

    Unrun, not failed. Sorting first would invent an order the bank never
    stated, and rows sharing a date have none to recover.
    """
    statement = {"lines": [
        {"row": 1, "date": "2026-03-24", "amount": Cents(283), "balance": Cents(171990)},
        {"row": 2, "date": "2026-04-08", "amount": Cents(269), "balance": Cents(244731)},
        {"row": 3, "date": "2026-01-31", "amount": Cents(137), "balance": Cents(31888)},
    ]}
    check = S.check_balance_walk(statement)
    assert check.ok is None
    assert "not in date order" in check.detail


def test_rows_in_date_order_are_still_walked():
    """The guard must not switch the check off for ordinary files."""
    statement = {"lines": [
        {"row": 1, "date": "2026-01-05", "amount": Cents(-420), "balance": Cents(9580)},
        {"row": 2, "date": "2026-01-06", "amount": Cents(-1000), "balance": Cents(7580)},
    ]}
    assert S.check_balance_walk(statement).ok is False


def test_an_order_export_is_not_a_bank_statement():
    """
    Amazon's order history has a total, a tax and a date, and is not a
    statement. Reading it as one would produce a page of findings about
    somebody's shopping.
    """
    with pytest.raises(S.StatementError):
        S.parse_csv("order id,order url,items,to,date,total,shipping,tax\n"
                    "123,http://x,book,me,2026-01-05,10.00,0.00,1.00\n")
