"""
All four steps, end to end, on one small month.

Written because the unit tests all passed while two modules disagreed about
what an amount *was*. The receipt reader and the statement parser both hand on
integers already counted in cents; `verdict.cents` reads a bare integer as
whole currency units, because that is right for a field read off a document. So
a receipt total of 1731 became $1,731 and every imported charge was inflated a
hundredfold — and every module was individually correct.

A boundary bug is invisible to tests that never cross the boundary. This file
crosses all of them.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot import verdict as V
from crossfoot.ingest import statement as S
from crossfoot.match import candidates as M
from crossfoot.read import receipt as R
from crossfoot.review import decisions as D
from crossfoot.review import queue as Q

STATEMENT = """\
Date,Description,Amount,Balance
2026-08-06,SQ *BLUE BOTTLE 0042,-17.31,982.69
2026-08-09,SUNRISE CAFE SF,-104.20,878.49
2026-08-14,HOME DEPOT #4471,-842.19,36.30
"""

COFFEE = """\
BLUE BOTTLE COFFEE
Latte                    5.50
Croissant                4.25
Drip Coffee              3.75
SUBTOTAL                13.50
TAX                      1.11
TIP                      2.70
TOTAL                   17.31
"""

HARDWARE = """\
THE HOME DEPOT #4471
Lumber                 791.44
SUBTOTAL               797.44
TAX                     44.75
TOTAL                  842.19
"""


def _charges():
    parsed = S.parse_csv(STATEMENT)
    assert S.accept(parsed)["usable"]
    return [{"amount": l["amount"], "description": l["description"],
             "date": l["date"]} for l in parsed["lines"]]


def _receipt(text, merchant, date):
    parsed = R.as_receipt(R.extract(text))
    parsed["merchant"] = merchant
    parsed["date"] = date
    return parsed


# --------------------------------------------------------------------------
# The boundary the unit tests could not see
# --------------------------------------------------------------------------

def test_an_amount_survives_every_hop_without_being_re_converted():
    """The regression. Each module hands the next one a value already counted."""
    charge = _charges()[0]
    assert V.cents(charge["amount"]) == -1731
    assert V.cents(V.cents(V.cents(charge["amount"]))) == -1731

    parsed = _receipt(COFFEE, "Blue Bottle Coffee", "2026-08-06")
    assert V.cents(parsed["total"]) == 1731


def test_a_converted_amount_is_marked_as_converted():
    assert isinstance(V.cents("17.31"), V.Cents)
    assert isinstance(S.parse_csv(STATEMENT)["lines"][0]["amount"], V.Cents)


def test_a_document_field_is_still_read_as_whole_units():
    """The behaviour the marker had to preserve: a receipt's "12" is twelve dollars."""
    assert V.cents(12) == 1200
    assert V.cents("12") == 1200


# --------------------------------------------------------------------------
# The month
# --------------------------------------------------------------------------

def test_a_clean_receipt_reconciles_all_the_way_through():
    matches = M.match_all([_receipt(COFFEE, "Blue Bottle Coffee", "2026-08-06")],
                          _charges())
    built = Q.build(matches)
    assert built["filed"] == 1
    coffee = [m for m in matches if m["receipt"]][0]
    assert coffee["charge"]["description"] == "SQ *BLUE BOTTLE 0042"


def test_a_receipt_whose_own_arithmetic_is_wrong_reaches_the_top_of_the_queue():
    """
    Home Depot prints a subtotal of 797.44 over line items summing to 791.44.
    The total and the charge agree, so nothing else notices.
    """
    matches = M.match_all(
        [_receipt(COFFEE, "Blue Bottle Coffee", "2026-08-06"),
         _receipt(HARDWARE, "The Home Depot", "2026-08-14")],
        _charges())
    built = Q.build(matches)

    top = built["needs_you"][0]
    assert top["state"] == Q.FAILED
    assert top["at_risk"] == -84219
    assert "791.44" in top["why"] and "797.44" in top["why"]


def test_the_charge_with_no_receipt_is_unchecked_and_stays_visible():
    matches = M.match_all([_receipt(COFFEE, "Blue Bottle Coffee", "2026-08-06")],
                          _charges())
    built = Q.build(matches)
    unchecked = [i for i in built["needs_you"] if i["state"] == Q.UNVERIFIED]
    assert {i["charge"]["description"] for i in unchecked} == {
        "SUNRISE CAFE SF", "HOME DEPOT #4471"}
    assert "unchecked" in built["headline"]


def test_the_headline_accounts_for_every_charge():
    """Nothing may fall out of the page between the statement and the queue."""
    charges = _charges()
    built = Q.build(M.match_all(
        [_receipt(COFFEE, "Blue Bottle Coffee", "2026-08-06")], charges))
    assert built["filed"] + len(built["needs_you"]) == len(charges)


def test_a_short_statement_stops_the_pipeline_rather_than_annotating_it():
    """
    Every verdict on a half-read statement is individually correct and the page
    as a whole is a lie.
    """
    short = STATEMENT.replace("2026-08-09,SUNRISE CAFE SF,-104.20,878.49\n", "")
    result = S.accept(S.parse_csv(short))
    assert result["usable"] is False
    assert "missing" in result["problems"][0]


def test_a_human_clears_the_hardware_row_and_it_leaves_the_queue(tmp_path):
    log = str(tmp_path / "decisions.jsonl")
    matches = M.match_all(
        [_receipt(COFFEE, "Blue Bottle Coffee", "2026-08-06"),
         _receipt(HARDWARE, "The Home Depot", "2026-08-14")],
        _charges())
    items = Q.build(matches)["needs_you"]

    D.record(items[0], D.ACCEPT_AS_PRINTED, actor=D.HUMAN,
             note="the merchant's own arithmetic is wrong", path=log)

    left = D.outstanding(items, log)
    assert len(left) == len(items) - 1
    assert all(i["state"] != Q.FAILED for i in left)


def test_nothing_but_a_person_can_empty_the_queue(tmp_path):
    log = str(tmp_path / "decisions.jsonl")
    items = Q.build(M.match_all([], _charges()))["needs_you"]
    for item in items:
        with pytest.raises(D.NotAHumanDecision):
            D.record(item, D.IGNORE, actor="assistant", path=log)
    assert D.outstanding(items, log) == items
