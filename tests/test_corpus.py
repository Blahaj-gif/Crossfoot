"""
The corpus, measured — including the number that actually matters.

Every other test here was written alongside the code it tests, which makes it a
mirror. These are twenty-two receipts typed from the layouts real tills,
restaurants, supermarkets and invoicing systems print, with the expected values
written by *reading the paper* rather than by running the parser and recording
what came out.

The headline is not "how many fields were right". It is the **silent pass
rate**: a receipt read wrongly in a way that still reconciles is the only
genuinely dangerous output this project can produce, because nothing
downstream flags it and the ledger says clean.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot import verdict as V
from crossfoot.read import receipt as R
from tests.corpus.receipts import CASES

FIELDS = ("subtotal", "tax", "tip", "discount", "total")


def _read(case):
    extracted = R.extract(case["text"])
    return extracted, R.as_receipt(extracted)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_every_stated_field_is_read_as_the_paper_states_it(case):
    """
    Field by field, against hand-keyed truth. A field the receipt does not
    state must come back absent rather than guessed.
    """
    extracted, parsed = _read(case)
    expected = case["expect"]

    for field in FIELDS:
        if field not in expected:
            continue
        want = expected[field]
        got = parsed.get(field)
        got = None if got is None else int(got)
        assert got == want, (
            f"{case['name']}: {field} read as {got}, the receipt says {want}")


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_merchant_is_the_name_at_the_top(case):
    if "merchant" not in case["expect"]:
        return
    extracted, _ = _read(case)
    want = case["expect"]["merchant"]
    got = extracted["merchant"] or None
    assert got == want, f"{case['name']}: merchant {got!r}, expected {want!r}"


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_line_items_are_the_priced_rows_and_nothing_else(case):
    """
    The column that gets summed. A phone number, a date, a unit price, a
    loyalty balance or the change due joining it is how a receipt disagrees
    with itself for a reason that has nothing to do with the merchant.
    """
    if "lines" not in case["expect"]:
        return
    extracted, _ = _read(case)
    got = [int(item["amount"]) for item in extracted["lines"]]
    assert got == case["expect"]["lines"], (
        f"{case['name']}: line items {got}, expected {case['expect']['lines']}")


def test_no_receipt_in_the_corpus_reconciles_on_a_wrong_reading():
    """
    The measurement this file exists for.

    A silent pass is a receipt whose fields were read wrongly and which
    reconciles anyway. It is the only output nothing else can catch: the
    verdict says clean, the ledger says clean, and the number is wrong. This
    asserts the rate is zero on the corpus, and prints the tally either way.
    """
    silent, checked, wrong = [], 0, []

    for case in CASES:
        extracted, parsed = _read(case)
        expected = case["expect"]

        mistakes = [
            f"{field}={parsed.get(field)} not {expected[field]}"
            for field in FIELDS
            if field in expected
            and (None if parsed.get(field) is None else int(parsed[field]))
               != expected[field]]
        if "lines" in expected:
            got = [int(i["amount"]) for i in extracted["lines"]]
            if got != expected["lines"]:
                mistakes.append(f"lines={got} not {expected['lines']}")

        if not mistakes:
            continue
        wrong.append((case["name"], mistakes))

        # Read wrongly. Does it still come out clean? That is the dangerous one.
        total = parsed.get("total")
        if total is None:
            continue
        checked += 1
        result = V.reconcile(parsed, {"amount": V.Cents(-abs(int(total))),
                                      "date": "2026-08-06"})
        if result["verdict"] == V.RECONCILED:
            silent.append((case["name"], mistakes))

    print(f"\ncorpus: {len(CASES)} receipts")
    print(f"  read exactly as the paper states: {len(CASES) - len(wrong)}")
    for name, mistakes in wrong:
        print(f"  MISREAD {name}: {'; '.join(mistakes)}")
    print(f"  silent passes (misread AND reconciled): {len(silent)}")

    assert not silent, (
        "these receipts were read wrongly and reconciled anyway, which is the "
        f"one output nothing downstream can catch: {silent}")


def test_the_receipts_flagged_as_traps_are_all_read_correctly():
    """
    The subset where a wrong reading would look clean: change due after the
    total, a loyalty balance at the foot, unit prices in the line items, a date
    that looks like money, a thousands separator, "SUB TOTAL" against "TOTAL".
    Named in the corpus rather than inferred, so adding a trap means saying so.
    """
    traps = [c for c in CASES if c.get("silent_pass_risk")]
    assert len(traps) >= 6, "the corpus should keep its known traps"

    for case in traps:
        extracted, parsed = _read(case)
        for field in FIELDS:
            if field in case["expect"]:
                got = parsed.get(field)
                assert (None if got is None else int(got)) == case["expect"][field], \
                    f"{case['name']}: {field}"
        if "lines" in case["expect"]:
            assert [int(i["amount"]) for i in extracted["lines"]] == \
                case["expect"]["lines"], case["name"]


def test_a_receipt_that_says_nothing_yields_nothing():
    """An unreadable scan must produce no numbers, not confident wrong ones."""
    case = next(c for c in CASES if c["name"] == "nothing_readable")
    extracted, parsed = _read(case)
    assert parsed.get("total") is None
    assert extracted["lines"] == []


def test_both_decimal_conventions_appear_and_both_are_read():
    """
    A corpus that only contains one convention proves nothing about the other,
    and the decimal comma is where the worst bug in this project lived.
    """
    comma = [c for c in CASES if "," in c["text"] and "." not in c["text"]
             .split("\n")[-3]]
    assert comma, "the corpus must contain comma-decimal receipts"
    for case in comma:
        _, parsed = _read(case)
        for field in FIELDS:
            if case["expect"].get(field):
                assert abs(int(parsed[field])) < 1_000_00, (
                    f"{case['name']}: {field} looks inflated a hundredfold")
