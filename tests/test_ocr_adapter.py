"""
The Tesseract adapter, tested without Tesseract.

This was the only significant path in the project nobody had ever run. It was
marked `# pragma: no cover - needs the binary` and left there, which for a
project whose whole argument is "measure it, do not assert it" is the one piece
of debt worth naming.

The binary is not needed to test the part that can be wrong. Tesseract's
`image_to_data` returns a documented dictionary of parallel lists, and
everything Crossfoot does with a photograph happens *after* that: mapping those
lists into words, grouping words into lines, deciding what to distrust. A fake
that returns the documented shape exercises all of it, and would have caught a
mistake in any of it.

What this cannot test is whether Tesseract reads a crumpled thermal receipt
correctly. Nothing but a photograph and a person can test that, and the corpus
harness in `test_ocr_images.py` measures it the moment the binary exists.
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot.read import ocr
from crossfoot.read import receipt as R


class _FakeOutput:
    DICT = "dict"


def _tesseract_returning(words):
    """
    A stand-in for pytesseract producing its documented output.

    `image_to_data` returns parallel lists, one entry per recognised token,
    with `conf` of -1 for the layout rows that are not words at all — blocks,
    paragraphs and lines. Getting that wrong means every receipt gains three
    phantom tokens per line, so it is worth a fake that includes them.
    """
    keys = ("text", "conf", "left", "top", "width", "height",
            "block_num", "par_num", "line_num")
    data = {key: [] for key in keys}
    for word in words:
        for key in keys:
            data[key].append(word[key])

    # The config string is captured rather than ignored. It carries the page
    # segmentation mode, and getting that wrong silently destroyed the amount
    # column on every two-column receipt -- so the fake has to see it.
    seen = {}

    def image_to_data(image, config=None, output_type=None):
        seen["config"] = config
        return data

    module = types.SimpleNamespace(
        Output=_FakeOutput,
        image_to_data=image_to_data,
        get_tesseract_version=lambda: "5.4.0",
        seen=seen,
    )
    return module


def _word(text, conf, left, top, width=40, height=12, block=1, par=1, line=0):
    return dict(text=text, conf=conf, left=left, top=top, width=width,
                height=height, block_num=block, par_num=par, line_num=line)


@pytest.fixture()
def fake_tesseract(monkeypatch, tmp_path):
    """Wire the fake in, and give it an image path that exists."""
    path = tmp_path / "receipt.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0")

    def install(words):
        module = _tesseract_returning(words)
        install.module = module
        monkeypatch.setattr(ocr, "pytesseract", module)
        monkeypatch.setattr(ocr, "Image",
                            types.SimpleNamespace(open=lambda p: p))
        monkeypatch.setattr(ocr, "HAVE_TESSERACT", True)
        monkeypatch.setattr(ocr, "_tesseract_binary_works", lambda: True)
        return str(path)

    return install


# --------------------------------------------------------------------------
# Mapping what Tesseract returns
# --------------------------------------------------------------------------

def test_a_receipt_comes_back_as_lines_in_reading_order(fake_tesseract):
    path = fake_tesseract([
        _word("BLUE", 96, 10, 10, line=0), _word("BOTTLE", 95, 60, 10, line=0),
        _word("TOTAL", 97, 10, 40, line=1), _word("17.31", 94, 300, 40, line=1),
    ])
    read = ocr.read_image(path)
    assert read["text"].splitlines() == ["BLUE BOTTLE", "TOTAL 17.31"]
    assert read["reader"] == "tesseract"


def test_words_arriving_out_of_order_are_still_read_left_to_right(fake_tesseract):
    """
    Tesseract does not promise left-to-right order within a line. Assembling in
    arrival order would print the amount before its label, and "TOTAL" would
    stop being a label with a number after it.
    """
    path = fake_tesseract([
        _word("17.31", 94, 300, 40, line=1), _word("TOTAL", 97, 10, 40, line=1),
    ])
    assert ocr.read_image(path)["text"] == "TOTAL 17.31"


def test_the_layout_rows_tesseract_emits_are_not_words(fake_tesseract):
    """
    `conf` of -1 marks a block, a paragraph or a line — structure, not text.
    Treating them as words puts empty strings and phantom boxes into every
    line, and the text comes out with holes in it.
    """
    path = fake_tesseract([
        _word("", -1, 0, 0, 500, 300, line=0),        # the page block
        _word("", -1, 0, 0, 500, 20, line=0),         # the paragraph
        _word("TOTAL", 97, 10, 40, line=1),
        _word("17.31", 94, 300, 40, line=1),
    ])
    read = ocr.read_image(path)
    assert read["text"] == "TOTAL 17.31"
    assert len(read["words"]) == 2


def test_lines_are_grouped_by_tesseracts_own_index_not_by_pixel_row(fake_tesseract):
    """
    Two lines a few pixels apart are still two lines. Inventing a line-breaking
    rule out of vertical position is how "SUB TOTAL 13.50" becomes two rows and
    the subtotal stops being found.
    """
    path = fake_tesseract([
        _word("SUB", 96, 10, 40, line=0), _word("TOTAL", 96, 50, 41, line=0),
        _word("13.50", 95, 300, 42, line=0),
        _word("TOTAL", 96, 10, 44, line=1), _word("14.61", 95, 300, 45, line=1),
    ])
    assert ocr.read_image(path)["text"].splitlines() == [
        "SUB TOTAL 13.50", "TOTAL 14.61"]


def test_a_block_boundary_starts_a_new_line(fake_tesseract):
    """
    The line index restarts inside each block, so grouping on it alone merges
    the first line of every block into one. The key is the whole triple.
    """
    path = fake_tesseract([
        _word("HEADER", 96, 10, 10, block=1, line=0),
        _word("TOTAL", 96, 10, 60, block=2, line=0),
    ])
    assert ocr.read_image(path)["text"].splitlines() == ["HEADER", "TOTAL"]


def test_whitespace_only_tokens_are_dropped(fake_tesseract):
    path = fake_tesseract([
        _word("   ", 90, 10, 10, line=0), _word("TOTAL", 96, 40, 10, line=0),
    ])
    assert ocr.read_image(path)["text"] == "TOTAL"


def test_a_confidence_tesseract_cannot_express_is_not_a_number(fake_tesseract):
    """Some builds return the string '-1'; a float() straight in would raise."""
    path = fake_tesseract([
        dict(_word("TOTAL", 96, 10, 10), conf="96"),
        dict(_word("junk", 0, 10, 30), conf="not a number"),
    ])
    read = ocr.read_image(path)
    assert [w.text for w in read["words"]] == ["TOTAL"]


# --------------------------------------------------------------------------
# Deciding what to distrust
# --------------------------------------------------------------------------

def test_a_clean_reading_is_not_degraded(fake_tesseract):
    path = fake_tesseract([
        _word("TOTAL", 96, 10, 10), _word("17.31", 94, 300, 10),
    ])
    read = ocr.read_image(path)
    assert read["degraded"] is False and read["confidence"] == 100.0


def test_a_reading_full_of_doubt_is_degraded(fake_tesseract):
    """
    A fifth of the words below threshold is a photograph worth retaking. Saying
    so costs a warning; not saying so costs a wrong total in a ledger that
    claims to be checked.
    """
    path = fake_tesseract([
        _word("TOTAL", 96, 10, 10), _word("17.31", 20, 300, 10),
        _word("TAX", 30, 10, 30, line=1),
    ])
    read = ocr.read_image(path)
    assert read["degraded"] is True
    assert "17.31" in read["doubtful"]


def test_a_photograph_that_yields_nothing_is_degraded_rather_than_empty(fake_tesseract):
    path = fake_tesseract([])
    read = ocr.read_image(path)
    assert read["degraded"] is True and read["text"] == ""


# --------------------------------------------------------------------------
# End to end, through the receipt parser
# --------------------------------------------------------------------------

def test_a_photographed_receipt_reconciles_against_its_own_arithmetic(fake_tesseract):
    """
    The whole path: Tesseract's lists, into words, into lines, into fields,
    into a verdict. If any hop is wrong this is where it shows.
    """
    rows = [("BLUE BOTTLE COFFEE",), ("Latte", "13.50"), ("SUBTOTAL", "13.50"),
            ("TAX", "1.11"), ("TIP", "2.70"), ("TOTAL", "17.31")]
    words = []
    for index, row in enumerate(rows):
        words.append(_word(row[0], 95, 10, 20 * index, line=index))
        if len(row) > 1:
            words.append(_word(row[1], 95, 300, 20 * index, line=index))

    read = ocr.read_image(fake_tesseract(words))
    extracted = R.extract(read["text"], read["lines"])
    parsed = R.as_receipt(extracted)

    assert extracted["merchant"] == "BLUE BOTTLE COFFEE"
    assert int(parsed["subtotal"]) == 1350
    assert int(parsed["tax"]) == 111
    assert int(parsed["tip"]) == 270
    assert int(parsed["total"]) == 1731


def test_every_field_off_a_photograph_carries_the_rectangle_it_came_from(
        fake_tesseract):
    """
    The reason boxes exist: the queue shows the ink rather than asking somebody
    to trust a number and go and find the original.
    """
    read = ocr.read_image(fake_tesseract([
        _word("TOTAL", 96, 10, 100, width=50), _word("17.31", 95, 300, 100),
    ]))
    field = R.extract(read["text"], read["lines"])["fields"]["total"]
    assert field.box == (10, 100, 340, 112)


def test_a_doubtful_total_is_withheld_from_the_checks(fake_tesseract):
    """
    A number the engine was unsure of must not become a verdict. It is shown to
    a person as evidence instead, which is what the crop is for.
    """
    read = ocr.read_image(fake_tesseract([
        _word("Latte", 95, 10, 10, line=0), _word("13.50", 95, 300, 10, line=0),
        _word("9.75", 15, 300, 40, line=1),
    ]))
    parsed = R.as_receipt(R.extract(read["text"], read["lines"]))
    assert "total" not in parsed


def test_the_page_segmentation_mode_is_set(fake_tesseract):
    """
    The bug that mattered most, and the one no fake could have found.

    Tesseract's default mode runs layout analysis first, decides a receipt is a
    multi-column document, and discards most of the amount column. Measured on
    a clean render of a Waitrose receipt it found one amount out of five, and
    put that one in a block of its own, so no line had a label and a number on
    it and every field came back empty.

    A till receipt is a single uniform block of text, which is mode 6. Saying
    so took that receipt from one amount in five to four, and the corpus from
    9 of 22 read exactly to 17.

    A fake cannot catch this, because a fake supplies the words layout analysis
    was throwing away. It can only make sure the setting is still being sent.
    """
    path = fake_tesseract([_word("TOTAL", 96, 10, 10)])
    ocr.read_image(path)
    assert "--psm" in fake_tesseract.module.seen["config"]
    assert ocr.PSM == "6"
