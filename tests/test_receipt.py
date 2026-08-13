"""
Step 2 — reading a receipt, and knowing which numbers not to trust.

The failure mode that governs this file: a wrong reading that produces a
*clean* verdict. A total read as the subtotal, a tax rate read as the tax, a
loyalty balance summed into the line items — each of those can make a receipt
agree with itself while agreeing about the wrong thing.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot import verdict as V
from crossfoot.read import document, receipt as R

PLAIN = """\
BLUE BOTTLE COFFEE
123 Mint Plaza

Latte                    5.50
Croissant                4.25
Drip Coffee              3.75

SUBTOTAL                13.50
TAX                      1.11
TIP                      2.70
TOTAL                   17.31

VISA ****4471
"""


# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------

def test_the_labelled_fields_come_off_a_plain_receipt():
    fields = R.extract(PLAIN)["fields"]
    assert fields["subtotal"].value == 1350
    assert fields["tax"].value == 111
    assert fields["tip"].value == 270
    assert fields["total"].value == 1731
    assert all(f.trusted for f in fields.values())


def test_sub_total_is_never_read_as_total():
    """
    The wrong reading that produces a clean verdict: with the subtotal in the
    total, a zero-tax receipt reconciles against itself perfectly.
    """
    text = "SUB TOTAL   10.00\nTAX          0.00\nTOTAL       10.00\n"
    fields = R.extract(text)["fields"]
    assert fields["subtotal"].value == 1000
    assert fields["total"].value == 1000
    assert fields["subtotal"].line_number != fields["total"].line_number


def test_a_rate_printed_beside_a_label_is_not_the_money():
    """Receipts print "TAX 8.25%   4.12". The rate is not the amount."""
    assert R.extract("TAX 8.25%    4.12\n")["fields"]["tax"].value == 412


def test_the_last_total_wins():
    """
    "TOTAL", then "TOTAL DUE", then the card slip's own total is the order
    these print in, and the last is what was charged.
    """
    text = "TOTAL       17.31\nAMOUNT PAID 17.31\nTOTAL       17.31\n"
    assert R.extract(text)["fields"]["total"].value == 1731


def test_every_field_carries_the_line_it_came_from():
    """A number nobody can trace is the thing this project exists to replace."""
    field = R.extract(PLAIN)["fields"]["total"]
    assert "TOTAL" in field.line
    assert field.line_number is not None


# --------------------------------------------------------------------------
# Confidence
# --------------------------------------------------------------------------

def test_an_unlabelled_total_is_inferred_and_not_trusted():
    """
    Position gets it right most of the time, which is exactly why it is not
    trusted. "Usually right" is the failure this whole project is about.
    """
    text = "Latte  5.50\nCroissant  4.25\n\n9.75\n"
    field = R.extract(text)["fields"]["total"]
    assert field.confidence == R.INFERRED
    assert field.trusted is False


def test_an_untrusted_field_is_withheld_from_the_checks():
    text = "Latte  5.50\nCroissant  4.25\n\n9.75\n"
    parsed = R.as_receipt(R.extract(text))
    assert "total" not in parsed
    assert V.reconcile(parsed, {"amount": "9.75"})["verdict"] == V.UNCHECKED


def test_a_withheld_field_is_named_so_the_queue_can_ask():
    text = "Latte  5.50\n\n9.75\n"
    assert "total" in R.extract(text)["needs_human"]


def test_a_receipt_with_no_amounts_at_all_yields_nothing_rather_than_zero():
    field = R.extract("THANK YOU FOR SHOPPING\n")["fields"]["total"]
    assert field.value is None
    assert field.trusted is False


# --------------------------------------------------------------------------
# Line items
# --------------------------------------------------------------------------

def test_line_items_stop_at_the_subtotal():
    """
    Without the lower bound the tax, the total, the change and the card's last
    four digits all join the column being summed, and the sum agrees with
    nothing.
    """
    items = R.extract(PLAIN)["lines"]
    assert [i["amount"] for i in items] == [550, 425, 375]
    assert sum(i["amount"] for i in items) == 1350


def test_a_bare_number_is_not_a_line_item():
    text = "Latte   5.50\n   4.25\nSUBTOTAL  9.75\n"
    assert [i["amount"] for i in R.extract(text)["lines"]] == [550]


def test_without_a_subtotal_no_line_items_are_collected():
    """
    There is no trustworthy lower bound, so an empty list leaves check 1 unrun.
    Guessing a bound would run the check on the wrong column and pass or fail
    for reasons nobody could trace.
    """
    text = "Latte  5.50\nCroissant  4.25\nTOTAL  9.75\n"
    assert R.extract(text)["lines"] == []


def test_the_extracted_receipt_reconciles_end_to_end():
    parsed = R.as_receipt(R.extract(PLAIN))
    result = V.reconcile(parsed, {"amount": "17.31"})
    assert result["verdict"] == V.RECONCILED, result["why"]


def test_a_receipt_whose_own_arithmetic_is_wrong_is_caught_after_reading():
    broken = PLAIN.replace("SUBTOTAL                13.50",
                           "SUBTOTAL                19.50")
    parsed = R.as_receipt(R.extract(broken))
    result = V.reconcile(parsed, {"amount": "17.31"})
    assert result["verdict"] == V.DISCREPANT


# --------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------

def test_the_currency_is_noted_when_the_receipt_states_one():
    assert R.extract("TOTAL  $17.31\n")["currency"] == "$"
    assert R.extract("TOTAL  17.31\n")["currency"] is None


def test_the_reader_is_reported_so_provenance_survives(tmp_path):
    """
    A total read by Docling off a structured PDF and one read from a text dump
    are not equally trustworthy, and the queue should be able to say which.
    """
    path = tmp_path / "r.txt"
    path.write_text(PLAIN, encoding="utf-8")
    result = document.read(str(path))
    assert result["reader"].startswith("plain text")
    assert result["degraded"] is False
    assert "TOTAL" in result["text"]


def test_a_pdf_with_no_layout_reader_installed_says_it_is_degraded(tmp_path):
    """A PDF read as text is mostly binary noise; a total 'found' in it is an artefact."""
    if document.HAVE_DOCLING:                        # pragma: no cover
        pytest.skip("docling is installed, so this path is not taken")
    path = tmp_path / "r.pdf"
    path.write_bytes(b"%PDF-1.4\n stuff \n")
    assert document.read(str(path))["degraded"] is True


def test_a_missing_file_raises_rather_than_returning_empty_text(tmp_path):
    with pytest.raises(document.UnreadableDocument):
        document.read(str(tmp_path / "nope.txt"))


def test_the_merchant_comes_off_the_receipt_rather_than_the_filename():
    """
    The fallback is whatever the phone called the photo. "IMG_2043" matches no
    descriptor, so every receipt would land in the queue — and worse, an
    unrelated one could be accepted on amount alone.
    """
    assert R.extract(PLAIN)["merchant"] == "BLUE BOTTLE COFFEE"
    assert R.as_receipt(R.extract(PLAIN))["merchant"] == "BLUE BOTTLE COFFEE"


def test_a_priced_or_labelled_line_is_not_the_merchant():
    assert R.extract("14.00\nTOTAL 14.00\nACME LTD\n")["merchant"] == "ACME LTD"


def test_a_receipt_with_no_header_names_nobody_rather_than_guessing():
    assert R.extract("TOTAL 14.00\n")["merchant"] == ""
