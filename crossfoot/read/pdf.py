"""
A PDF is one of two entirely different files, and which one decides everything.

**A text-layer PDF** — an emailed invoice, an order confirmation, a utility
bill — draws its characters as text. The numbers are *in the file*. Reading
them is unzipping a stream and pulling the strings out, and it needs nothing
but the standard library.

**A scanned PDF** is a photograph in a wrapper. It draws one image and stops.
Everything the 55-receipt measurement found applies to it unchanged, because it
*is* that measurement's input with a different extension.

Measured on 24 real PDFs from Wikimedia Commons: 16 scans, 6 text-layer, 2
mixed. The text-layer ones gave up thousands of words of readable text to the
sixty lines below.

That measurement is why `docling` is no longer the answer here. It was the
declared reader, it was never installed, its branch was never covered, and it
is the wrong dependency in both directions at once:

  * for a text-layer PDF it is unnecessary — the text is already there
  * for a scanned PDF it is insufficient — it would OCR the page and inherit
    every number from the photograph measurement, at the cost of a deep ML
    stack in a project whose core has no required dependencies at all

**The honest limit of the measurement.** Those 24 PDFs are archival documents,
because those are the ones that are freely licensed. The population this
actually targets — an Amazon order confirmation, a SaaS invoice, a phone bill —
is almost certainly more text-layer than that sample, and *almost certainly* is
not a number. Nobody has measured it, and this file does not claim otherwise.
"""
import re
import zlib

#: How many text-drawing operators a *picture* has to be carrying before its
#: text is treated as a real layer rather than a stamped page number or a
#: watermark.
#:
#: It applies only when there is an image to compete with, and that condition
#: was the bug the tests found. Calibrated on archival PDFs, this was a flat
#: floor of twenty — and **a receipt is short**. A six-line receipt draws six
#: strings, so a perfectly ordinary text-layer receipt was classified as having
#: no text at all and refused. The floor was measured against the wrong
#: population, which is the same mistake, in miniature, that the 22-receipt
#: corpus made.
TEXT_OPERATOR_FLOOR = 20

TEXT = "text"
SCAN = "scan"
EMPTY = "empty"


def _streams(data: bytes):
    """Every stream in the file, inflated where it is inflated."""
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        chunk = match.group(1)
        try:
            yield zlib.decompress(chunk)
        except zlib.error:
            yield chunk                      # already flat, or a filter we skip


def kind(data: bytes) -> str:
    """
    Which of the two files this is.

    Counts the operators that *draw a string* rather than looking for fonts
    alone: a scanned page routinely carries a font resource it never uses.

    A file with no image in it and any text at all is text — there is nothing
    else it could be, and a short receipt is still a receipt. The floor exists
    only to stop a page number stamped on a scan from passing for a document.

    **What this deliberately does not try to tell you** is whether a text layer
    was authored or added by a scanner's own OCR. The two are not cheaply
    distinguishable — a born-digital invoice with a logo and a scanned page
    with an OCR layer both have images and plenty of text — and guessing would
    mark ordinary invoices unreadable, which is the one path that works. The
    cost of being wrong is bounded by the design: an OCR'd text layer carries
    OCR's errors, and those errors are checked against a bank statement that no
    OCR ever touched.
    """
    operators = 0
    for stream in _streams(data):
        operators += len(re.findall(rb"\)\s*T[Jj]", stream))
        operators += len(re.findall(rb"\]\s*TJ", stream))
    images = len(re.findall(rb"/Subtype\s*/Image", data))

    if not operators:
        return SCAN if images else EMPTY
    if not images:
        return TEXT
    return TEXT if operators > TEXT_OPERATOR_FLOOR else SCAN


_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b",
            b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}


def _unescape(raw: bytes) -> bytes:
    out, index = bytearray(), 0
    while index < len(raw):
        byte = raw[index:index + 1]
        if byte == b"\\" and index + 1 < len(raw):
            following = raw[index + 1:index + 2]
            if following in _ESCAPES:
                out += _ESCAPES[following]
                index += 2
                continue
            octal = re.match(rb"[0-7]{1,3}", raw[index + 1:index + 4])
            if octal:
                out.append(int(octal.group(0), 8) & 0xFF)
                index += 1 + len(octal.group(0))
                continue
        out += byte
        index += 1
    return bytes(out)


def text(data: bytes) -> str:
    """
    Every string the content streams draw, in the order they draw them.

    Deliberately naive. It does not lay out columns, resolve font encodings, or
    reconstruct reading order across a two-column page — and it does not need
    to, because what follows it is a receipt parser that works on lines of
    "label then amount", and a receipt is a single column.

    A file this reads badly is a file the parser then finds no fields in, which
    comes out *unchecked*. That is the same failure mode as a bad photograph
    and it is already handled.
    """
    lines = []
    for stream in _streams(data):
        if not re.search(rb"T[Jj]", stream):
            continue
        for match in re.finditer(rb"(?:\[(.*?)\]\s*TJ)|(?:\((.*?)\)\s*Tj)",
                                 stream, re.S):
            if match.group(2) is not None:
                lines.append(_unescape(match.group(2)))
            else:
                pieces = re.findall(rb"\((.*?)(?<!\\)\)", match.group(1), re.S)
                lines.append(b"".join(_unescape(p) for p in pieces))
    return "\n".join(line.decode("latin-1", "replace") for line in lines)


def read(path: str) -> dict:
    """
    A PDF as text, saying which of the two kinds it was.

    A scan is *not* silently returned as empty text. An empty receipt parses to
    no fields, which comes out unchecked for a reason nobody can act on; naming
    the reason is the difference between "we could not check this" and "this
    file is a picture, and here is what to do about it".
    """
    with open(path, "rb") as handle:
        data = handle.read()

    shape = kind(data)
    if shape in (SCAN, EMPTY):
        return {
            "text": "", "reader": f"pdf ({shape})", "path": path,
            "degraded": True,
            "why": ("this PDF is a scan — it draws a picture of a page rather "
                    "than any text. Reading it needs the same OCR as a "
                    "photograph, and on real receipts that works about one "
                    "time in fifty-five, so it is refused rather than guessed "
                    "at."),
        }

    extracted = text(data)
    return {
        "text": extracted,
        "reader": f"pdf ({shape})",
        "path": path,
        # A file classified as text that yields none is a producer this does not
        # understand -- an encoding, a filter, an object stream. Saying so beats
        # handing on an empty string that parses to a receipt with no fields.
        "degraded": not extracted.strip(),
    }
