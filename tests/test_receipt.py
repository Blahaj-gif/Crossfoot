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


# --------------------------------------------------------------------------
# One receipt, one decimal mark
# --------------------------------------------------------------------------

DOT_RECEIPT = """SPORTS OUTLET

Trainers               60.00
Socks                   8.00

SUBTOTAL               68.00
DISCOUNT               10.00
TAX                     4.64
TOTAL                  62.64
"""


def test_an_amount_using_the_other_decimal_mark_is_dropped_rather_than_read():
    """
    The silent pass a photograph found, and the reason this rule exists.

    A phone photograph of the receipt below came back with every amount intact
    except the discount, which read "16,02" — a comma, on a receipt that prints
    points. The total was right, the charge matched it, and no subtotal survived
    to constrain the adjustments, so it reconciled carrying a discount wrong by
    six pounds. Nothing downstream can catch that.

    Dropping the field costs the discount. That is the right price: the receipt
    becomes one with an unread field rather than one with a confident wrong one.
    """
    damaged = DOT_RECEIPT.replace("DISCOUNT               10.00",
                                  "DISCOUNT               16,02")
    parsed = R.as_receipt(R.extract(damaged))
    assert "discount" not in parsed
    assert int(parsed["total"]) == 6264


def test_a_receipt_that_prints_commas_throughout_is_read_in_commas():
    """The rule is about disagreement, not about preferring points."""
    german = """KAUFLAND

Brot                    2,50
Milch                   1,20

ZWISCHENSUMME           3,70
MWST                    0,26
SUMME                   3,96
"""
    parsed = R.as_receipt(R.extract(german))
    assert int(parsed["subtotal"]) == 370
    assert int(parsed["total"]) == 396


def test_a_receipt_with_too_few_amounts_to_judge_decides_nothing():
    """
    Two amounts are not evidence of a convention. Refusing on that little would
    throw away the commonest receipt there is: one line and a total.
    """
    assert R._decimal_mark(["TOTAL 14.00", "CASH 20,00"]) == ""


def test_a_receipt_evenly_split_between_marks_decides_nothing():
    """Ambiguous is a real answer, and quieter than picking a side."""
    lines = ["A 1.00", "B 2.00", "C 3,00", "D 4,00"]
    assert R._decimal_mark(lines) == ""


def test_thousands_separators_do_not_vote_for_the_wrong_mark():
    """
    "1,234.56" is a point-decimal amount that contains a comma. Counting the
    comma would make a receipt of large amounts look like a European one and
    every amount on it would then be dropped.
    """
    lines = ["A 1,234.56", "B 2,000.00", "C 3,500.00"]
    assert R._decimal_mark(lines) == "."


# --------------------------------------------------------------------------
# VAT that is inside the total rather than added to it
# --------------------------------------------------------------------------

def test_a_line_saying_the_total_includes_vat_is_not_the_total():
    """
    Found on a photograph of a real receipt from Lae, Papua New Guinea.

    "TOTAL INCLUDES VAT OF   1.77" begins with the word TOTAL, and by the rule
    that a later TOTAL beats an earlier one it overwrote the real total. The
    receipt reported a total of 1.77 against a charge of 19.50 — a loud failure
    rather than a silent one, and still wrong.

    The line states the tax, so it is read as the tax.
    """
    text = """CHIN H. MEEN & SON'S LTD.

Choking band            19.50

TOTAL                   19.50
Cash                    20.00
CHANGE                   0.50
TOTAL INCLUDES VAT OF    1.77
"""
    parsed = R.as_receipt(R.extract(text))
    assert int(parsed["total"]) == 1950
    assert int(parsed["tax"]) == 177


def test_vat_inclusive_phrasing_in_other_languages_is_read_the_same_way():
    """The phrasing is not an English idiom; the receipts it appears on are not
    English either."""
    assert R._label_on("Incl. 7.6% MwSt 54.50 CHF: 3.85") == "tax"
    assert R._label_on("Gesamt inkl. MwSt 3,85") == "tax"
    assert R._label_on("Totaal incl. BTW 2,10") == "tax"


def test_an_ordinary_total_line_is_still_a_total():
    """The guard must not eat the thing it sits next to."""
    assert R._label_on("TOTAL                   19.50") == "total"
    assert R._label_on("TOTAL DUE               19.50") == "total"
    assert R._label_on("TAX                      1.77") == "tax"
