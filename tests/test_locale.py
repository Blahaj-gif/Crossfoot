"""
Stage 1 — the defects the audit found, each with the input that produced it.

Every test here is a bug that shipped. The two at the top are the same
hundredfold error at two different boundaries, which is the lesson: finding a
class of bug and fixing one instance of it is not fixing the class.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot import verdict as V
from crossfoot.ingest import statement as S


# --------------------------------------------------------------------------
# Money, which is written two ways
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("17.31", 1731),                # the point convention
    ("17,31", 1731),                # the comma convention — was read as $1,731
    ("1,234.56", 123456),
    ("1.234,56", 123456),
    ("1.234.567,89", 123456789),
    ("1,234,567.89", 123456789),
    ("1,234", 123400),              # three digits after: a thousands separator
    ("1.234", 123400),
    ("1234", 123400),
    ("1.5", 150),
    (".50", 50),
])
def test_both_conventions_read_to_the_same_cents(raw, expected):
    assert V.cents(raw) == expected


def test_the_defect_that_started_this():
    """
    An ordinary European receipt total. The old parser stripped every comma and
    read what was left, so this was $1,731.00 — silently, and then reconciled
    confidently against.
    """
    assert V.cents("17,31") == 1731


def test_the_later_separator_is_the_decimal_point():
    """
    The one rule that needs no locale at all: whichever of the two comes last
    is the decimal point, and that settles every value carrying both.
    """
    assert V.cents("1,234.56") == V.cents("1.234,56") == 123456


def test_three_digits_after_the_separator_means_thousands():
    """Money is not written to three decimal places, so this is decidable."""
    assert V.cents("1,234") == V.cents("1.234") == 123400


@pytest.mark.parametrize("raw", ["1.2.3", "1.22.3", "12.34.56", "5..00", "--5.00",
                                 "1,2,3", "12,345,6.78"])
def test_a_value_grouped_unlike_money_is_refused(raw):
    """
    Without a grouping check the whole part was flattened — "1.2.3" became "12"
    plus ".3" and returned 12.30, a number this invented out of a malformed
    field.
    """
    assert V.cents(raw) is None


# --------------------------------------------------------------------------
# Accounting furniture, which used to make a row disappear
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("(42.00)", -4200),             # the commonest export convention for a debit
    ("$-842.19", -84219),
    ("-$842.19", -84219),
    ("842.19 CR", 84219),
    ("842.19 DR", -84219),
    ("USD 1,299.00", 129900),
    ("EUR 1.299,00", 129900),
    ("£12.00", 1200),
    ("  8.00  ", 800),
])
def test_the_shapes_a_real_export_uses(raw, expected):
    assert V.cents(raw) == expected


# --------------------------------------------------------------------------
# The convention is decided once, for the document
# --------------------------------------------------------------------------

def test_a_file_settles_the_one_value_that_cannot_settle_itself():
    """
    "1.005" is one thousand and five to a German bank and three decimal places
    to nobody. A file containing "17.31" says which.
    """
    assert V.detect_decimal_separator(["17.31", "1.005"]) == "."
    assert V.cents("1.005", decimal=".") is None
    assert V.cents("1.005", decimal=",") == 100500


def test_a_value_carrying_both_separators_settles_the_whole_file():
    assert V.detect_decimal_separator(["1.234,56", "99"]) == ","
    assert V.detect_decimal_separator(["1,234.56", "99"]) == "."


def test_a_file_with_no_evidence_decides_nothing():
    """Every value is a whole number with thousands separators. Nothing to settle."""
    assert V.detect_decimal_separator(["1,234", "5,678"]) == ""


def test_a_file_that_mixes_conventions_decides_nothing():
    """
    Rather than averaging. A file with both "1,50" and "2.75" is a file worth
    looking at, and picking one would misread half of it.
    """
    assert V.detect_decimal_separator(["1,50", "2.75"]) == ""


def test_the_statement_parser_applies_one_convention_to_the_whole_file():
    text = ("Date,Description,Amount\n"
            "2026-08-06,CAFE BERLIN,\"-17,31\"\n"
            "2026-08-07,BUCHLADEN,\"-1.234,50\"\n")
    parsed = S.parse_csv(text)
    assert parsed["decimal_separator"] == ","
    assert [l["amount"] for l in parsed["lines"]] == [-1731, -123450]


# --------------------------------------------------------------------------
# Dates, which are written two ways and say so
# --------------------------------------------------------------------------

def test_a_day_above_the_twelfth_settles_the_order():
    assert S.detect_date_order(["09/08/2026", "25/08/2026"]) == S.DAY_FIRST
    assert S.detect_date_order(["09/08/2026", "08/25/2026"]) == S.MONTH_FIRST


def test_iso_dates_settle_nothing_because_they_need_nothing():
    assert S.detect_date_order(["2026-08-09", "2026-08-25"]) is None


def test_a_us_export_is_no_longer_read_as_european():
    """
    The old parser tried day-first before month-first, so every US export moved
    by up to eleven days — far enough to push a receipt out of the posting
    window, or into the wrong one.
    """
    text = ("Date,Description,Amount\n"
            "09/08/2026,COFFEE,-4.50\n"
            "12/25/2026,GIFTS,-80.00\n")     # the 25th settles it: month-first
    assert [l["date"] for l in S.parse_csv(text)["lines"]] == \
        ["2026-09-08", "2026-12-25"]


def test_a_european_export_is_read_as_european():
    text = ("Date,Description,Amount\n"
            "09/08/2026,COFFEE,-4.50\n"
            "25/12/2026,GIFTS,-80.00\n")
    assert [l["date"] for l in S.parse_csv(text)["lines"]] == \
        ["2026-08-09", "2026-12-25"]


def test_a_file_nothing_settles_is_refused_rather_than_guessed():
    """
    Every day is the twelfth or below, so the file genuinely does not say. A
    guess here silently moves every date; the refusal names the fix.
    """
    text = ("Date,Description,Amount\n"
            "09/08/2026,COFFEE,-4.50\n"
            "01/02/2026,BOOKS,-12.00\n")
    with pytest.raises(S.AmbiguousDates, match="day-first or month-first"):
        S.parse_csv(text)


def test_a_file_containing_both_orders_is_refused():
    text = ("Date,Description,Amount\n"
            "25/08/2026,A,-1.00\n"
            "08/25/2026,B,-2.00\n")
    with pytest.raises(S.AmbiguousDates, match="both orders"):
        S.parse_csv(text)


def test_iso_needs_no_settling_at_all():
    text = "Date,Description,Amount\n2026-08-09,COFFEE,-4.50\n"
    assert S.parse_csv(text)["lines"][0]["date"] == "2026-08-09"


# --------------------------------------------------------------------------
# A row that cannot be read
# --------------------------------------------------------------------------

def test_an_unreadable_amount_refuses_the_file_rather_than_dropping_the_row():
    """
    The module's own bug, and the exact failure it was written to prevent: the
    row was skipped as blank and `accept()` still called the file usable.
    """
    text = ("Date,Description,Amount\n"
            "2026-08-01,GOOD,-10.00\n"
            "2026-08-02,BAD,not a number\n")
    with pytest.raises(S.StatementError, match="row 2"):
        S.parse_csv(text)


def test_accounting_parentheses_are_read_rather_than_refused():
    text = ("Date,Description,Amount\n"
            "2026-08-01,GOOD,-10.00\n"
            "2026-08-02,PARENS,(42.00)\n")
    assert [l["amount"] for l in S.parse_csv(text)["lines"]] == [-1000, -4200]


def test_a_genuinely_empty_cell_is_still_a_blank_line():
    """The distinction the refusal rests on: absent is not the same as unreadable."""
    text = ("Date,Description,Amount\n"
            "2026-08-01,GOOD,-10.00\n"
            "2026-08-02,BLANK,\n")
    assert len(S.parse_csv(text)["lines"]) == 1


def test_an_unreadable_balance_is_refused_too():
    """It is the input to the completeness check that everything else rests on."""
    text = ("Date,Description,Amount,Balance\n"
            "2026-08-01,GOOD,-10.00,90.00\n"
            "2026-08-02,GOOD,-10.00,eighty\n")
    with pytest.raises(S.StatementError, match="balance"):
        S.parse_csv(text)


# --------------------------------------------------------------------------
# Currency, which used to be read and ignored
# --------------------------------------------------------------------------

def test_two_currencies_are_not_compared():
    """
    Reading the field and ignoring it was worse than not reading it, because it
    looked handled. There is no comparison to make without a rate.
    """
    check = V.check_receipt_matches_the_charge(
        {"total": "17.31", "currency": "EUR"},
        {"amount": "-17.31", "currency": "USD"})
    assert check.ok is None
    assert "EUR" in check.detail and "USD" in check.detail


def test_a_symbol_and_its_code_are_one_currency():
    check = V.check_receipt_matches_the_charge(
        {"total": "17.31", "currency": "$"},
        {"amount": "-17.31", "currency": "USD"})
    assert check.ok is True


def test_a_document_that_names_no_currency_is_not_assumed_into_one():
    check = V.check_receipt_matches_the_charge(
        {"total": "17.31"}, {"amount": "-17.31", "currency": "USD"})
    assert check.ok is True


def test_a_cross_currency_charge_is_unchecked_rather_than_failed():
    """
    Honest, and the important half: it must not be reported as a discrepancy,
    because nothing here established that the amounts disagree.
    """
    result = V.reconcile({"total": "17.31", "currency": "EUR"},
                         {"amount": "-19.02", "currency": "USD"})
    assert result["verdict"] == V.UNCHECKED


def test_the_statement_reports_its_currency_when_it_states_one():
    text = ("Date,Description,Amount\n"
            "2026-08-06,CAFE,-17.31 USD\n")
    assert S.parse_csv(text)["currency"] == "USD"


def test_a_statement_naming_nothing_claims_nothing():
    text = "Date,Description,Amount\n2026-08-06,CAFE,-17.31\n"
    assert S.parse_csv(text)["currency"] is None
