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
    """What is available, for `get_data_sources`-style honesty in the UI."""
    return (["docling"] if HAVE_DOCLING else []) + ["plain text"]


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

    suffix = os.path.splitext(path)[1].lower()
    if suffix in PLAIN_SUFFIXES or not HAVE_DOCLING:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as e:
            raise UnreadableDocument(f"{path}: {e}") from e
        if suffix not in PLAIN_SUFFIXES and not HAVE_DOCLING:
            # Read as bytes-turned-text because nothing better is installed.
            # Say so: a PDF read this way is mostly binary noise, and a total
            # "found" in it would be an artefact.
            return {"text": text, "reader": "plain text (docling not installed)",
                    "path": path, "degraded": True}
        return {"text": text, "reader": "plain text", "path": path,
                "degraded": False}

    try:                                    # pragma: no cover - needs docling
        result = _Converter().convert(path)
        return {"text": result.document.export_to_markdown(),
                "reader": "docling", "path": path, "degraded": False}
    except Exception as e:                  # pragma: no cover - needs docling
        raise UnreadableDocument(f"docling could not read {path}: {e}") from e
