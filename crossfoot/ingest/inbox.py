"""
A folder you drop things into, and the two questions that answers.

The intake used to be two command-line arguments naming a statement file and a
receipts directory, which is fine for the second run and hostile for the first:
somebody with a download of their bank export and a phone folder of photographs
has to know which is which and where each goes.

So: one folder. Drop everything in it. This works out which files are
statements and which are receipts by **looking at them**, not by their names or
extensions -- a bank export saved as `download (3).csv` and a receipt saved as
`statement.pdf` are both entirely normal, and a rule based on filenames gets
both wrong.

Deliberately not a daemon. `watch` is a loop a person starts and stops, not a
background service, because a service that reconciles your finances while you
are not looking is exactly the thing this project argues against.
"""
import os
import time

from crossfoot.ingest import statement as S

#: Suffixes worth opening at all. Everything else in the folder is left alone:
#: an inbox is somebody's own directory and this has no business reading their
#: unrelated files to find out what they are.
CONSIDERED = (".csv", ".ofx", ".qfx", ".txt", ".text", ".md", ".pdf",
              ".jpg", ".jpeg", ".png", ".heic", ".webp", ".tif", ".tiff", ".bmp")

#: How much of a file to read when deciding what it is. A statement announces
#: itself in its header row or its first tag; nothing needs the whole file.
SNIFF_BYTES = 4096


def looks_like_a_statement(path: str) -> bool:
    """
    Whether this file is a bank export, decided by reading it.

    Two signals, both from the content: an OFX transaction block, or a CSV
    header row that names a date column and an amount column. The second reuses
    the same header table the parser uses, so a file this says is a statement
    is a file the parser can actually read -- rather than two independent
    guesses that disagree in front of the user.
    """
    if os.path.splitext(path)[1].lower() not in (".csv", ".ofx", ".qfx", ".txt"):
        return False
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = fh.read(SNIFF_BYTES)
    except OSError:
        return False

    if "<STMTTRN>" in head.upper():
        return True

    first = head.splitlines()[0] if head.splitlines() else ""
    columns = S._column_map(next(iter([first.split(",")]), []))
    return "date" in columns and (
        "amount" in columns or "debit" in columns or "credit" in columns)


def sort(folder: str) -> dict:
    """
    What is in this folder, split into statements, receipts and the ignored.

    Returns all three. The third is not noise: a person who drops a file in and
    sees nothing happen needs to be told it was skipped and why, or they will
    conclude the tool is broken when it is being careful.
    """
    statements, receipts, ignored = [], [], []
    if not os.path.isdir(folder):
        return {"statements": [], "receipts": [], "ignored": [],
                "problem": f"{folder} is not a folder"}

    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isfile(path) or name.startswith("."):
            continue
        if os.path.splitext(name)[1].lower() not in CONSIDERED:
            ignored.append((name, "not a document type this reads"))
            continue
        (statements if looks_like_a_statement(path) else receipts).append(path)

    problem = None
    if not statements:
        problem = ("no bank statement found — drop in the CSV or OFX your bank "
                   "exports. Every verdict here is about what is *missing* from "
                   "a statement, so there is nothing to say without one.")
    elif len(statements) > 1:
        # Not merged. Two exports may overlap, and silently concatenating them
        # would invent duplicate charges -- from the tool whose headline
        # finding is duplicate charges.
        problem = (f"{len(statements)} files look like statements "
                   f"({', '.join(os.path.basename(p) for p in statements)}). "
                   "Reconcile one at a time: merging two exports that overlap "
                   "would manufacture the duplicates this is meant to find.")
    return {"statements": statements, "receipts": receipts, "ignored": ignored,
            "problem": problem}


def fingerprint(folder: str):
    """
    A cheap value that changes when the folder's contents change.

    Names, sizes and modification times. Enough to notice a new file, a
    replaced one, or a deletion, and it costs one `stat` per file rather than
    reading anything.
    """
    if not os.path.isdir(folder):
        return ()
    out = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        try:
            info = os.stat(path)
        except OSError:
            continue
        out.append((name, info.st_size, int(info.st_mtime)))
    return tuple(out)


def watch(folder: str, on_change, interval: float = 2.0, stop=None):
    """
    Call `on_change(sorted_folder)` whenever the folder's contents change.

    A loop a person starts and stops in their own terminal, not a daemon and
    not a service. Polling rather than filesystem events, because the events
    APIs differ per platform and would each be a dependency, and two seconds is
    imperceptible for a folder somebody is dropping files into by hand.

    `stop` is a callable returning True when it should end -- so a caller, and
    a test, can end it without a signal.
    """
    previous = None
    while not (stop and stop()):
        current = fingerprint(folder)
        if current != previous:
            previous = current
            on_change(sort(folder))
        time.sleep(interval)
