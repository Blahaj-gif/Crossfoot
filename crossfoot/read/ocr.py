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
#: Why the import failed, when it failed for a reason other than absence.
#:
#: This existed as a bare `except Exception: HAVE_TESSERACT = False`, and the
#: consequence was measured the hard way. A file named `select.py` sitting in
#: the working directory shadows the standard library's `select`, which breaks
#: `socket`, which breaks `pandas`, which pytesseract imports -- so the import
#: raised, the flag went False, and Crossfoot told somebody with a working
#: Tesseract installation to go and install Tesseract. The engine was present,
#: on PATH, and functioning.
#:
#: An absent package and a broken one need different sentences. Guessing
#: "absent" for both sends people to reinstall what they already have, and it
#: is the tool being confidently wrong about a fact it could simply report.
IMPORT_ERROR = None

try:                                        # pragma: no cover - environment
    import pytesseract
    from PIL import Image
    HAVE_TESSERACT = True
except ImportError:                         # pragma: no cover - environment
    pytesseract = Image = None
    HAVE_TESSERACT = False
except Exception as _error:                 # pragma: no cover - environment
    pytesseract = Image = None
    HAVE_TESSERACT = False
    IMPORT_ERROR = f"{type(_error).__name__}: {_error}"

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

#: Fewer words than this off a whole receipt and the engine has failed, however
#: sure it is of the few it found. Even a card slip prints a merchant, a date,
#: an amount and a card number. Deliberately low: this is a floor under
#: "obviously failed", not a judgement about how much a receipt should say.
MINIMUM_WORDS = 8

_reader = None


class NoEngine(Exception):
    """No OCR backend is installed, so a photograph cannot be read at all."""


#: Set to opt into a one-time model download for the pure-Python engine.
#:
#: The default is off, and the *reason* is worth being precise about, because
#: the first version of this got it wrong. The promise this project makes is
#: that **your documents never leave the machine**. It is not "no network
#: request is ever made by anything" -- and conflating the two killed the only
#: OCR path available to somebody who cannot install a system binary, which is
#: most people. Fetching a public model file once is not sending anyone's
#: receipts anywhere.
#:
#: So it stays off by default, because a tool that silently downloads several
#: hundred megabytes on first run has surprised somebody, and it is on by one
#: explicit environment variable with the message saying so.
ALLOW_MODEL_DOWNLOAD = "CROSSFOOT_ALLOW_MODEL_DOWNLOAD"


def _tesseract_binary_works() -> bool:
    """
    Whether the *engine* is there, not just the Python wrapper around it.

    `pip install crossfoot[ocr]` installs pytesseract, which imports perfectly
    on a machine with no tesseract binary anywhere -- so `HAVE_TESSERACT` was
    True and every photograph raised TesseractNotFoundError out of the middle
    of a run. The wrapper being importable says nothing about the program it
    wraps, and asking it costs one subprocess at import.
    """
    if not HAVE_TESSERACT:
        return False
    try:                                    # pragma: no cover - environment
        pytesseract.get_tesseract_version()
        return True
    except Exception:                       # pragma: no cover - environment
        return False


def available() -> list:
    """
    Which engines can actually read a photograph right now.

    "Installed" is not the question a person cares about; "will this work" is.
    Tesseract must have its binary, and easyocr must have weights on disk or
    permission to fetch them once.
    """
    engines = []
    if _tesseract_binary_works():
        engines.append("tesseract")
    if HAVE_EASYOCR:
        engines.append("easyocr")
    return engines


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
    if _tesseract_binary_works():
        return _read_with_tesseract(path)
    if HAVE_EASYOCR:
        return _read_with_easyocr(path)

    name = os.path.basename(path)
    if IMPORT_ERROR:
        raise NoEngine(
            f"{name} is a photograph, and the OCR engine is installed but "
            f"would not load:\n"
            f"  {IMPORT_ERROR}\n"
            "This is not a missing package and reinstalling will not fix it. "
            "The usual cause is another module shadowing one it needs — a file "
            "in the working directory named after a standard library module, "
            "such as select.py, socket.py or json.py — or a broken numpy or "
            "pandas in this environment. Run `python -c \"import pytesseract\"` "
            "to see the whole traceback.")
    if HAVE_TESSERACT:
        # The wrapper is installed and the program it wraps is not, which is
        # what `pip install crossfoot[ocr]` alone leaves you with. Saying "no
        # OCR engine installed" here would send somebody to reinstall the
        # thing they already have.
        raise NoEngine(
            f"{name} is a photograph. pytesseract is installed but the "
            "tesseract program itself is not — pip cannot install it, because "
            "it is not a Python package.\n"
            "  Windows: winget install UB-Mannheim.TesseractOCR\n"
            "  macOS:   brew install tesseract\n"
            "  Linux:   apt install tesseract-ocr\n"
            "Or, if you cannot install software on this machine, "
            "`pip install 'crossfoot[ocr-heavy]'` needs nothing but Python.")
    raise NoEngine(
        f"{name} is a photograph and nothing here can read one yet.\n"
        "  pip install 'crossfoot[ocr]'        - fast, needs the tesseract program\n"
        "  pip install 'crossfoot[ocr-heavy]'  - slower, needs nothing but Python\n"
        "Until then this file is refused rather than treated as an empty "
        "receipt, because reading a photograph as text produces noise that a "
        "parser will find amounts in.")


#: Page segmentation mode 6: "assume a single uniform block of text".
#:
#: Not a tuning knob. The default mode runs layout analysis first, decides a
#: receipt is a multi-column document, and then **discards most of the amount
#: column**. Measured on a clean render of a Waitrose receipt it found one of
#: five amounts, and the one it found landed in a block of its own, so no line
#: had a label and a number on it and every field came back empty. The whole
#: photograph path was broken in a way no amount of testing with fake data
#: could have shown, because the fake supplied the words layout analysis was
#: throwing away.
#:
#: A till receipt *is* a single uniform block of text. Saying so takes it from
#: one amount in five to four, with labels and their numbers on the same line.
PSM = os.getenv("CROSSFOOT_TESSERACT_PSM", "6").strip() or "6"


#: Below this many pixels of character height the engine stops reading letters
#: and starts reading shapes: TOTAL as "oral", TAX as "TAK", SUBTOTAL as
#: "susToTAL". The *amounts* survive, because digits are simpler, but the
#: labels do not -- so no line has a label and a number on it and every field
#: comes back empty. That is a phone held at arm's length, and on the corpus at
#: 45% scale it is 2 receipts read exactly out of 22.
#:
#: The trigger is character height rather than page width, and that distinction
#: is the whole of what makes this safe. A width rule was measured first and it
#: was a clear loss: enlarging every image below 1000px wide cost accuracy on
#: seven of the eleven degradations and produced silent passes on nine of them,
#: including on a clean render, because a second reading of an image that was
#: already legible is not a better reading -- it is a *different* wrong one, and
#: a wrong reading that is self-consistent reconciles. Height separates the two
#: populations without being fitted to them: the ten degradations that read
#: well sit at 15-18px, and the two that fail sit at 8px.
MINIMUM_HEIGHT = 11

#: What to enlarge to. Also measured, and lower than Tesseract's own advice of
#: about 30px, because more is not better here: the corpus reads best at the
#: density it was already being read at, and pushing past it buys interpolation
#: artefacts rather than detail.
TARGET_HEIGHT = 16

#: A receipt occupying a corner of a 12-megapixel frame can report a tiny median
#: height, and the scale that implies would ask Pillow for an image of some
#: absurd size. Enlarging past this has never helped anything measured here.
MAXIMUM_SCALE = 4.0


#: How bright a pixel has to be, between the darkest and lightest of the frame,
#: to count as paper rather than as the table the paper is on.
PAPER_BRIGHTNESS = 0.72

#: How much of a row has to be paper before the row is inside the document.
PAPER_COVERAGE = 0.5

#: Pulled *in* from the detected edge, not out. Measured, and the measurement
#: was emphatic: a crop twenty pixels too generous left a sliver of the desk in
#: frame, and a sliver was enough to take the same receipt from 121 words back
#: to zero. The threshold Tesseract picks is global, so one dark edge poisons
#: the whole page.
PAPER_INSET = 0.015

#: A detected region this close to the whole frame means the photograph is
#: already all document, and cropping it would only shave the margins off a
#: page that was never the problem.
PAPER_LEAVE_ALONE = 0.95


def _paper(grey):                        # pragma: no cover - needs Pillow
    """
    Where the document is in the frame, or None if the frame is all document.

    A receipt on a desk is a bright region surrounded by something darker, and
    Tesseract binarises the *whole image* against one threshold -- so the desk
    decides where the threshold falls and the ink on the paper ends up on the
    wrong side of it. This is not a small effect. A flat, sharp, entirely
    legible scan of a receipt on a blue desk mat produced **zero words** at
    every page segmentation mode; cropped to the paper it produced 114 words at
    71% confidence. Nothing in the rendered corpus could have found that,
    because a rendered receipt is paper edge to edge and has no desk in it.

    Worked out on a thumbnail, because this asks where the paper is rather than
    what it says. Returns None whenever the answer is not clear -- a photograph
    with no contrast between document and background, or one that is already
    all document -- since a crop that is merely plausible can cut the total off
    the bottom of a receipt.
    """
    small = grey.copy()
    small.thumbnail((400, 400), Image.BILINEAR)
    width, height = small.size
    if width < 20 or height < 20:
        return None
    pixels = small.load()

    values = sorted(pixels[x, y] for y in range(height) for x in range(width))
    floor, ceiling = values[len(values) // 20], values[-len(values) // 20]
    if ceiling - floor < 40:
        return None                      # nothing stands out from anything
    cut = floor + (ceiling - floor) * PAPER_BRIGHTNESS

    rows = [y for y in range(height)
            if sum(pixels[x, y] > cut for x in range(width))
            > width * PAPER_COVERAGE]
    columns = [x for x in range(width)
               if sum(pixels[x, y] > cut for y in range(height))
               > height * PAPER_COVERAGE]
    if not rows or not columns:
        return None

    scale = grey.width / width
    inset = PAPER_INSET * max(grey.width, grey.height)
    box = (max(0, int(columns[0] * scale + inset)),
           max(0, int(rows[0] * scale + inset)),
           min(grey.width, int((columns[-1] + 1) * scale - inset)),
           min(grey.height, int((rows[-1] + 1) * scale - inset)))
    if box[2] - box[0] < 50 or box[3] - box[1] < 50:
        return None
    area = (box[2] - box[0]) * (box[3] - box[1])
    if area >= grey.width * grey.height * PAPER_LEAVE_ALONE:
        return None
    return box


def _tesseract_words(path, scale):       # pragma: no cover - needs the binary
    """
    One reading of one image, optionally enlarged first, boxes in *file*
    coordinates.

    Dividing the boxes back down is not tidiness. Every box comes off the image
    the engine read, and `crop` opens the image on disk -- so keeping the
    enlarged coordinates would show a reviewer a patch of paper from somewhere
    else on the receipt, confidently labelled as the total. The same applies to
    the crop: the offset has to be added back or every rectangle points at the
    wrong part of the page.
    """
    # Greyscale before anything else. Measured: handing Tesseract the RGB file
    # of a Swiss restaurant receipt gave 162 words at 42% confidence, and the
    # same file converted first gave 106 words at 56% -- fewer words because
    # the extra ones were the wood grain of the table.
    image = Image.open(path).convert("L")
    box = _paper(image)
    if box:
        image = image.crop(box)
    left, top = (box[0], box[1]) if box else (0, 0)

    if scale != 1.0:
        image = image.resize((round(image.width * scale),
                              round(image.height * scale)), Image.LANCZOS)
    data = pytesseract.image_to_data(image, config=f"--psm {PSM}",
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
        words.append(Word(text, confidence,
                          left + round(data["left"][index] / scale),
                          top + round(data["top"][index] / scale),
                          round(data["width"][index] / scale),
                          round(data["height"][index] / scale),
                          line=(data["block_num"][index], data["par_num"][index],
                                data["line_num"][index])))
    return words


def _read_with_tesseract(path):          # pragma: no cover - needs the binary
    """
    Read it, and if the ink turns out to be too small to read, read it again.

    The second pass is triggered by the first pass's own measurement of the
    page, so the decision is a property of the image rather than of the answer.
    That matters: choosing between two readings on which one *reconciles* would
    be a machine for manufacturing silent passes.
    """
    words = _tesseract_words(path, 1.0)
    if not words:
        return _assemble(words, "tesseract", path)

    heights = sorted(word.height for word in words)
    median = heights[len(heights) // 2]
    if 0 < median < MINIMUM_HEIGHT:
        scale = min(TARGET_HEIGHT / median, MAXIMUM_SCALE)
        # `or words` only for a second pass that read *nothing*, which is a
        # failed reading rather than a worse one.
        words = _tesseract_words(path, scale) or words
    return _assemble(words, "tesseract", path)


def _read_with_easyocr(path):            # pragma: no cover - needs the weights
    global _reader
    if _reader is None:
        allowed = os.getenv(ALLOW_MODEL_DOWNLOAD, "").strip().lower() in (
            "1", "true", "yes")
        try:
            _reader = easyocr.Reader(["en"], gpu=False,
                                     download_enabled=allowed)
        except Exception as e:
            # Off by default because several hundred megabytes arriving
            # unannounced is a surprise, not because fetching a public model
            # file would break the promise. The promise is about *your
            # documents*, and no document is involved in downloading a model.
            raise NoEngine(
                f"easyocr has no language model on this machine yet ({e}).\n"
                f"Set {ALLOW_MODEL_DOWNLOAD}=1 to let it fetch one: about "
                "100 MB, once, from easyocr's own release, and none of your "
                "receipts are involved. Your documents still never leave this "
                "machine; that promise is about them, not about a model file."
            ) from e
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
    # A ratio has no opinion about how much was read. Measured on a photograph
    # of a Dutch fuel receipt, the engine returned **two words**, was sure of
    # both, and the reading scored 100% confident and not degraded -- so a
    # receipt the engine had almost entirely failed to read was the most
    # trusted reading in the batch. Two words is a failed reading that happens
    # to contain no doubt, which is not the same as a good one, and a receipt
    # yielding "TOTAL 5.00" and nothing else would have been believed on the
    # strength of having nothing to disagree with.
    too_little = len(words) < MINIMUM_WORDS
    return {
        "text": "\n".join(line["text"] for line in lines),
        "lines": lines,
        "words": words,
        "reader": engine,
        "path": path,
        "degraded": ratio > 0.2 or too_little,
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
