"""
The photograph path, measured — the moment an OCR engine exists.

Everything else about reading receipts is measured on text. This is the only
file that measures the thing a person actually does: point a camera at a piece
of paper. It runs the same 22-receipt corpus, rendered as images and then
damaged in the four ways a real photograph is damaged, and reports the two
numbers that matter.

    field accuracy   how often a stated number is read as stated
    silent passes    how often a receipt is read WRONGLY and reconciles anyway

The second is the one to watch. A misread that fails loudly costs somebody
thirty seconds; a misread that reconciles is a wrong number in a ledger that
says it was checked, and nothing downstream will ever catch it.

Skipped, loudly, when no engine is installed. A test suite that silently passes
because the thing it tests is absent is worse than one that fails.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot import verdict as V
from crossfoot.read import ocr
from crossfoot.read import receipt as R
from tests.corpus import render
from tests.corpus.receipts import CASES

FIELDS = ("subtotal", "tax", "tip", "discount", "total")

pytestmark = [
    pytest.mark.skipif(not render.HAVE_PILLOW, reason="Pillow is not installed"),
    pytest.mark.skipif(not ocr.available(),
                       reason="no OCR engine installed — run `crossfoot doctor`"),
]


def _read_image(case, degradation, tmp_path):
    image = render.DEGRADATIONS[degradation](render.render(case["text"]))
    path = render.write(image, str(tmp_path / f"{case['name']}-{degradation}.png"))
    read = ocr.read_image(path)
    extracted = R.extract(read["text"], read["lines"])
    return read, extracted, R.as_receipt(extracted)


def _mistakes(case, extracted, parsed):
    out = []
    for field in FIELDS:
        if field not in case["expect"]:
            continue
        want = case["expect"][field]
        got = parsed.get(field)
        got = None if got is None else int(got)
        if got != want:
            out.append(f"{field}={got} not {want}")
    return out


def _measure(degradation, tmp_path):
    """Run the whole corpus at one degradation and tally what happened."""
    exact, wrong, silent = 0, [], []
    for case in CASES:
        _, extracted, parsed = _read_image(case, degradation, tmp_path)
        mistakes = _mistakes(case, extracted, parsed)
        if not mistakes:
            exact += 1
            continue
        wrong.append((case["name"], mistakes))

        if parsed.get("total") is None:
            continue                        # unreadable is not a silent pass

        # Against the amount the *bank* says was charged, not against the
        # receipt's own misread total. The first version did the latter and
        # reported silent passes that cannot happen: a blurred 5.60 read as
        # 5.68 agreed with itself, so the receipt reconciled against itself.
        #
        # In reality the charge comes from a CSV. OCR cannot corrupt it, which
        # makes the statement the anchor the whole design rests on: a receipt
        # misread consistently still fails, because the number it is compared
        # against was never photographed.
        truth = case["expect"].get("total")
        if truth is None:
            continue
        result = V.reconcile(parsed, {"amount": V.Cents(-abs(int(truth))),
                                      "date": "2026-08-06"})
        if result["verdict"] == V.RECONCILED:
            silent.append((case["name"], mistakes))
    return exact, wrong, silent


@pytest.mark.parametrize("degradation", sorted(render.DEGRADATIONS))
def test_the_corpus_photographed(degradation, tmp_path, capsys):
    """
    Accuracy per degradation, printed whatever happens.

    Only the silent-pass count is asserted, and only at zero. Field accuracy is
    reported rather than gated: a threshold picked before any real photograph
    has been measured would be a number invented to be met.
    """
    exact, wrong, silent = _measure(degradation, tmp_path)

    with capsys.disabled():
        print(f"\n  {degradation:8} {exact:2}/{len(CASES)} read exactly"
              f"   silent passes: {len(silent)}")
        for name, mistakes in wrong[:4]:
            print(f"           {name}: {'; '.join(mistakes)}")

    assert not silent, (
        f"{degradation}: read wrongly and reconciled anyway, which is the one "
        f"output nothing downstream can catch: {silent}")


def test_a_clean_render_is_read_at_least_as_well_as_a_damaged_one(tmp_path):
    """
    Sanity on the harness itself. If a blurred receipt scores better than a
    crisp one, the measurement is broken and every number above it is noise.
    """
    clean, _, _ = _measure("clean", tmp_path)
    blurred, _, _ = _measure("blurred", tmp_path)
    assert clean >= blurred


def test_every_word_off_a_photograph_carries_a_box(tmp_path):
    """
    Boxes are what let the queue show the ink. A reading with no rectangles is
    a reading a person cannot check.
    """
    case = CASES[0]
    read, _, _ = _read_image(case, "clean", tmp_path)
    assert read["words"], "the engine read nothing at all from a clean render"
    for word in read["words"]:
        left, top, right, bottom = word.box
        assert right > left and bottom > top, word


def test_a_crop_of_a_doubtful_field_is_a_real_image(tmp_path):
    """The picture the reviewer shows. It has to actually open."""
    case = CASES[0]
    image = render.render(case["text"])
    path = render.write(image, str(tmp_path / "crop-source.png"))
    read = ocr.read_image(path)
    field = R.extract(read["text"], read["lines"])["fields"]["total"]
    assert field.box, "the total came off a photograph with no rectangle"

    data = ocr.crop(path, field.box)
    assert data.startswith(b"\x89PNG"), "the crop is not a PNG"
    assert len(data) > 200, "the crop is too small to be a picture of anything"
