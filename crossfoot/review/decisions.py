"""
The only place a queue item is cleared, and the only thing an assistant cannot
reach.

Crossfoot's claim is that an unverified number is never counted as clean. The
one way that claim dies is a caller -- a script, a model, a helpful automation
-- marking a queue full of unchecked rows as accepted. So the write path is
this module, it is imported by the review UI and by nothing else, and the
separation is enforced by a test rather than by convention.

Four properties, each guarding a different way the log could lie:

  * **Tamper-evident.** Every record carries the SHA-256 of the previous line
    exactly as it was written, so the file is a chain and any edit, deletion or
    reordering breaks it at the line where it happened. `read_all` walks the
    chain and refuses a broken one rather than returning the forgery.

    This exists because the earlier claim was false. The docstring said
    "append-only -- a decision is a historical fact", which described the API
    and not the file: the file was plain text, and rewriting it wholesale to
    turn an *ignore* into an *accept* against a different amount was undetected
    by everything. A project whose product is doubt cannot ship prose that
    outruns its code.

    It is the balance walk from `ingest.statement`, pointed at our own records:
    each row proves the one before it, and a missing row breaks the chain at
    exactly the point it was removed.

  * **Append-only, and now enforced rather than asserted.** Changing your mind
    appends a decision that supersedes the last one; both survive, and removing
    the first is what the chain catches.
  * **Actor recorded, and only one actor accepted.** `record` refuses anything
    that is not a human. This is **not** a security boundary -- any caller can
    pass the string, and any process on the machine can import this module. It
    is a *statement*, so that a log claiming a person cleared 847 items in four
    seconds is a log that visibly contradicts itself, and now one that cannot
    be quietly repaired afterwards.
  * **The numbers seen at the time.** A decision references the figures the
    person was actually shown. If the underlying documents are re-read and the
    numbers move, the decision no longer applies, and `applies_to` says so
    rather than letting an old approval cover a new number.
"""
import hashlib
import json
import os
import time

#: Bumped when the shape of a record changes. A log written this year has to
#: stay readable when it is the evidence for a return filed three years ago.
SCHEMA = 1

#: What the first record points back at. A literal rather than a null, so the
#: genesis line is chained like every other and a file cannot be truncated from
#: the top and still verify.
GENESIS = "0" * 64

HUMAN = "human"

ACCEPT_AS_PRINTED = "accept_as_printed"
CORRECT = "correct"
SPLIT = "split"
IGNORE = "ignore"
MATCH = "match"

ACTIONS = (ACCEPT_AS_PRINTED, CORRECT, SPLIT, IGNORE, MATCH)


class NotAHumanDecision(Exception):
    """Something other than a person tried to clear a queue item."""


class StaleDecision(Exception):
    """The numbers moved between being shown and being decided on."""


class TamperedLog(Exception):
    """The chain is broken: a record was edited, removed or reordered."""


def _default_path() -> str:
    return os.path.join(os.getcwd(), "decisions.jsonl")


def record(item, action: str, *, actor: str, note: str = "",
           correction=None, path: str = None, now=None) -> dict:
    """
    Append one decision. Returns what was written.

    `item` is a queue item from `crossfoot.review.queue`, and its `seen` block
    is copied into the record verbatim -- the decision is *about* those numbers
    and means nothing detached from them.
    """
    if actor != HUMAN:
        raise NotAHumanDecision(
            f"decisions are cleared by a person, not by {actor!r}. Nothing else "
            "may mark an unchecked row as accepted; that is the one claim this "
            "project makes.")
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; expected one of {', '.join(ACTIONS)}")
    if action == CORRECT and correction is None:
        raise ValueError("a correction must say what the number should be")

    target = path or _default_path()
    charge = item.get("charge") or {}
    entry = {
        "schema": SCHEMA,
        # The chain. Computed from the file as it stands, so two writers cannot
        # both believe they are extending the same tail -- the second one's
        # `prev` will not match and verification says so.
        "prev": _tip(target),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)) if now
              else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "actor": actor,
        "action": action,
        "note": note,
        "correction": correction,
        "charge": {"date": charge.get("date"),
                   "description": charge.get("description"),
                   "amount": charge.get("amount")},
        "seen": dict(item.get("seen") or {}),
        "state": item.get("state"),
        "why": item.get("why"),
    }

    _append(target, entry)
    return entry


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


def _append(path: str, entry: dict):
    """
    One line, flushed and fsynced before the call returns.

    A decision that is in a buffer when the process dies is a decision the
    person believes they made. The cost is a syscall per click, on a workload
    of a few dozen clicks.
    """
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


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
