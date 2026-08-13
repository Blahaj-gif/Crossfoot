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


class _FakeImage:
    """
    Enough of a Pillow image for the reader to measure, crop and enlarge.

    Not a stub that returns fixed answers: it carries a real bright rectangle
    on a dark ground and reports real pixel values, so the paper-finding
    arithmetic actually runs. That arithmetic is the part worth testing without
    the binary — a crop twenty pixels too generous is the difference between a
    receipt that reads and one that returns nothing at all.

    `paper` is where the document sits, as fractions of the frame. None means
    the frame is uniform, which is what a scan or a rendered page looks like.
    """

    def __init__(self, width=600, height=800, paper=None, offset=(0, 0)):
        self.width, self.height, self.paper = width, height, paper
        self.offset = offset
        self.resized_to = None
        self.cropped_to = None

    @property
    def size(self):
        return (self.width, self.height)

    def convert(self, mode):
        return self

    def copy(self):
        out = _FakeImage(self.width, self.height, self.paper, self.offset)
        out.origin = self
        return out

    def thumbnail(self, size, resample=None):
        factor = min(size[0] / self.width, size[1] / self.height, 1.0)
        self.width = max(1, int(self.width * factor))
        self.height = max(1, int(self.height * factor))

    def load(self):
        image = self

        class _Pixels:
            def __getitem__(self, point):
                x, y = point
                if image.paper is None:
                    return 255
                left, top, right, bottom = image.paper
                inside = (left <= x / image.width < right
                          and top <= y / image.height < bottom)
                return 250 if inside else 15

        return _Pixels()

    def crop(self, box):
        self.cropped_to = box
        out = _FakeImage(box[2] - box[0], box[3] - box[1],
                         offset=(box[0], box[1]))
        out.origin = self
        return out

    def resize(self, size, resample=None):
        self.resized_to = size
        out = _FakeImage(size[0], size[1], offset=self.offset)
        out.origin = self
        return out


def _as_data(words):
    keys = ("text", "conf", "left", "top", "width", "height",
            "block_num", "par_num", "line_num")
    data = {key: [] for key in keys}
    for word in words:
        for key in keys:
            data[key].append(word[key])
    return data


def _tesseract_returning(words, second=None):
    """
    A stand-in for pytesseract producing its documented output.

    `image_to_data` returns parallel lists, one entry per recognised token,
    with `conf` of -1 for the layout rows that are not words at all — blocks,
    paragraphs and lines. Getting that wrong means every receipt gains three
    phantom tokens per line, so it is worth a fake that includes them.

    `second`, when given, is what the engine returns on the *second* reading of
    the same photograph — the one taken after the image has been enlarged. The
    reader only asks for it when the ink is too small, and the two readings
    have to be allowed to differ or the retry cannot be tested at all.
    """
    first, later = _as_data(words), _as_data(second or words)

    # The config string is captured rather than ignored. It carries the page
    # segmentation mode, and getting that wrong silently destroyed the amount
    # column on every two-column receipt -- so the fake has to see it.
    seen = {"calls": 0, "images": []}

    def image_to_data(image, config=None, output_type=None):
        seen["config"] = config
        seen["calls"] += 1
        seen["images"].append(image)
        return first if seen["calls"] == 1 else later

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

    def install(words, second=None, paper=None):
        module = _tesseract_returning(words, second)
        install.module = module
        install.image = _FakeImage(paper=paper)
        monkeypatch.setattr(ocr, "pytesseract", module)
        monkeypatch.setattr(ocr, "Image", types.SimpleNamespace(
            open=lambda p: install.image, LANCZOS=1, BILINEAR=2))
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


# --------------------------------------------------------------------------
# Finding the paper in the frame
# --------------------------------------------------------------------------

def test_a_frame_that_is_all_document_is_not_cropped(fake_tesseract):
    """
    A scan, or anything else with no desk in it. Cropping it could only shave
    the margins off a page that was never the problem.
    """
    path = fake_tesseract([_word("TOTAL", 96, 10, 10)], paper=None)
    ocr.read_image(path)
    assert fake_tesseract.image.cropped_to is None


def test_a_receipt_on_a_dark_desk_is_cropped_to_the_paper(fake_tesseract):
    """
    The bug real paper found and the rendered corpus could not.

    Tesseract binarises the whole image against one threshold, so the desk
    decides where that threshold falls and the ink ends up on the wrong side of
    it. A flat, sharp, entirely legible scan of a receipt on a blue desk mat
    produced zero words at every page segmentation mode. Cropped, it produced
    114 words at 71% confidence.
    """
    path = fake_tesseract([_word("TOTAL", 96, 10, 10)],
                          paper=(0.2, 0.1, 0.8, 0.9))
    ocr.read_image(path)
    box = fake_tesseract.image.cropped_to
    assert box is not None
    left, top, right, bottom = box
    # Inside the paper, not merely near it. A crop twenty pixels too generous
    # left a sliver of desk in frame, and a sliver took the same receipt from
    # 121 words back to zero.
    assert left >= 0.2 * 600 and right <= 0.8 * 600
    assert top >= 0.1 * 800 and bottom <= 0.9 * 800


def test_a_box_off_a_cropped_reading_lands_on_the_original_image(fake_tesseract):
    """
    Same hazard as the enlargement, from the other direction: the engine reads
    a crop and reports coordinates within it, while `crop` opens the whole file.
    Without the offset the queue shows a reviewer the wrong part of the page.
    """
    path = fake_tesseract([_word("TOTAL", 96, 10, 20, width=50, height=14)],
                          paper=(0.2, 0.1, 0.8, 0.9))
    read = ocr.read_image(path)
    left, top, _, _ = fake_tesseract.image.cropped_to
    assert read["words"][0].box == (left + 10, top + 20, left + 60, top + 34)


# --------------------------------------------------------------------------
# Reading a photograph whose ink is too small
# --------------------------------------------------------------------------

def test_ink_big_enough_to_read_is_read_once(fake_tesseract):
    """
    The expensive half of the retry is not paying for it when it is not needed.

    It is also the safe half. Enlarging every image was measured and it lost:
    accuracy fell on seven of eleven degradations and silent passes appeared on
    nine, because a second reading of an already-legible photograph is not a
    better reading, it is a different wrong one.
    """
    path = fake_tesseract([_word("TOTAL", 96, 10, 10, height=20)])
    ocr.read_image(path)
    assert fake_tesseract.module.seen["calls"] == 1
    assert fake_tesseract.image.resized_to is None


def test_ink_too_small_to_read_is_read_again_larger(fake_tesseract):
    """
    Below about eleven pixels of character height the engine stops reading
    letters and starts reading shapes, and the labels go first: TOTAL as
    "oral", SUBTOTAL as "susToTAL". The amounts survive and nothing is left to
    name them.
    """
    path = fake_tesseract(
        [_word("oral", 40, 10, 10, height=6), _word("17.31", 90, 300, 10, height=6)],
        second=[_word("TOTAL", 96, 20, 20, width=80, height=16),
                _word("17.31", 95, 600, 20, width=80, height=16)])
    read = ocr.read_image(path)

    assert fake_tesseract.module.seen["calls"] == 2
    assert fake_tesseract.image.resized_to is not None
    assert read["text"] == "TOTAL 17.31"


def test_a_box_off_an_enlarged_reading_lands_on_the_original_image(fake_tesseract):
    """
    The retry's one genuine hazard.

    Every box comes off the image the *engine* read, and `crop` opens the image
    on *disk*. Keeping the enlarged coordinates would show a reviewer a patch of
    paper from somewhere else on the receipt, labelled as the total — evidence
    that is not evidence, which is worse than showing nothing.
    """
    path = fake_tesseract(
        [_word("oral", 40, 10, 10, height=8)],
        # Enlarged by 16/8 = 2, so a word at (200, 100) 80x16 on the enlarged
        # image sat at (100, 50) 40x8 on the file.
        second=[_word("TOTAL", 96, 200, 100, width=80, height=16)])
    read = ocr.read_image(path)
    assert read["words"][0].box == (100, 50, 140, 58)


def test_an_enlargement_that_reads_nothing_keeps_the_first_reading(fake_tesseract):
    """A second pass that returns nothing has failed, not done better."""
    path = fake_tesseract([_word("17.31", 90, 10, 10, height=6)], second=[])
    read = ocr.read_image(path)
    assert read["text"] == "17.31"


def test_a_receipt_in_the_corner_of_a_huge_photograph_is_not_enlarged_forever(
        fake_tesseract):
    """
    Tiny ink in a twelve-megapixel frame implies a scale that would ask Pillow
    for an image of absurd size. The cap is not a tuning knob; it is the reason
    a phone photograph cannot exhaust memory.
    """
    path = fake_tesseract([_word("x", 30, 5, 5, height=1)],
                          second=[_word("TOTAL", 96, 10, 10)])
    ocr.read_image(path)
    width, _ = fake_tesseract.image.resized_to
    assert width <= fake_tesseract.image.width * ocr.MAXIMUM_SCALE


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
