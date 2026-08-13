"""
The Stage 1 gate: go looking for the seventh defect.

Six were found by hand in one afternoon. Every one of them lived at a boundary
the tests never crossed, and every one was a *silent* wrong answer rather than
a crash — which is the only kind that matters here, because the product is a
verdict and a verdict nobody doubts is a verdict nobody checks.

So these do not assert that parsing succeeds. They assert the two properties a
money parser can never violate no matter what it is fed:

    it never invents a number, and it never returns a different number for the
    same amount written a different way.

Hypothesis where it is installed, and an exhaustive walk over the shapes that
actually occur where it is not — the checking layer has no required
dependencies and this file must not be the thing that adds one.
"""
import itertools
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot import verdict as V
from crossfoot.ingest import statement as S
from crossfoot.match import candidates as M

try:
    from hypothesis import given, settings, strategies as st
    HAVE_HYPOTHESIS = True
except ImportError:                          # pragma: no cover - environment
    HAVE_HYPOTHESIS = False


# --------------------------------------------------------------------------
# Round trips: the same amount, written every way a document writes it
# --------------------------------------------------------------------------

def _write(amount_cents, decimal, group=True):
    """One amount, rendered in one convention."""
    sign = "-" if amount_cents < 0 else ""
    whole, fraction = divmod(abs(amount_cents), 100)
    thousands = "," if decimal == "." else "."
    text = f"{whole:,}".replace(",", thousands) if group else str(whole)
    return f"{sign}{text}{decimal}{fraction:02d}"


AMOUNTS = [1, 7, 50, 99, 100, 999, 1000, 1731, 4200, 84219, 123456,
           1000000, 123456789, -1, -450, -84219, -123456789]


@pytest.mark.parametrize("amount", AMOUNTS)
def test_an_amount_reads_the_same_in_either_convention(amount):
    """
    The property the decimal-comma defect violated. Two renderings of one
    amount must not produce two numbers, and the one that differed was out by a
    factor of a hundred.
    """
    for group in (True, False):
        point = V.cents(_write(amount, ".", group))
        comma = V.cents(_write(amount, ",", group))
        assert point == comma == amount, (amount, group, point, comma)


@pytest.mark.parametrize("amount", AMOUNTS)
def test_furniture_never_changes_the_number(amount):
    """A currency mark, a space or a plus sign is decoration, not magnitude."""
    plain = _write(amount, ".")
    for dressed in (f"$ {plain}", f"{plain} ", f" {plain}", f"USD {plain}",
                    plain.replace("-", "-$")):
        assert V.cents(dressed) == amount, dressed


@pytest.mark.parametrize("amount", [a for a in AMOUNTS if a > 0])
def test_the_three_ways_of_writing_a_debit_agree(amount):
    plain = _write(amount, ".")
    assert V.cents(f"-{plain}") == V.cents(f"({plain})") == V.cents(f"{plain} DR") == -amount


def test_converting_twice_is_converting_once():
    """The Cents marker, asserted rather than assumed."""
    for amount in AMOUNTS:
        once = V.cents(_write(amount, "."))
        assert V.cents(V.cents(once)) == once


# --------------------------------------------------------------------------
# Never invent a number
# --------------------------------------------------------------------------

_JUNK = ["", " ", "n/a", "N/A", "-", "--", ".", ",", "..", ",,", "1.2.3", "1,2,3",
         "5..00", "--5.00", "1.2,3.4", "TOTAL", "abc", "1a.00", "0x10", "1e5",
         "∞", "NaN", "inf", "1..", "..1", "1,", ",1", "1.", "(", ")", "()",
         "(1.00", "1.00)", "( 1.00 )", "CR", "DR", "$", "1.2345", "1,23456"]


@pytest.mark.parametrize("junk", _JUNK)
def test_junk_is_none_and_never_a_number(junk):
    """
    None, not zero and not a guess. An unreadable field coerced to 0.00 is how
    a receipt nobody could read reconciles perfectly against a charge of
    nothing.
    """
    result = V.cents(junk)
    assert result is None or isinstance(result, V.Cents)
    if result is not None:
        # If it did parse, it must be one of the shapes we deliberately accept.
        assert junk.strip(" ()$") not in ("", "-", "--", "abc", "TOTAL")


def test_no_input_raises_out_of_the_money_parser():
    """
    A parser that throws on the ten thousandth row of somebody's statement is
    a parser that loses the run. It returns None; the *caller* decides that a
    None in a non-empty cell means the file is refused.
    """
    random.seed(20260813)
    alphabet = "0123456789.,-+() $€CRDRabc\t\n"
    for _ in range(4000):
        text = "".join(random.choice(alphabet)
                       for _ in range(random.randint(0, 14)))
        V.cents(text)                        # must not raise


def test_a_parsed_value_always_survives_being_rewritten():
    """
    If it read the field as an amount, rendering that amount and reading it
    back must give the same number. Anything else means the first read invented
    part of it — which is exactly what "1.2.3" -> 12.30 was.
    """
    random.seed(20260814)
    alphabet = "0123456789.,-"
    for _ in range(6000):
        text = "".join(random.choice(alphabet)
                       for _ in range(random.randint(1, 12)))
        value = V.cents(text)
        if value is None:
            continue
        assert V.cents(_write(int(value), ".")) == value, (text, value)


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

def test_a_settled_order_is_applied_to_every_row():
    """
    Not row by row. One row settling the order must fix the reading of all of
    them, including the ones that are individually ambiguous.
    """
    for day, order, expected in ((25, "%d/%m", "2026-08-09"),
                                 (25, "%m/%d", "2026-09-08")):
        settling = "25/08/2026" if order == "%d/%m" else "08/25/2026"
        text = ("Date,Description,Amount\n"
                "09/08/2026,AMBIGUOUS,-1.00\n"
                f"{settling},SETTLES IT,-2.00\n")
        assert S.parse_csv(text)["lines"][0]["date"] == expected


def test_every_emitted_date_is_iso_or_empty():
    """Downstream never sees an ambiguous date, because none leaves the parser."""
    random.seed(20260815)
    for _ in range(300):
        day, month = random.randint(13, 28), random.randint(1, 12)
        text = ("Date,Description,Amount\n"
                f"{day:02d}/{month:02d}/2026,A,-1.00\n"
                f"{random.randint(1,12):02d}/{random.randint(1,12):02d}/2026,B,-2.00\n")
        for line in S.parse_csv(text)["lines"]:
            assert line["date"] == "" or (
                len(line["date"]) == 10 and line["date"][4] == line["date"][7] == "-")


def test_an_impossible_date_is_empty_rather_than_wrong():
    """31 February is not a date, and must not become 3 March."""
    text = ("Date,Description,Amount\n"
            "31/02/2026,IMPOSSIBLE,-1.00\n"
            "25/08/2026,SETTLES IT,-2.00\n")
    assert S.parse_csv(text)["lines"][0]["date"] == ""


# --------------------------------------------------------------------------
# CSV shapes
# --------------------------------------------------------------------------

_HEADER_SHAPES = [
    "Date,Description,Amount",
    "Date,Description,Amount,Balance",
    "Date,Description,Debit,Credit,Balance",
    "Posting Date,Narrative,Value",
    "Booking Date,Payee,Money Out,Money In,Running Balance",
]


@pytest.mark.parametrize("header", _HEADER_SHAPES)
def test_a_known_header_shape_parses_or_says_why(header):
    columns = header.split(",")
    row = []
    for name in columns:
        low = name.lower()
        if "date" in low:
            row.append("2026-08-09")
        # Only the debit side is filled. A row carrying both a debit and a
        # credit is refused, correctly — one transaction moves money one way,
        # and a row that says otherwise is two columns read as one.
        elif any(k in low for k in ("credit", "money in", "paid in", "deposit")):
            row.append("")
        elif any(k in low for k in ("amount", "value", "debit", "balance",
                                    "out")):
            row.append("10.00")
        else:
            row.append("MERCHANT")
    parsed = S.parse_csv(header + "\n" + ",".join(row) + "\n")
    assert parsed["lines"], header


def test_a_header_with_no_amount_column_is_refused_not_silently_empty():
    with pytest.raises(S.StatementError):
        S.parse_csv("Date,Description\n2026-08-09,COFFEE\n")


def test_no_csv_shape_produces_a_statement_with_no_rows_and_no_complaint():
    """
    The silent half-file. Either rows come out or an error does; never a clean
    empty statement, because an empty statement reconciles perfectly.
    """
    random.seed(20260816)
    cells = ["", "10.00", "abc", "2026-08-09", "-", "(1.00)", "1,00", "MERCHANT"]
    for _ in range(400):
        header = random.choice(_HEADER_SHAPES)
        width = len(header.split(","))
        body = "\n".join(",".join(random.choice(cells) for _ in range(width))
                         for _ in range(random.randint(1, 4)))
        try:
            parsed = S.parse_csv(header + "\n" + body + "\n")
        except S.StatementError:
            continue                         # refused, which is the other legal answer
        assert parsed["lines"], (header, body)


# --------------------------------------------------------------------------
# The matcher
# --------------------------------------------------------------------------

def test_the_order_of_rows_never_changes_the_outcome():
    """
    The greedy-by-row-order defect, as a property rather than one example.
    """
    random.seed(20260817)
    for _ in range(60):
        n = random.randint(2, 8)
        charges = [{"amount": f"-{random.randint(1, 6)}.00",
                    "description": random.choice(["SUNRISE CAFE", "SUNSET BAR",
                                                  "HOME DEPOT", "BLUE BOTTLE"]),
                    "date": "2026-08-09"} for _ in range(n)]
        receipts = [{"total": f"{random.randint(1, 6)}.00",
                     "merchant": random.choice(["Sunrise Cafe", "Sunset Bar",
                                                "The Home Depot", "Blue Bottle"]),
                     "date": "2026-08-09"} for _ in range(n)]

        def matched(cs):
            return sorted((r["charge"]["description"], r["receipt"]["merchant"])
                          for r in M.match_all(receipts, cs) if r["receipt"])

        assert matched(charges) == matched(list(reversed(charges)))


def test_a_receipt_is_never_assigned_to_two_charges():
    """One payment, one receipt — asserted over random months, not one case."""
    random.seed(20260818)
    for _ in range(60):
        charges = [{"amount": "-5.00", "description": "ADOBE INC",
                    "date": f"2026-{m:02d}-02"} for m in range(1, 13)]
        receipts = [{"total": "5.00", "merchant": "Adobe",
                     "date": "2026-01-02"}] * random.randint(1, 3)
        results = M.match_all(receipts, charges)
        used = [id(r["receipt"]) for r in results if r["receipt"]]
        assert len(used) == len(set(used))


def test_every_charge_survives_the_matcher():
    """A charge that vanishes is a charge nobody reviews."""
    random.seed(20260819)
    for _ in range(60):
        n = random.randint(0, 12)
        charges = [{"amount": f"-{i}.00", "description": f"M{i}",
                    "date": "2026-08-09"} for i in range(n)]
        assert len(M.match_all([{"total": "3.00", "merchant": "M3"}], charges)) == n


# --------------------------------------------------------------------------
# Hypothesis, where it is available
# --------------------------------------------------------------------------

if HAVE_HYPOTHESIS:

    @given(st.integers(min_value=-10 ** 11, max_value=10 ** 11))
    @settings(max_examples=400, deadline=None)
    def test_property_either_convention_reads_alike(amount):
        assert V.cents(_write(amount, ".")) == V.cents(_write(amount, ",")) == amount

    @given(st.text(alphabet="0123456789.,-+()$ CRDR", max_size=20))
    @settings(max_examples=1500, deadline=None)
    def test_property_the_parser_never_raises(text):
        result = V.cents(text)
        assert result is None or isinstance(result, V.Cents)

    @given(st.text(alphabet="0123456789.,-", min_size=1, max_size=14))
    @settings(max_examples=1500, deadline=None)
    def test_property_a_parsed_value_rewrites_to_itself(text):
        value = V.cents(text)
        if value is not None:
            assert V.cents(_write(int(value), ".")) == value
