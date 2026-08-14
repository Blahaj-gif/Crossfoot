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

#: Where the window drops files when nobody says otherwise. Sensible enough
#: that nobody has to invent one, and visible enough that nobody wonders where
#: their files went -- a hidden temp directory would be tidier and would mean
#: the person could not open, inspect or empty the place their bank statements
#: are sitting.
#:
#: Lives here rather than in the review UI because creating it is intake, not
#: interface -- and because a test that had to import the UI to reach it would
#: need Streamlit, which is an optional extra. That mistake has now been made
#: twice in this project and caught by CI both times.
DEFAULT = "crossfoot-inbox"

#: How much of a file to read when deciding what it is. A statement announces
#: itself in its header row or its first tag; nothing needs the whole file.
SNIFF_BYTES = 4096


def make(folder: str = DEFAULT) -> str:
    """
    Create the drop folder, and make it refuse to be committed.

    The `.gitignore` written inside it is not redundant with the one in the
    repository. This folder ends up holding somebody's bank statements, and it
    travels: people copy it, move it into a project, sync it to a drive. A
    folder that ignores its own contents stays protected wherever it lands,
    which a rule in one repository cannot do.
    """
    os.makedirs(folder, exist_ok=True)
    guard = os.path.join(folder, ".gitignore")
    if not os.path.exists(guard):
        with open(guard, "w", encoding="utf-8") as fh:
            fh.write("# Your bank statements and receipts are in here.\n"
                     "# Nothing in this folder should ever be committed.\n"
                     "*\n")
    return folder


def dropped_file_path(folder: str, name: str):
    """
    Where a dropped file may be written, or None if that name is not a name.

    A browser supplies the filename of an upload, and it is written straight to
    disk — so it is not a name, it is a path. `os.path.join(inbox, "../../.bashrc")`
    leaves the folder entirely and overwrites whatever is there. That is a
    directory traversal in a program whose whole pitch is that it runs on your
    own machine and touches nothing but the folder you gave it.

    Reduced to its last component, then checked to sit directly inside the
    folder regardless — basename alone is not a containment proof on every
    platform, since a Windows name like `C:evil.txt` survives it and resolves
    against the current drive.

    Lives here rather than in the window, because the window is the one module
    the tests are forbidden to import, and a guard the tests cannot reach is a
    guard nobody has checked.
    """
    raw = (name or "").strip()
    if not raw or raw in (".", ".."):
        return None
    # Refused rather than reduced. `os.path.basename` would turn
    # "../../.bashrc" into ".bashrc" and write it, which is safe and is a
    # silent rewrite of the name somebody gave — and a browser has no
    # legitimate reason to send a path here, so the only files this rejects are
    # the ones worth rejecting.
    if any(sep in raw for sep in ("/", "\\", os.sep)) or os.path.splitdrive(raw)[0]:
        return None
    target = os.path.abspath(os.path.join(folder, raw))
    # Belt and braces: whatever the platform makes of the name, it has to land
    # directly in the folder that was asked for.
    if os.path.dirname(target) != os.path.abspath(folder):
        return None
    return target


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
