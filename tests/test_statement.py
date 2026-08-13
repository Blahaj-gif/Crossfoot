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
