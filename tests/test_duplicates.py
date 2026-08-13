"""
Being billed twice — the one finding here that can hand somebody money back.

It needs no receipt, so it works on the first run before anyone has
photographed anything. That makes it the check most likely to be the reason a
person keeps the tool, and the one most likely to lose them if it cries wolf:
a section that flags a subscription twelve times a year is a section people
learn to skim past, and a skimmed section catches nothing.

So the tests come in pairs — what it must catch, and what it must not.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot import pipeline as P
from crossfoot.export import rows as E
from crossfoot.ingest import duplicates as DUP
from crossfoot.ingest import statement as S
from crossfoot.review import queue as Q


def _lines(*rows, header="Date,Description,Amount,Balance"):
    return S.parse_csv("\n".join([header, *rows]) + "\n")["lines"]


# --------------------------------------------------------------------------
# What it must catch
# --------------------------------------------------------------------------

def test_the_same_charge_twice_on_the_same_day():
    """The classic double-tap: a terminal that timed out and was run again."""
    found = DUP.suspects(_lines("2026-08-14,HOME DEPOT #4471,-842.19,133.42",
                                "2026-08-14,HOME DEPOT #4471,-842.19,-708.77"))
    assert len(found) == 1
    assert found[0]["amount"] == 84219
    assert found[0]["days_apart"] == 0
    assert "the same day" in found[0]["why"]


def test_a_repeat_the_next_morning():
    found = DUP.suspects(_lines("2026-08-14,CAFE,-12.00,88.00",
                                "2026-08-15,CAFE,-12.00,76.00"))
    assert len(found) == 1 and found[0]["days_apart"] == 1
    assert "1 day apart" in found[0]["why"]


def test_a_truncated_descriptor_still_names_the_same_merchant():
    """
    The bank writes the same shop two ways. Matching on the raw string would
    miss precisely the pairs worth catching.
    """
    found = DUP.suspects(_lines("2026-08-14,SQ *BLUE BOTTLE 0042,-4.20,88.00",
                                "2026-08-14,SQ *BLUE BOTTLE COFFEE,-4.20,83.80"))
    assert len(found) == 1


def test_the_largest_pair_comes_first():
    """
    Two £4.20 coffees and two £842 hardware charges are the same shape and not
    remotely the same problem.
    """
    found = DUP.suspects(_lines("2026-08-06,CAFE,-4.20,95.80",
                                "2026-08-06,CAFE,-4.20,91.60",
                                "2026-08-14,HOME DEPOT,-842.19,-750.59",
                                "2026-08-14,HOME DEPOT,-842.19,-1592.78"))
    assert [s["amount"] for s in found] == [84219, 420]


def test_three_identical_charges_in_a_row_produce_two_pairs():
    found = DUP.suspects(_lines("2026-08-14,IKEA,-10.00,90.00",
                                "2026-08-14,IKEA,-10.00,80.00",
                                "2026-08-14,IKEA,-10.00,70.00"))
    assert len(found) == 2


# --------------------------------------------------------------------------
# What it must not catch
# --------------------------------------------------------------------------

def test_a_monthly_subscription_is_not_a_double_bill():
    """
    Flagging twelve of these a year is how somebody learns to skim past this
    section, and a skimmed section catches nothing.
    """
    rows = [f"2026-{m:02d}-03,NETFLIX.COM,-15.99,{100 - m * 16}.00"
            for m in range(1, 13)]
    assert DUP.suspects(_lines(*rows)) == []


def test_a_subscription_whose_billing_date_drifts_is_still_a_subscription():
    """Month lengths and weekends move the date; the tolerance covers that."""
    rows = ["2026-01-03,SPOTIFY,-11.99,88.00",
            "2026-02-01,SPOTIFY,-11.99,76.00",
            "2026-03-05,SPOTIFY,-11.99,64.00",
            "2026-04-02,SPOTIFY,-11.99,52.00"]
    assert DUP.suspects(_lines(*rows)) == []


def test_two_visits_a_fortnight_apart_are_two_visits():
    assert DUP.suspects(_lines("2026-08-01,CAFE,-12.00,88.00",
                               "2026-08-15,CAFE,-12.00,76.00")) == []


def test_a_different_amount_is_a_different_charge():
    assert DUP.suspects(_lines("2026-08-14,IKEA,-10.00,90.00",
                               "2026-08-14,IKEA,-10.01,79.99")) == []


def test_a_different_merchant_is_a_different_charge():
    assert DUP.suspects(_lines("2026-08-14,SUNRISE CAFE,-10.00,90.00",
                               "2026-08-14,SUNSET BAR,-10.00,80.00")) == []


def test_money_in_is_never_a_double_bill():
    """You were not charged twice; you were paid twice, which is not this."""
    assert DUP.suspects(_lines("2026-08-14,REFUND,10.00,110.00",
                               "2026-08-14,REFUND,10.00,120.00")) == []


def test_a_row_with_no_readable_merchant_is_not_paired_on_amount_alone():
    """Every descriptor stripped to nothing would otherwise match every other."""
    found = DUP.suspects(_lines("2026-08-14,POS PURCHASE CARD 4471,-10.00,90.00",
                                "2026-08-14,POS PURCHASE CARD 9930,-10.00,80.00"))
    assert found == []


# --------------------------------------------------------------------------
# Nuance
# --------------------------------------------------------------------------

def test_a_refund_afterwards_is_reported_and_not_alarming():
    """
    It was already put right. Still worth showing — it says the merchant does
    this — but the money is not at risk any more.
    """
    found = DUP.suspects(_lines("2026-08-14,IKEA,-50.00,50.00",
                                "2026-08-14,IKEA,-50.00,0.00",
                                "2026-08-20,IKEA,50.00,50.00"))
    assert len(found) == 1
    assert found[0]["refunded_by"] is not None
    assert "already put right" in found[0]["why"]
    assert DUP.at_risk(found) == 0


def test_what_is_at_risk_is_the_second_charge_not_both():
    """
    Counting both doubles what is actually at stake, and a number a person can
    see is exaggerated is a number that costs you the ones beside it.
    """
    found = DUP.suspects(_lines("2026-08-14,IKEA,-50.00,50.00",
                                "2026-08-14,IKEA,-50.00,0.00"))
    assert DUP.at_risk(found) == 5000


def test_undated_rows_are_reported_as_unpairable_rather_than_ignored():
    """
    Without a date there is no "close together". Silence about rows that might
    genuinely be duplicates is the worse answer.
    """
    lines = [{"row": 1, "date": "", "description": "IKEA", "amount": -1000},
             {"row": 2, "date": "", "description": "IKEA", "amount": -1000}]
    found = DUP.suspects(lines)
    assert len(found) == 1
    assert found[0]["days_apart"] is None
    assert "no dates" in found[0]["why"]


# --------------------------------------------------------------------------
# How it reaches the person
# --------------------------------------------------------------------------

@pytest.fixture()
def doubled(tmp_path):
    (tmp_path / "bank.csv").write_text(
        "Date,Description,Amount,Balance\n"
        "2026-08-03,NETFLIX.COM,-15.99,984.01\n"
        "2026-08-06,SQ *BLUE BOTTLE 0042,-4.20,979.81\n"
        "2026-08-06,SQ *BLUE BOTTLE 0042,-4.20,975.61\n"
        "2026-08-14,HOME DEPOT #4471,-842.19,133.42\n"
        "2026-08-14,HOME DEPOT #4471,-842.19,-708.77\n"
        "2026-09-03,NETFLIX.COM,-15.99,-724.76\n"
        "2026-10-03,NETFLIX.COM,-15.99,-740.75\n", encoding="utf-8")
    return P.load(str(tmp_path / "bank.csv"), str(tmp_path / "none"))


def test_only_the_second_charge_of_a_pair_is_flagged(doubled):
    """
    The first is an ordinary purchase that happens to have been followed by an
    identical one. Flagging both doubles the apparent problem — and the first
    version did exactly that, because two identical charges are identical and a
    value-based key cannot tell them apart.
    """
    flagged = [i for i in doubled["built"]["needs_you"] if i["state"] == Q.DUPLICATE]
    assert len(flagged) == 2
    assert sorted(i["charge"]["row"] for i in flagged) == [3, 5]


def test_a_flagged_row_says_which_charge_it_repeats(doubled):
    flagged = [i for i in doubled["built"]["needs_you"] if i["state"] == Q.DUPLICATE][0]
    assert flagged["duplicate_of"]["row"] == 4


def test_duplicates_outrank_everything_else_in_the_queue(doubled):
    """It is the only finding that can give somebody money back."""
    assert doubled["built"]["needs_you"][0]["state"] == Q.DUPLICATE


def test_the_headline_leads_with_being_billed_twice(doubled):
    """
    "You may have paid this twice" is a different sentence from "your paperwork
    is incomplete", and burying it behind a tally is how it gets skimmed.
    """
    assert doubled["built"]["headline"].startswith("2 possibly billed twice")


def test_the_export_still_has_exactly_one_row_per_statement_line(doubled):
    """
    The bug this replaced: duplicates were appended as extra queue items, so
    the export wrote the charge twice and importing it would have created a
    duplicate transaction in somebody's ledger. From the duplicate detector.
    """
    built = doubled["built"]
    rows = E.rows_for(built["needs_you"] + built["filed_items"])
    assert len(rows) == len(doubled["parsed"]["lines"]) == 7


def test_the_verdict_travels_into_the_ledger(doubled):
    built = doubled["built"]
    rows = E.rows_for(built["needs_you"] + built["filed_items"])
    flagged = [r for r in rows if r["verdict"] == E.DUPLICATE]
    assert len(flagged) == 2
    assert all("two charges of" in r["why"] for r in flagged)


def test_a_subscription_reaches_the_ledger_unflagged(doubled):
    built = doubled["built"]
    rows = E.rows_for(built["needs_you"] + built["filed_items"])
    netflix = [r for r in rows if "NETFLIX" in r["description"]]
    assert len(netflix) == 3
    assert all(r["verdict"] != E.DUPLICATE for r in netflix)


def test_it_works_with_no_receipts_at_all(doubled):
    """
    The whole point. This is what a person sees on their first run, before they
    have photographed anything and whether or not they ever do.
    """
    assert doubled["receipts"] == []
    assert len(doubled["duplicates"]) == 2
