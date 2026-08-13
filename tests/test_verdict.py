"""
The checks, and the failures they exist for.

Written failure-first: every test that asserts a pass is paired with one that
asserts the same check catches the thing it was built to catch. A check nobody
has watched fail is a check nobody knows works.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot import verdict as v


# --------------------------------------------------------------------------
# Reading money
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("19.99", 1999), (19.99, 1999), ("1,299.00", 129900), ("0.01", 1),
    ("-4.50", -450), (12, 1200), ("  8.00  ", 800),
])
def test_money_is_read_as_cents(raw, expected):
    assert v.cents(raw) == expected


def test_a_parsed_float_is_not_read_through_binary():
    """
    19.99 is nineteen ninety-nine, not 19.989999999999998. Upstream parsers
    hand back floats, and `float * 100` is the classic way a cent goes missing.
    """
    assert v.cents(19.99) == 1999
    assert v.cents(0.07) == 7
    assert v.cents(1234.56) == 123456


def test_binary_noise_is_refused_rather_than_rounded():
    """
    0.1 + 0.2 is 0.30000000000000004, which is not a two-decimal money field
    and never came off a receipt. Rounding it here would mean this function
    silently accepts the output of arithmetic done in the wrong type
    somewhere upstream -- and hide it. Nothing in this module produces such a
    value: sums are taken in integer cents precisely so they cannot.
    """
    assert v.cents(0.1 + 0.2) is None


@pytest.mark.parametrize("raw", [None, "", "  ", "n/a", "TOTAL", [], {}, float("nan")])
def test_an_unreadable_field_is_none_and_never_zero(raw):
    """
    A missing total and a total of nothing are different facts. Coercing the
    first to the second is how an unreadable receipt reconciles perfectly
    against a charge of nothing.
    """
    assert v.cents(raw) is None


def test_a_third_of_a_cent_was_never_money():
    assert v.cents("1.005") is None


# --------------------------------------------------------------------------
# Check 1 -- the column against the row
# --------------------------------------------------------------------------

def test_line_items_that_sum_to_the_printed_subtotal_pass():
    r = {"lines": [{"amount": "10.00"}, {"amount": "5.49"}], "subtotal": "15.49"}
    assert v.check_lines_sum_to_subtotal(r).ok is True


def test_a_subtotal_that_disagrees_with_its_own_items_fails():
    """The Home Depot case: the receipt's own arithmetic is wrong."""
    r = {"lines": [{"amount": "791.44"}], "subtotal": "797.44"}
    check = v.check_lines_sum_to_subtotal(r)
    assert check.ok is False
    assert check.gap == -600


def test_per_line_rounding_is_tolerated_and_bounded_by_the_row_count():
    """
    Per-unit prices and VAT-inclusive lines round at each row, so n lines may
    legitimately be n cents out. A check that fires on that is a check people
    learn to click through.
    """
    lines = [{"amount": "3.33"}] * 3          # 9.99
    assert v.check_lines_sum_to_subtotal(
        {"lines": lines, "subtotal": "10.00"}).ok is True
    # Four cents on three lines is past what rounding can explain.
    assert v.check_lines_sum_to_subtotal(
        {"lines": lines, "subtotal": "10.03"}).ok is False


def test_the_allowance_can_never_grow_to_hide_a_magnitude_error():
    """
    The failure this all exists for. A hundredfold misread still looks like a
    price; it does not survive being added up. A percentage tolerance is exactly
    the shape that would let it through, which is why there isn't one.
    """
    lines = [{"amount": "12.34"}] * 200        # a very long receipt
    check = v.check_lines_sum_to_subtotal({"lines": lines, "subtotal": "24.68"})
    assert check.ok is False


def test_one_unreadable_line_leaves_the_check_unrun_rather_than_passing():
    """
    Summing the lines that happened to parse makes the check easier the worse
    the parse was, which is backwards.
    """
    r = {"lines": [{"amount": "10.00"}, {"amount": "smudged"}], "subtotal": "10.00"}
    assert v.check_lines_sum_to_subtotal(r).ok is None


def test_a_receipt_with_no_subtotal_is_unchecked():
    assert v.check_lines_sum_to_subtotal({"lines": [{"amount": "1.00"}]}).ok is None


# --------------------------------------------------------------------------
# Check 2 -- subtotal builds the total
# --------------------------------------------------------------------------

def test_subtotal_plus_tax_and_tip_reaches_the_printed_total():
    r = {"subtotal": "100.00", "tax": "8.25", "tip": "20.00", "total": "128.25"}
    assert v.check_subtotal_builds_the_total(r).ok is True


def test_a_discount_is_subtracted():
    r = {"subtotal": "50.00", "discount": "5.00", "total": "45.00"}
    assert v.check_subtotal_builds_the_total(r).ok is True


def test_a_total_that_does_not_follow_from_its_parts_fails():
    r = {"subtotal": "100.00", "tax": "8.25", "total": "128.25"}
    check = v.check_subtotal_builds_the_total(r)
    assert check.ok is False
    assert check.gap == -2000        # the tip line was never read


def test_absent_adjustments_are_zero_but_absent_anchors_are_not():
    assert v.check_subtotal_builds_the_total(
        {"subtotal": "10.00", "total": "10.00"}).ok is True
    assert v.check_subtotal_builds_the_total({"total": "10.00"}).ok is None
    assert v.check_subtotal_builds_the_total({"subtotal": "10.00"}).ok is None


def test_a_present_but_unreadable_tax_line_is_unchecked_not_ignored():
    """Skipping it would silently turn a failing receipt into a passing one."""
    r = {"subtotal": "100.00", "tax": "?", "total": "108.25"}
    assert v.check_subtotal_builds_the_total(r).ok is None


# --------------------------------------------------------------------------
# Check 3 -- across the two documents
# --------------------------------------------------------------------------

def test_the_receipt_total_against_what_left_the_account():
    assert v.check_receipt_matches_the_charge(
        {"total": "42.00"}, {"amount": "42.00"}).ok is True
    assert v.check_receipt_matches_the_charge(
        {"total": "42.00"}, {"amount": "42.01"}).ok is False


def test_a_charge_with_no_receipt_is_unchecked():
    check = v.check_receipt_matches_the_charge(None, {"amount": "42.00"})
    assert check.ok is None
    assert "no receipt" in check.detail


def test_this_check_is_exact_because_a_cent_here_is_a_different_charge():
    """
    Rounding lives inside a receipt, not between a receipt and a bank. There is
    no arithmetic between these two numbers, so there is nothing to round.
    """
    assert v.check_receipt_matches_the_charge(
        {"total": "42.00"}, {"amount": "42.01"}).ok is False


# --------------------------------------------------------------------------
# Check 4 -- the statement against itself
# --------------------------------------------------------------------------

def test_a_statements_rows_against_its_declared_period_total():
    s = {"lines": [{"amount": "10.00"}, {"amount": "20.00"}], "period_total": "30.00"}
    assert v.check_statement_lines_sum_to_its_total(s).ok is True


def test_a_truncated_export_is_caught_here_or_nowhere():
    """
    The failure that quietly voids every other verdict on the page: rows that
    were never read cannot be reported as unmatched, so a half-read statement
    reconciles beautifully.
    """
    s = {"lines": [{"amount": "10.00"}], "period_total": "30.00"}
    check = v.check_statement_lines_sum_to_its_total(s)
    assert check.ok is False
    assert check.gap == -2000


def test_a_statement_that_declares_no_total_is_unchecked():
    assert v.check_statement_lines_sum_to_its_total(
        {"lines": [{"amount": "10.00"}]}).ok is None


# --------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------

def test_a_clean_receipt_against_a_matching_charge_reconciles():
    receipt = {"lines": [{"amount": "100.00"}], "subtotal": "100.00",
               "tax": "8.25", "total": "108.25"}
    assert v.reconcile(receipt, {"amount": "108.25"})["verdict"] == v.RECONCILED


def test_one_failed_check_is_a_failure_no_matter_how_many_passed():
    """Not a score. Two out of three is not a pass."""
    receipt = {"lines": [{"amount": "791.44"}], "subtotal": "797.44",
               "tax": "44.75", "total": "842.19"}
    result = v.reconcile(receipt, {"amount": "842.19"})
    assert result["verdict"] == v.DISCREPANT
    assert len(result["failed"]) == 1
    assert any(c.ok for c in result["checks"])


def test_no_evidence_is_unchecked_and_never_reconciled():
    """
    The whole argument. A verdict that improves as the evidence thins is not a
    verdict, and this is the state every other tool throws away.
    """
    result = v.reconcile(None, {"amount": "263.88"})
    assert result["verdict"] == v.UNCHECKED
    assert result["failed"] == []


def test_the_verdict_carries_what_is_at_risk_so_the_queue_can_be_ordered_by_it():
    assert v.reconcile(None, {"amount": "1,284.11"})["at_risk"] == 128411


def test_a_charge_with_no_receipt_says_so_rather_than_naming_a_missing_subtotal():
    """
    With no receipt every check is unrun, and the first in the list complains
    about line items — true, and a baffling thing to read about a charge that
    has no document at all. The absence of the receipt outranks anything
    missing inside it.
    """
    why = v.reconcile(None, {"amount": "263.88"})["why"]
    assert "no receipt" in why
    assert "subtotal" not in why


def test_the_reason_names_the_disagreement_rather_than_the_verdict():
    """
    "Does not reconcile" tells a person nothing they can act on. Both numbers,
    side by side, tells them everything.
    """
    receipt = {"lines": [{"amount": "791.44"}], "subtotal": "797.44"}
    why = v.reconcile(receipt, {"amount": "842.19"})["why"]
    assert "791.44" in why and "797.44" in why
