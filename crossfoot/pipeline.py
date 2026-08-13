"""
Statement plus receipts, in one place, for everything that needs them.

This exists because there were two copies and they had already drifted. The
command line attached the statement's currency to every charge and the review
UI did not, so the cross-currency check fired for `crossfoot check` and was
silently dead in the window where a person actually approves things — the two
surfaces disagreeing about the same two files, which is the exact failure the
CLI's own docstring warned about while a second copy sat in the UI.

Everything that reads documents goes through here: the CLI, the reviewer, and
whatever comes next. Nothing here writes anything, and nothing here can clear a
queue item — the decision log is not imported at all.
"""
import os

from crossfoot.ingest import duplicates as DUP
from crossfoot.ingest import statement as S
from crossfoot.match import candidates as M
from crossfoot.read import document
from crossfoot.read import receipt as R
from crossfoot.review import queue as Q


class Refused(Exception):
    """The inputs cannot be used. Carries the exit code a caller should give."""

    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def receipts_in(directory: str):
    """
    Every readable receipt in a folder, and a note about the ones that were not.

    Unreadable files are returned rather than skipped. A receipt that could not
    be opened is a charge that will land in the queue as unchecked for a reason
    the person can fix, and silently dropping it makes that look like a receipt
    they never took.
    """
    receipts, unreadable = [], []
    if not os.path.isdir(directory):
        return receipts, unreadable
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        try:
            read = document.read(path)
        except document.UnreadableDocument as e:
            unreadable.append((name, str(e)))
            continue
        parsed = R.as_receipt(R.extract(read["text"], read.get("lines"),
                                        degraded=read.get("degraded", False)))
        parsed["merchant"] = (parsed.get("merchant")
                              or os.path.splitext(name)[0].replace("_", " "))
        parsed["source"] = name
        # Kept so the reviewer can crop the original when a field is doubtful.
        parsed["path"] = path
        parsed["reader"] = read["reader"]
        parsed["degraded"] = read.get("degraded", False)
        receipts.append(parsed)
    return receipts, unreadable


def load(statement_path: str, receipts_dir: str) -> dict:
    """
    Read both sides and match them, or refuse and say why.

    Refuses before matching rather than after, because a statement that cannot
    be trusted makes every verdict below it individually correct and
    collectively a lie.
    """
    try:
        with open(statement_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as e:
        raise Refused(f"Cannot read {statement_path}: {e.strerror}.")

    try:
        parsed = S.parse(text, statement_path)
    except S.StatementError as e:
        raise Refused(f"This statement cannot be used:\n  {e}")

    acceptance = S.accept(parsed)
    if not acceptance["usable"]:
        raise Refused(
            "This statement is not complete, so nothing below it can be trusted:\n"
            + "\n".join(f"  {p}" for p in acceptance["problems"]))

    receipts, unreadable = receipts_in(receipts_dir)
    # `row` travels with the charge. Two identical charges are identical by
    # definition, so date-description-amount cannot tell the first from the
    # second -- which made the duplicate marker flag both halves of every pair.
    # It is also the only way the queue can say *which* line of your statement.
    charges = [{"amount": line["amount"], "description": line["description"],
                "date": line["date"], "currency": parsed.get("currency"),
                "row": line["row"]}
               for line in parsed["lines"]]
    # Found on the statement alone, so this works on the very first run --
    # before anyone has photographed a receipt, and whether or not they ever do.
    doubled = DUP.suspects(parsed["lines"])
    return {"parsed": parsed, "acceptance": acceptance, "receipts": receipts,
            "unreadable": unreadable, "charges": charges, "duplicates": doubled,
            "built": Q.build(M.match_all(receipts, charges), doubled)}
