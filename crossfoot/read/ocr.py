"""
Getting text off a photograph, and keeping track of where on the page it was.

This is the hole the pre-publication read-through named as the largest thing
between Crossfoot and a fair test. Docling reads a PDF invoice; nothing read a
photograph of a till receipt, which is what almost every receipt actually is.
Without this the audience is people with emailed supplier invoices. With it,
it is people with receipts.

**Optional, and honest about being optional.** Tesseract is a system package,
not a Python one, and requiring it would mean the checking layer -- arithmetic
and stdlib -- could not be installed by somebody who only wants to reconcile
numbers they already have. So this is a seam with two backends and a truthful
answer when neither is present:

    pytesseract   the common case; needs the tesseract binary installed
    easyocr       pure-Python weights, no system package, much heavier

Nothing here reaches the network. Both engines run locally on already-installed
data, which is the property the whole project rests on, and there is deliberately
no cloud backend -- an OCR API would be the single line of code that turns "your
receipts never leave this machine" into a lie.

**Every word keeps its box.** That is not decoration: it is what lets the review
queue show a person the actual patch of paper a doubtful total was read from,
instead of asking them to trust a number or go and find the original. A field's
provenance is the line of text *and* the rectangle it came from.
"""
import os

#: Read once at import so the answer cannot change mid-run and produce two
#: different readings of the same photograph in one session.
try:                                        # pragma: no cover - environment
    import pytesseract
    from PIL import Image
    HAVE_TESSERACT = True
except Exception:                           # pragma: no cover - environment
    pytesseract = Image = None
    HAVE_TESSERACT = False

try:                                        # pragma: no cover - environment
    import easyocr
    HAVE_EASYOCR = True
except Exception:                           # pragma: no cover - environment
    easyocr = None
    HAVE_EASYOCR = False

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".heic", ".webp", ".tif", ".tiff", ".bmp")

#: Below this, a word is not trusted to be what the engine says it is. Tesseract
#: reports 0-100 per word; this is the point at which a smudged digit becomes a
#: confident wrong number, which is the failure this project exists to prevent.
WORD_CONFIDENCE = 60

_reader = None


class NoEngine(Exception):
    """No OCR backend is installed, so a photograph cannot be read at all."""


def available() -> list:
    """Which engines are installed, for the UI to state rather than imply."""
    return ([n for n, have in (("tesseract", HAVE_TESSERACT),
                               ("easyocr", HAVE_EASYOCR)) if have])


def is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_SUFFIXES


class Word:
    """One recognised word: what it says, how sure, and where it sat."""

    __slots__ = ("text", "confidence", "left", "top", "width", "height", "line")

    def __init__(self, text, confidence, left, top, width, height, line=0):
        self.text = text
        self.confidence = confidence
        self.left, self.top = left, top
        self.width, self.height = width, height
        self.line = line

    @property
    def box(self):
        """(left, top, right, bottom) — what `crop` needs and what a person sees."""
        return (self.left, self.top, self.left + self.width, self.top + self.height)

    def __repr__(self):
        return f"<Word {self.text!r} {self.confidence:.0f}% at {self.box}>"


def _lines_from(words) -> list:
    """
    Words grouped into lines of text, in reading order.

    The receipt parser works on lines -- "TOTAL" followed by an amount -- so
    the whole point of OCR here is to reconstruct lines faithfully. Grouping is
    by the engine's own line index where it gives one, because inventing a
    line-breaking rule out of pixel rows is how "SUB TOTAL 13.50" becomes two
    lines and the subtotal stops being found.
    """
    by_line = {}
    for word in words:
        by_line.setdefault(word.line, []).append(word)
    out = []
    for index in sorted(by_line):
        row = sorted(by_line[index], key=lambda w: w.left)
        out.append({"text": " ".join(w.text for w in row), "words": row,
                    "line": index})
    return out


def read_image(path: str) -> dict:
    """
    A photograph as lines of text, each word carrying its confidence and box.

    Raises `NoEngine` rather than returning empty text. An unreadable receipt
    that silently produces no lines becomes a charge marked *unchecked* for a
    reason nobody can act on; the exception names the package to install.
    """
    if HAVE_TESSERACT:
        return _read_with_tesseract(path)
    if HAVE_EASYOCR:
        return _read_with_easyocr(path)
    raise NoEngine(
        f"{os.path.basename(path)} is a photograph and no OCR engine is "
        "installed. `pip install 'crossfoot[ocr]'` and install the tesseract "
        "binary for your platform, or `pip install 'crossfoot[ocr-heavy]'` for "
        "a pure-Python engine that needs no system package. Without one, this "
        "file cannot be read at all — which is why it is refused rather than "
        "quietly treated as an empty receipt.")


def _read_with_tesseract(path):          # pragma: no cover - needs the binary
    data = pytesseract.image_to_data(Image.open(path),
                                     output_type=pytesseract.Output.DICT)
    words = []
    for index, text in enumerate(data["text"]):
        text = (text or "").strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            confidence = -1.0
        if confidence < 0:
            continue                     # tesseract's marker for "not a word"
        words.append(Word(text, confidence, data["left"][index], data["top"][index],
                          data["width"][index], data["height"][index],
                          line=(data["block_num"][index], data["par_num"][index],
                                data["line_num"][index])))
    return _assemble(words, "tesseract", path)


def _read_with_easyocr(path):            # pragma: no cover - needs the weights
    global _reader
    if _reader is None:
        # download_enabled=False on purpose: the weights must already be on
        # this machine. An OCR engine that fetches a model the first time it
        # runs is an OCR engine that made a network request, and the promise
        # is that nothing here does.
        _reader = easyocr.Reader(["en"], gpu=False, download_enabled=False)
    words = []
    for index, (box, text, confidence) in enumerate(_reader.readtext(path)):
        text = (text or "").strip()
        if not text:
            continue
        xs = [point[0] for point in box]
        ys = [point[1] for point in box]
        left, top = int(min(xs)), int(min(ys))
        words.append(Word(text, float(confidence) * 100, left, top,
                          int(max(xs)) - left, int(max(ys)) - top,
                          line=round(top / 12)))
    return _assemble(words, "easyocr", path)


def _assemble(words, engine, path) -> dict:
    """
    The shape `read.document` hands on, plus everything the queue needs to show
    somebody the paper.

    `degraded` is set when the engine was unsure often enough that the reading
    should be treated as evidence rather than as figures -- a fifth of the
    words below threshold is a photograph worth retaking, and saying so is
    cheaper than a wrong total in a ledger that claims to be checked.
    """
    lines = _lines_from(words)
    doubtful = [w for w in words if w.confidence < WORD_CONFIDENCE]
    ratio = len(doubtful) / len(words) if words else 1.0
    return {
        "text": "\n".join(line["text"] for line in lines),
        "lines": lines,
        "words": words,
        "reader": engine,
        "path": path,
        "degraded": ratio > 0.2 or not words,
        "confidence": round(100 * (1 - ratio), 1),
        "doubtful": [w.text for w in doubtful],
    }


def crop(path: str, box, pad: int = 8):
    """
    The patch of paper a number was read from, as PNG bytes.

    This is what makes a doubtful total actionable rather than merely flagged:
    the queue shows the ink instead of asking somebody to go and find the
    original and squint at it. Padded, because a box drawn tight around a digit
    is unreadable to a human even when it was perfectly readable to the engine.
    """
    if not HAVE_TESSERACT:               # PIL arrives with the tesseract extra
        raise NoEngine("cropping needs Pillow: pip install 'crossfoot[ocr]'")
    import io                            # pragma: no cover - needs Pillow

    with Image.open(path) as image:      # pragma: no cover - needs Pillow
        left, top, right, bottom = box
        patch = image.crop((max(0, left - pad), max(0, top - pad),
                            min(image.width, right + pad),
                            min(image.height, bottom + pad)))
        buffer = io.BytesIO()
        patch.save(buffer, format="PNG")
        return buffer.getvalue()
