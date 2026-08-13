"""
Step 3 — matching, and the tie it refuses to break.

Fuzzy on the name, exact on the cents. And when two receipts fit equally well,
both come back: picking one produces a ledger that reads as reconciled and is
wrong in a way no later check can find, which is strictly worse than a gap.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot.match import candidates as M


def receipt(total, merchant, date="2026-08-09"):
    return {"total": total, "merchant": merchant, "date": date}


def charge(amount, description, date="2026-08-09"):
    """
    Money *out*, which is what a receipt reconciles. The minus is the point:
    a statement writes a payment as negative, and a credit is a different
    animal entirely (see the money-in tests below).
    """
    text = str(amount)
    return {"amount": text if text.startswith("-") else f"-{text}",
            "description": description, "date": date}


# --------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------

def test_payment_network_furniture_is_stripped():
    assert M.normalise_merchant("SQ *BLUE BOTTLE 0042 SAN FRANCISCO CA") \
        .startswith("blue bottle")
    assert "visa" not in M.normalise_merchant("VISA PURCHASE BLUE BOTTLE")


def test_two_descriptors_that_share_only_furniture_do_not_match():
    """
    "POS PURCHASE CARD 4471" and "POS PURCHASE CARD 9930" are unrelated
    charges, and every word they share is noise.
    """
    assert M.name_similarity("POS PURCHASE CARD 4471",
                             "POS PURCHASE CARD 9930") < M.NAME_FLOOR


def test_a_truncated_descriptor_reaches_the_full_name():
    """A descriptor is a prefix of the real name far more often than a near-miss of it."""
    assert M.name_similarity("SQ *BLUE BOTTLE 0042",
                             "Blue Bottle Coffee Roasters") >= M.NAME_FLOOR


def test_similarity_is_symmetric():
    a, b = "HOME DEPOT #4471", "The Home Depot"
    assert M.name_similarity(a, b) == M.name_similarity(b, a)


# --------------------------------------------------------------------------
# The amount gate
# --------------------------------------------------------------------------

def test_the_amount_is_a_gate_and_not_a_score():
    """
    A receipt whose total is not the charged amount to the cent is not a worse
    candidate. It is not a candidate.
    """
    found = M.candidates([receipt("104.21", "Sunrise Cafe")],
                         charge("104.20", "SUNRISE CAFE"))
    assert found == []


def test_sign_does_not_prevent_a_match():
    """
    A statement debit is negative; a receipt total is not. Neither document is
    wrong about it — they simply do not share a sign convention.
    """
    found = M.candidates([receipt("104.20", "Sunrise Cafe")],
                         {"amount": "-104.20", "description": "SUNRISE CAFE",
                          "date": "2026-08-09"})
    assert len(found) == 1


def test_money_in_is_never_paired_with_a_receipt():
    """
    A receipt reconciles a payment, and a credit is not one. Pairing a $50
    refund with the $50 purchase receipt it reverses would reconcile the two
    documents that most need to stay apart.
    """
    refund = {"amount": "104.20", "description": "SUNRISE CAFE REFUND",
              "date": "2026-08-09"}
    assert M.candidates([receipt("104.20", "Sunrise Cafe")], refund) == []


def test_a_salary_deposit_reaches_the_queue_unchecked_rather_than_matched():
    salary = {"amount": "3000.00", "description": "ACME PAYROLL",
              "date": "2026-08-09"}
    outcome = M.resolve(M.candidates([receipt("3000.00", "Acme")], salary))
    assert outcome["receipt"] is None


def test_a_receipt_outside_the_posting_window_is_excluded():
    found = M.candidates([receipt("50.00", "Cafe", date="2026-07-01")],
                         charge("50.00", "CAFE", date="2026-08-09"))
    assert found == []


def test_the_window_covers_a_normal_posting_delay():
    found = M.candidates([receipt("50.00", "Cafe", date="2026-08-06")],
                         charge("50.00", "CAFE", date="2026-08-09"))
    assert len(found) == 1 and found[0]["days_apart"] == 3


@pytest.mark.parametrize("fmt", ["2026-08-09", "09/08/2026", "20260809"])
def test_common_date_formats_are_understood(fmt):
    found = M.candidates([receipt("50.00", "Cafe", date=fmt)],
                         charge("50.00", "CAFE", date="2026-08-09"))
    assert len(found) == 1


def test_a_missing_date_does_not_exclude_a_candidate():
    """A receipt with no readable date is less useful, not disqualified."""
    found = M.candidates([receipt("50.00", "Cafe", date="")],
                         charge("50.00", "CAFE"))
    assert len(found) == 1 and found[0]["days_apart"] is None


# --------------------------------------------------------------------------
# Resolving
# --------------------------------------------------------------------------

def test_one_clear_candidate_resolves():
    outcome = M.resolve(M.candidates([receipt("842.19", "Home Depot")],
                                     charge("842.19", "HOME DEPOT #4471")))
    assert outcome["receipt"] is not None
    assert "to the cent" in outcome["why"]


def test_two_identical_receipts_stay_two():
    """
    Two coffees at the same cafe for the same amount on the same day is an
    ordinary Saturday. Picking whichever sorted first is not.
    """
    both = [receipt("104.20", "Sunrise Cafe"), receipt("104.20", "Sunrise Cafe")]
    outcome = M.resolve(M.candidates(both, charge("104.20", "SUNRISE CAFE")))
    assert outcome["receipt"] is None
    assert len(outcome["ambiguous"]) == 2


def test_a_close_second_does_not_beat_a_clear_first():
    found = M.candidates(
        [receipt("50.00", "Sunrise Cafe"), receipt("50.00", "Sunset Bar")],
        charge("50.00", "SUNRISE CAFE"))
    assert M.resolve(found)["receipt"]["merchant"] == "Sunrise Cafe"


def test_matching_on_amount_alone_is_not_enough_to_choose():
    """
    Several receipts for the same amount and none of them named anything like
    the charge. That is a coincidence of money, not a match.
    """
    found = M.candidates([receipt("50.00", "Alpha"), receipt("50.00", "Beta")],
                         charge("50.00", "OMEGA HOLDINGS"))
    outcome = M.resolve(found)
    assert outcome["receipt"] is None
    assert "merchant name" in outcome["why"]


def test_nothing_matching_says_so_rather_than_erroring():
    outcome = M.resolve(M.candidates([], charge("50.00", "ANYTHING")))
    assert outcome["receipt"] is None
    assert outcome["ambiguous"] == []


# --------------------------------------------------------------------------
# Across a whole statement
# --------------------------------------------------------------------------

def test_one_receipt_cannot_reconcile_twelve_charges():
    """
    Without withdrawing a used receipt, a subscription's single receipt matches
    every month and eleven of them reconcile against a document that is not
    about them.
    """
    receipts = [receipt("263.88", "Adobe", date="2026-01-02")]
    charges = [charge("263.88", "ADOBE INC", date=f"2026-{m:02d}-02")
               for m in range(1, 13)]
    results = M.match_all(receipts, charges)
    matched = [r for r in results if r["receipt"] is not None]
    assert len(matched) == 1
    assert matched[0]["charge"]["date"] == "2026-01-02"


def test_every_charge_appears_in_the_results_matched_or_not():
    """A charge that vanishes from the results is a charge nobody reviews."""
    charges = [charge("1.00", "A"), charge("2.00", "B"), charge("3.00", "C")]
    assert len(M.match_all([], charges)) == 3


# --------------------------------------------------------------------------
# Found in the audit sweep
# --------------------------------------------------------------------------

def test_assignment_is_by_confidence_not_by_row_order():
    """
    The bug this pins: walking the statement top to bottom let whichever charge
    was listed first take a receipt it barely matched. A $50 Sunset Bar line
    consumed the Sunrise Cafe receipt because it appeared two rows higher, and
    the charge that matched it perfectly got nothing.
    """
    charges = [charge("50.00", "SUNSET BAR"), charge("50.00", "SUNRISE CAFE")]
    receipts = [receipt("50.00", "Sunrise Cafe")]
    results = M.match_all(receipts, charges)
    matched = [r for r in results if r["receipt"] is not None]
    assert len(matched) == 1
    assert matched[0]["charge"]["description"] == "SUNRISE CAFE"


def test_reversing_the_statement_changes_nothing():
    charges = [charge("50.00", "SUNSET BAR"), charge("50.00", "SUNRISE CAFE")]
    receipts = [receipt("50.00", "Sunrise Cafe")]
    forward = M.match_all(receipts, charges)
    backward = M.match_all(receipts, list(reversed(charges)))
    def named(rs):
        return {r["charge"]["description"] for r in rs if r["receipt"]}
    assert named(forward) == named(backward) == {"SUNRISE CAFE"}


def test_a_lone_candidate_named_nothing_like_the_charge_is_refused():
    """
    Amount plus date is not enough when both documents *do* name a merchant and
    the names have nothing in common. That is a coincidence of money.
    """
    outcome = M.resolve(M.candidates([receipt("50.00", "Sunrise Cafe")],
                                     charge("50.00", "SUNSET BAR")))
    assert outcome["receipt"] is None


def test_a_receipt_with_no_name_is_not_failed_on_its_name():
    """
    An absent name is an absence of evidence, not evidence of a mismatch.
    Failing it would send every unnamed receipt to the queue.
    """
    outcome = M.resolve(M.candidates([receipt("50.00", "")],
                                     charge("50.00", "SUNSET BAR")))
    assert outcome["receipt"] is not None


def test_two_short_names_made_of_the_same_letters_are_not_the_same_shop():
    """
    The measurement that forced RATIO_FLOOR. "sunset bar" and "sunrise cafe"
    share no token and no meaning, and scored 0.64 on raw character overlap.
    """
    assert M.name_similarity("SUNSET BAR", "Sunrise Cafe") < M.NAME_FLOOR


def test_a_genuine_near_miss_still_counts():
    """Above the ratio floor is a typo or a truncation, which is real evidence."""
    assert M.name_similarity("SUNRISE CAFE", "Sunrise Caffe") >= M.NAME_FLOOR
