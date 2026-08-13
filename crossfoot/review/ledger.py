"""
Reading the decision log, and proving nobody has touched it.

Split from the writer deliberately. The export step has to know which
discrepancies a person accepted, so it has to read this file -- and the whole
safety argument of the project is that the read path cannot clear an item. If
reading meant importing the module that contains `record`, then every consumer
of the ledger would have `record` one attribute away, and the boundary would be
a convention again.

So: this module reads and verifies and cannot write. `decisions.py` imports it
and adds the one function that appends. `review/app.py` is the only importer of
that, and CI asserts it.
"""
import hashlib
import json
import os

#: Bumped when the shape of a record changes. A log written this year has to
#: stay readable when it is the evidence for a return filed three years ago.
SCHEMA = 1

#: What the first record points back at. A literal rather than a null, so the
#: genesis line is chained like every other and a file cannot be truncated from
#: the top and still verify.
GENESIS = "0" * 64

ACCEPT_AS_PRINTED = "accept_as_printed"
CORRECT = "correct"
SPLIT = "split"
IGNORE = "ignore"
MATCH = "match"

ACTIONS = (ACCEPT_AS_PRINTED, CORRECT, SPLIT, IGNORE, MATCH)


class TamperedLog(Exception):
    """The chain is broken: a record was edited, removed or reordered."""


class StaleDecision(Exception):
    """The numbers moved between being shown and being decided on."""


def _default_path() -> str:
    return os.path.join(os.getcwd(), "decisions.jsonl")


def _digest(line: str) -> str:
    """
    The hash of a record as it was written.

    Deliberately over the literal line rather than a re-serialisation of the
    parsed object: verification then depends on the bytes on disk and not on
    this module still canonicalising JSON the same way in three years' time.
    """
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def _lines(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [line.rstrip("\n") for line in fh if line.strip()]


def _tip(path: str) -> str:
    """What the next record must point back at."""
    existing = _lines(path)
    return _digest(existing[-1]) if existing else GENESIS


def verify(path: str = None) -> dict:
    """
    Walk the chain. Report the first line where it breaks, and only the first.

    Later breaks are consequences of the first, exactly as in the statement
    balance walk -- listing them all buries the one that says where the file
    was actually touched.
    """
    target = path or _default_path()
    lines = _lines(target)
    if not lines:
        return {"intact": True, "records": 0, "broke_at": None, "detail": "no decisions recorded"}

    expected = GENESIS
    for number, line in enumerate(lines, start=1):
        try:
            record = json.loads(line)
        except ValueError as e:
            return {"intact": False, "records": number - 1, "broke_at": number,
                    "detail": f"line {number} is not readable JSON ({e})"}
        if record.get("prev") != expected:
            return {"intact": False, "records": number - 1, "broke_at": number,
                    "detail": (f"line {number} points back at "
                               f"{str(record.get('prev'))[:12]}… but the line before it "
                               f"hashes to {expected[:12]}… — a record here was edited, "
                               "removed or reordered")}
        expected = _digest(line)

    return {"intact": True, "records": len(lines), "broke_at": None,
            "detail": f"{len(lines)} records chain unbroken"}


def read_all(path: str = None, check: bool = True) -> list:
    """
    Every decision, oldest first. A malformed line is reported, never skipped.

    Silently dropping an unreadable line would quietly un-decide something a
    person decided, which is the same class of failure as counting an unchecked
    row as clean.

    Verifies the chain first by default. `check=False` exists for tooling that
    needs to *look at* a broken log in order to repair it -- and for nothing
    else, which is why the safe value is the default rather than a flag callers
    have to remember.
    """
    target = path or _default_path()
    if check:
        chain = verify(target)
        if not chain["intact"]:
            raise TamperedLog(
                f"{target}: {chain['detail']}. {chain['records']} records before it "
                "verify. This log is evidence; it is not repaired silently.")
    out = []
    for number, line in enumerate(_lines(target), start=1):
        try:
            out.append(json.loads(line))
        except ValueError as e:
            raise ValueError(
                f"{target} line {number} is not readable JSON ({e}). Fix or "
                "remove the line; it will not be skipped, because a "
                "decision that silently disappears is worse than a crash."
            ) from e
    return out


def applies_to(entry: dict, item: dict) -> bool:
    """
    Whether a past decision still covers this item.

    False as soon as any number the person was shown has changed. An approval
    is about the figures on the screen at the time; re-reading a document and
    getting a different total produces a different fact, and an old click must
    not travel to it.
    """
    return dict(entry.get("seen") or {}) == dict(item.get("seen") or {})


def outstanding(items, path: str = None) -> list:
    """Queue items no live decision covers. What the UI should still show."""
    decided = read_all(path)
    return [i for i in items
            if not any(applies_to(entry, i) for entry in decided)]
