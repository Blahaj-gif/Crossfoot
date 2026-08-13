"""
What works on this machine, what does not, and the exact line that fixes it.

Written because the failures were arriving one at a time, in the middle of
runs, phrased as exceptions. Somebody would install the tool, point it at a
folder of photographs, and learn only then that photographs need a separate
program — and the sentence telling them so came out of a traceback.

One place asks every question up front and answers in the order a person cares
about: **what can I do right now**, then what is missing and what it costs.

Deliberately never network-dependent and never slow. Every probe here is an
import or a subprocess that already happened at start-up, so this can run on a
train, and so the review window can render it without a spinner.
"""
import shutil
import sys

#: A capability is what a person wants to do, not the package that does it.
#: "Read photographs of receipts" is a thing somebody wants; "pytesseract" is
#: an implementation detail they should never need to learn unless it breaks.
CORE = "core"
OPTIONAL = "optional"


class Capability:
    __slots__ = ("name", "ok", "kind", "detail", "fix")

    def __init__(self, name, ok, kind, detail, fix=""):
        self.name = name
        self.ok = ok
        self.kind = kind
        self.detail = detail
        self.fix = fix


def report() -> list:
    """Every capability, working ones first."""
    from crossfoot.read import document, ocr

    engines = ocr.available()
    photographs = bool(engines)

    if photographs:
        photo_detail = f"reading photographs with {', '.join(engines)}"
        photo_fix = ""
    elif ocr.HAVE_TESSERACT:
        photo_detail = ("pytesseract is installed but the tesseract program is "
                        "not — pip cannot install it, because it is not a "
                        "Python package")
        photo_fix = ("Windows: winget install UB-Mannheim.TesseractOCR  |  "
                     "macOS: brew install tesseract  |  "
                     "Linux: apt install tesseract-ocr")
    else:
        photo_detail = "photographs of receipts cannot be read yet"
        photo_fix = ("pip install 'crossfoot[ocr]' (fast, needs the tesseract "
                     "program) or 'crossfoot[ocr-heavy]' (slower, needs nothing "
                     "but Python)")

    try:
        import streamlit                            # noqa: F401
        window = True
    except ImportError:
        window = False

    return [
        Capability("Bank statements (CSV, OFX)", True, CORE,
                   "reading and checking a statement is complete"),
        # Named separately and named first among the findings, because it is
        # the one thing that works with nothing installed and no receipts at
        # all -- and it is the finding most likely to be worth money.
        Capability("Finding charges you were billed twice", True, CORE,
                   "works on the statement alone, with no receipts"),
        Capability("Text receipts", True, CORE,
                   "reading .txt receipts and checking their arithmetic"),
        Capability("PDF receipts", document.HAVE_DOCLING, OPTIONAL,
                   "reading PDF invoices with Docling" if document.HAVE_DOCLING
                   else "PDF invoices are read as plain text and marked degraded",
                   "" if document.HAVE_DOCLING else "pip install 'crossfoot[read]'"),
        Capability("Photographs of receipts", photographs, OPTIONAL,
                   photo_detail, photo_fix),
        Capability("The review window", window, OPTIONAL,
                   "drag-and-drop, review and export in a browser" if window
                   else "the window that does everything without a terminal",
                   "" if window else "pip install 'crossfoot[ui]'"),
    ]


def can_do_anything_useful() -> bool:
    """
    Whether there is any point running at all.

    True on a bare install, deliberately: a statement on its own already finds
    double-billing, so nobody is ever told to install something before they can
    get an answer.
    """
    return all(c.ok for c in report() if c.kind == CORE)


def summary() -> str:
    """One line for the top of a window or a log."""
    working = [c for c in report() if c.ok]
    missing = [c for c in report() if not c.ok]
    text = f"{len(working)} of {len(working) + len(missing)} things working"
    if missing:
        text += " — missing: " + ", ".join(c.name.lower() for c in missing)
    return text


def render() -> str:
    """
    The plain-text report, for `crossfoot doctor`.

    Working things first. A list that opens with four red crosses reads as
    "this is broken", when the truth is usually "this does most of what you
    want and one optional piece is absent".
    """
    lines = ["What works on this machine", "=" * 26, ""]
    entries = report()

    for capability in [c for c in entries if c.ok]:
        lines.append(f"  yes   {capability.name}")
        lines.append(f"        {capability.detail}")
    missing = [c for c in entries if not c.ok]
    if missing:
        lines.append("")
        lines.append("Not yet")
        lines.append("-" * 7)
        for capability in missing:
            lines.append(f"  no    {capability.name}")
            lines.append(f"        {capability.detail}")
            if capability.fix:
                lines.append(f"        fix: {capability.fix}")

    lines.append("")
    if can_do_anything_useful():
        lines.append("You can already drop a bank export in and find out whether")
        lines.append("you were billed twice for anything. That needs no receipts")
        lines.append("and nothing else installed.")
    lines.append("")
    lines.append(f"python {sys.version.split()[0]} at {sys.executable}")
    return "\n".join(lines)


def launcher_hint() -> str:
    """Where the double-clickable launcher lives, if this install has one."""
    return ("launch/crossfoot.bat" if sys.platform == "win32" else
            "launch/crossfoot.command" if sys.platform == "darwin" else
            "launch/crossfoot.sh")


def python_is_on_the_path() -> bool:
    """
    Whether `crossfoot` will be findable in a fresh terminal.

    A pip install into a Python that is not on PATH produces the single most
    confusing failure available: the install succeeds and the command does not
    exist. Worth detecting so the answer can be given before the question.
    """
    return shutil.which("crossfoot") is not None
