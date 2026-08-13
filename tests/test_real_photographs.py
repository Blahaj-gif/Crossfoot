"""
Six photographs of real paper, measured.

Everything else about the photograph path is measured on rendered text with
damage applied to it. That was always the stated limit of it. These are
photographs somebody took of receipts: a Swiss restaurant bill on a wooden
table, a 1988 Intershop slip that has been folded since 1988, a Korean receipt
whose labels are in a script the engine was not given, and a bank transfer
confirmation that is not a till receipt at all.

They found things the rendered corpus structurally could not:

  * A flat, sharp, entirely legible scan produced **zero words** at every page
    segmentation mode, because the receipt sat on a blue desk mat and Tesseract
    binarises the whole frame against one threshold. Cropped to the paper it
    produced 114 words at 71% confidence. A rendered receipt is paper edge to
    edge and has no desk in it, so no amount of damage applied to one could
    have shown this.
  * "TOTAL INCLUDES VAT OF   1.77" was read as the total, and by the rule that
    a later TOTAL beats an earlier one it overwrote the real one. The receipt
    reported a total of 1.77 against a charge of 19.50.

Skipped, loudly, when the photographs have not been fetched --
`python -m tests.corpus.photographs` -- or when no engine is installed. Nothing
here reaches the network during a test run.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot import verdict as V
from crossfoot.read import ocr
from crossfoot.read import receipt as R
from tests.corpus import photographs as P

FIELDS = ("subtotal", "tax", "tip", "discount", "total")

pytestmark = [
    pytest.mark.skipif(not ocr.available(),
                       reason="no OCR engine installed — run `crossfoot doctor`"),
    pytest.mark.skipif(not P.present(),
                       reason="photographs not fetched — run "
                              "`python -m tests.corpus.photographs`"),
]


def _read(entry):
    read = ocr.read_image(P.path_for(entry))
    extracted = R.extract(read["text"], read["lines"],
                          degraded=read.get("degraded", False))
    return read, R.as_receipt(extracted)


@pytest.mark.parametrize("entry", P.PHOTOGRAPHS, ids=lambda e: e["name"])
def test_a_photograph_of_real_paper(entry, capsys):
    """
    What the tool makes of one real receipt, printed whatever happens.

    One thing is asserted: no field is recorded wrongly on a receipt that then
    reconciles. A field the tool declines to record is counted and printed and
    not asserted on — refusing puts no number in anybody's ledger, which is the
    entire mechanism by which the assertion holds.
    """
    read, parsed = _read(entry)
    misread, missing = [], []
    for field in FIELDS:
        if field not in entry["expect"]:
            continue
        want = entry["expect"][field]
        got = parsed.get(field)
        got = None if got is None else int(got)
        if got == want:
            continue
        (missing if got is None else misread).append(f"{field}={got} not {want}")

    with capsys.disabled():
        print(f"\n  {entry['name']:24} {read['confidence']:5.1f}% confident, "
              f"{len(read['words']):4} words, "
              f"{'refused' if read['degraded'] else 'read'}")
        if misread:
            print(f"      WRONG:   {'; '.join(misread)}")
        if missing:
            print(f"      unread:  {'; '.join(missing)}")

    truth = entry["expect"].get("total")
    if not misread or truth is None:
        return
    result = V.reconcile(parsed, {"amount": V.Cents(-abs(truth)),
                                 "date": "2026-08-06"})
    assert result["verdict"] != V.RECONCILED, (
        f"{entry['name']}: recorded a wrong number and reconciled anyway, "
        f"which is the one output nothing downstream can catch: {misread}")


@pytest.mark.parametrize(
    "entry", [e for e in P.PHOTOGRAPHS if e.get("unreadable")],
    ids=lambda e: e["name"])
def test_a_photograph_with_nothing_to_check_invents_nothing(entry):
    """
    Three of the six have no arithmetic to check: one is cropped so the total
    is off the frame, one is labelled entirely in Hangul, one is a bank
    transfer confirmation. Each has numbers on it that a parser would happily
    find. The right answer is a total of None.
    """
    _, parsed = _read(entry)
    assert parsed.get("total") is None, (
        f"{entry['name']}: invented a total from a document where "
        f"{entry['unreadable']}")


def test_the_traps_on_these_receipts_are_not_read_as_the_total():
    """
    Every one of them prints a number that is not the total and looks like one:
    the cash tendered, the change, the same total again in euros, a receipt
    number, a phone number. Any of those becoming the total would reconcile
    against nothing and quietly misstate a charge.
    """
    for entry in P.PHOTOGRAPHS:
        _, parsed = _read(entry)
        total = parsed.get("total")
        if total is None:
            continue
        for what, amount in (entry.get("traps") or {}).items():
            if amount is None:
                continue
            assert int(total) != amount, (
                f"{entry['name']}: read the {what} as the total")
