"""
PDFs, which are two entirely different files wearing one extension.

Stage 4 of the direction document: measure the PDF path before deciding
whether to bet on it. The measurement said the bet was mostly already lost and
partly already won — two thirds of real PDFs are scans that no reader helps
with, and the text-layer third needs no dependency at all.

Nothing here needs docling, which is the finding.
"""
import os
import sys
import zlib

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot.read import document, pdf
from crossfoot.read import receipt as R


def _pdf(content: bytes, extra_objects: bytes = b"", compress=True) -> bytes:
    """
    A minimal but genuinely valid PDF carrying one content stream.

    Built here rather than committed as a fixture file so that what is being
    tested is visible in the test: the bytes below are the whole document.
    """
    stream = zlib.compress(content) if compress else content
    filt = b"/Filter /FlateDecode " if compress else b""
    return (b"%PDF-1.4\n"
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
            b"3 0 obj << /Type /Page /Parent 2 0 R /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
            b"4 0 obj << /Length " + str(len(stream)).encode() + b" " + filt
            + b">>\nstream\n" + stream + b"\nendstream endobj\n"
            b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> "
            b"endobj\n" + extra_objects
            + b"trailer << /Root 1 0 R >>\n%%EOF\n")


def _drawing(*lines) -> bytes:
    """A content stream that draws each line as text, the way a PDF does."""
    out = [b"BT /F1 12 Tf"]
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", r"\(").replace(")", r"\)")
        out.append(b"0 -14 Td (" + escaped.encode("latin-1") + b") Tj")
    out.append(b"ET")
    return b"\n".join(out)


RECEIPT = ("BLUE BOTTLE COFFEE", "Latte 13.50", "SUBTOTAL 13.50",
           "TAX 1.11", "TIP 2.70", "TOTAL 17.31")


# --------------------------------------------------------------------------
# Telling the two kinds apart
# --------------------------------------------------------------------------

def test_a_pdf_that_draws_text_is_recognised_as_text():
    assert pdf.kind(_pdf(_drawing(*RECEIPT * 5))) == pdf.TEXT


def test_a_pdf_that_draws_only_a_picture_is_recognised_as_a_scan():
    """
    What a scanner produces, and what two thirds of real PDF receipts are. It
    has a font resource it never uses, which is why the test counts the
    operators that draw a string rather than looking for fonts.
    """
    scan = _pdf(b"q 600 0 0 800 0 0 cm /Im0 Do Q",
                extra_objects=b"6 0 obj << /Subtype /Image /Width 600 >> endobj\n")
    assert pdf.kind(scan) == pdf.SCAN


def test_a_stray_string_on_a_scan_does_not_make_it_a_text_layer():
    """
    A scanned page routinely carries a stamped page number or a watermark. One
    string is not a document, and treating it as one would produce a receipt
    with a single number in it and no way to tell that was all there was.
    """
    nearly = _pdf(b"BT /F1 8 Tf (Page 1 of 2) Tj ET\nq 600 0 0 800 0 0 cm /Im0 Do Q",
                  extra_objects=b"6 0 obj << /Subtype /Image /Width 600 >> endobj\n")
    assert pdf.kind(nearly) == pdf.SCAN


# --------------------------------------------------------------------------
# Reading the half that can be read
# --------------------------------------------------------------------------

def test_a_text_layer_receipt_reads_end_to_end_with_no_dependency(tmp_path):
    """
    The finding that decides Stage 4: the whole path, with nothing installed.

    docling is the declared reader for this and has never been installed in
    this project's life. It is unnecessary here, and for a scanned PDF it would
    only OCR the page and inherit the one-in-fifty-five result from the
    photograph measurement.
    """
    path = tmp_path / "invoice.pdf"
    path.write_bytes(_pdf(_drawing(*RECEIPT)))

    read = document.read(str(path))
    assert read["reader"] == "pdf (text)"
    assert read["degraded"] is False

    parsed = R.as_receipt(R.extract(read["text"]))
    assert int(parsed["subtotal"]) == 1350
    assert int(parsed["tax"]) == 111
    assert int(parsed["tip"]) == 270
    assert int(parsed["total"]) == 1731


def test_an_uncompressed_content_stream_reads_too(tmp_path):
    """Not every producer deflates. A great many older ones do not."""
    path = tmp_path / "flat.pdf"
    path.write_bytes(_pdf(_drawing(*RECEIPT), compress=False))
    assert int(R.as_receipt(R.extract(document.read(str(path))["text"]))["total"]) == 1731


def test_escaped_parentheses_survive(tmp_path):
    """
    `(` and `)` delimit a PDF string, so a receipt line containing one is
    escaped in the file. Getting this wrong truncates the line — and the line
    it truncates is whichever one says "TOTAL (incl. VAT)".
    """
    path = tmp_path / "escaped.pdf"
    path.write_bytes(_pdf(_drawing("TOTAL (incl. VAT) 17.31")))
    text = document.read(str(path))["text"]
    assert "(incl. VAT)" in text
    assert int(R.as_receipt(R.extract(text))["total"]) == 1731


# --------------------------------------------------------------------------
# Refusing the half that cannot
# --------------------------------------------------------------------------

def test_a_scanned_pdf_is_refused_with_a_reason_rather_than_read_as_empty(tmp_path):
    """
    Empty text parses to no fields, which comes out unchecked for a reason
    nobody can act on. "This file is a picture" is a reason somebody can act on.
    """
    path = tmp_path / "scan.pdf"
    path.write_bytes(_pdf(b"q 600 0 0 800 0 0 cm /Im0 Do Q",
                          extra_objects=b"6 0 obj << /Subtype /Image >> endobj\n"))
    read = document.read(str(path))
    assert read["degraded"] is True
    assert read["reader"] == "pdf (scan)"
    assert "scan" in read["why"]
    assert "fifty-five" in read["why"]


def test_a_scanned_pdf_yields_no_fields_at_all(tmp_path):
    """
    The property that matters more than the message: nothing downstream can
    find an amount in it, because there is no text to find one in.
    """
    path = tmp_path / "scan.pdf"
    path.write_bytes(_pdf(b"q 600 0 0 800 0 0 cm /Im0 Do Q",
                          extra_objects=b"6 0 obj << /Subtype /Image >> endobj\n"))
    read = document.read(str(path))
    assert R.as_receipt(R.extract(read["text"], degraded=read["degraded"])) \
        .get("total") is None


def test_a_pdf_that_is_not_a_pdf_at_all_does_not_raise(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a pdf, just some bytes")
    read = document.read(str(path))
    assert read["degraded"] is True


# --------------------------------------------------------------------------
# A PDF is an untrusted file
# --------------------------------------------------------------------------

def test_a_decompression_bomb_does_not_take_the_process_with_it():
    """
    A few kilobytes of deflate stream inflates to gigabytes, and
    `zlib.decompress` has no ceiling. It does not take an attacker either: this
    reads whatever somebody drops in a folder, and a receipt that arrived by
    email is not a trusted file just because it arrived.

    A megabyte of zeroes compresses to about a kilobyte; the real bomb is the
    same trick with a much larger payload, and the bound is what stops it.
    """
    payload = zlib.compress(b"\0" * (4 * 1024 * 1024))
    assert len(payload) < 20_000, "the fixture is not actually a bomb"

    bomb = (b"%PDF-1.4\n4 0 obj << /Filter /FlateDecode >>\nstream\n"
            + payload + b"\nendstream endobj\ntrailer << >>\n%%EOF\n")

    original = pdf.MAXIMUM_STREAM
    try:
        pdf.MAXIMUM_STREAM = 64 * 1024
        assert all(len(s) <= pdf.MAXIMUM_STREAM for s in pdf._streams(bomb))
    finally:
        pdf.MAXIMUM_STREAM = original


def test_an_ordinary_receipt_is_nowhere_near_the_bound(tmp_path):
    """The guard must not truncate a real document."""
    path = tmp_path / "long.pdf"
    path.write_bytes(_pdf(_drawing(*(RECEIPT * 200))))
    assert int(R.as_receipt(R.extract(document.read(str(path))["text"]))["total"]) == 1731


# --------------------------------------------------------------------------
# Parsing what a vision model says, without four gigabytes of weights
# --------------------------------------------------------------------------

def test_a_models_reply_becomes_a_receipt_marked_as_generated():
    from crossfoot.read import vision
    got = vision.as_receipt('{"merchant": "SHOP", "subtotal": 2.50, '
                            '"tax": 0.13, "total": 2.63, "tip": null}')
    assert got["generated"] is True
    assert int(got["subtotal"]) == 250 and int(got["total"]) == 263
    assert "tip" not in got


def test_prose_around_the_json_is_tolerated():
    """Models preface things. The JSON is what matters."""
    from crossfoot.read import vision
    got = vision.as_receipt('Sure! Here is the receipt:\n{"total": 17.31}\nHope that helps')
    assert int(got["total"]) == 1731


def test_a_reply_that_is_not_json_yields_no_figures_rather_than_guesses():
    from crossfoot.read import vision
    got = vision.as_receipt("I think the total is about seventeen pounds")
    assert got["generated"] is True
    assert "total" not in got


def test_a_value_that_is_not_a_number_is_dropped():
    """A model asked for a number sometimes returns "approximately 17.31"."""
    from crossfoot.read import vision
    got = vision.as_receipt('{"total": "approximately 17.31", "tax": 1.11}')
    assert "total" not in got
    assert int(got["tax"]) == 111
