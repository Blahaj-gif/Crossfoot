"""
Text out of a file, by whatever reader is installed.

Docling does layout, reading order and table structure with sixty thousand
stars behind it, and competing with that would be the whole project spent on
the part that is already solved. So this is a seam, not an implementation: use
Docling where it is present, plain text where it is not, and say which happened
so a verdict can never be built on a reader nobody knew was in use.

Deliberately an optional dependency. The verdict layer is arithmetic and
stdlib, and someone who only wants to reconcile numbers they already have
should not be made to install a machine-learning stack to do it.
"""
import os

from crossfoot.read import ocr, pdf

#: Read once at import so the answer cannot change mid-run and produce two
#: different readings of the same document in one session.
try:                                        # pragma: no cover - environment
    from docling.document_converter import DocumentConverter as _Converter
    HAVE_DOCLING = True
except Exception:                           # pragma: no cover - environment
    _Converter = None
    HAVE_DOCLING = False

PLAIN_SUFFIXES = (".txt", ".text", ".md")


class UnreadableDocument(Exception):
    """No installed reader can turn this file into text."""


def readers() -> list:
    """What is available, stated rather than implied."""
    return ((["docling"] if HAVE_DOCLING else [])
            + [f"ocr:{name}" for name in ocr.available()]
            + ["plain text"])


def read(path: str) -> dict:
    """
    `{"text": ..., "reader": ..., "path": ...}`, or raise.

    The reader is returned rather than logged because it belongs in the
    provenance of every number that comes out of the text -- a total read by
    Docling from a structured PDF and one read off a plain-text dump are not
    equally trustworthy, and the queue should be able to say which it has.
    """
    if not os.path.isfile(path):
        raise UnreadableDocument(f"{path} is not a file")

    # A photograph, which is what almost every receipt actually is. Routed
    # before anything else because reading a JPEG as text produces binary noise
    # that a parser will cheerfully find amounts in.
    if ocr.is_image(path):
        try:
            return ocr.read_image(path)
        except ocr.NoEngine as e:
            raise UnreadableDocument(str(e)) from e

    suffix = os.path.splitext(path)[1].lower()

    # A PDF, read with the standard library and nothing else. This used to fall
    # through to "open it as text and admit it is noise" unless docling was
    # installed, which it never was -- so the whole PDF path was a promise with
    # no implementation behind it.
    #
    # Measured on 24 real PDFs: two thirds are scans, which no reader can help
    # with, and the text-layer third gives up thousands of words to sixty lines
    # of zlib and a regular expression. docling is unnecessary for the first
    # kind and insufficient for the second.
    if suffix == ".pdf":
        try:
            return pdf.read(path)
        except OSError as e:
            raise UnreadableDocument(f"{path}: {e}") from e

    if suffix in PLAIN_SUFFIXES or not HAVE_DOCLING:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as e:
            raise UnreadableDocument(f"{path}: {e}") from e
        if suffix not in PLAIN_SUFFIXES and not HAVE_DOCLING:
            # Some other binary format nothing here reads. Say so rather than
            # letting a parser find amounts in the byte soup.
            return {"text": text, "reader": "plain text (nothing better installed)",
                    "path": path, "degraded": True}
        return {"text": text, "reader": "plain text", "path": path,
                "degraded": False}

    try:                                    # pragma: no cover - needs docling
        result = _Converter().convert(path)
        return {"text": result.document.export_to_markdown(),
                "reader": "docling", "path": path, "degraded": False}
    except Exception as e:                  # pragma: no cover - needs docling
        raise UnreadableDocument(f"docling could not read {path}: {e}") from e
