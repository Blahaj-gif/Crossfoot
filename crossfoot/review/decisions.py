"""
The only place a queue item is cleared, and the only thing an assistant cannot
reach.

Crossfoot's claim is that an unverified number is never counted as clean. The
one way that claim dies is a caller -- a script, a model, a helpful automation
-- marking a queue full of unchecked rows as accepted. So the write path is
this module, it is imported by the review UI and by nothing else, and the
separation is enforced by a test rather than by convention.

Three properties, each guarding a different way the log could lie:

  * **Append-only.** A decision is a historical fact. Nothing here updates or
    deletes one; changing your mind appends a new decision that supersedes it,
    and both survive.
  * **Actor recorded, and only one actor accepted.** `record` refuses anything
    that is not a human. It is not a security boundary -- any caller can pass
    the string -- it is a *statement*, so that a log claiming a person cleared
    847 items in four seconds is a log that visibly contradicts itself.
  * **The numbers seen at the time.** A decision references the figures the
    person was actually shown. If the underlying documents are re-read and the
    numbers move, the decision no longer applies, and `applies_to` says so
    rather than letting an old approval cover a new number.
"""
import json
import os
import time

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

    charge = item.get("charge") or {}
    entry = {
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

    target = path or _default_path()
    _append(target, entry)
    return entry


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


def read_all(path: str = None) -> list:
    """
    Every decision, oldest first. A malformed line is reported, never skipped.

    Silently dropping an unreadable line would quietly un-decide something a
    person decided, which is the same class of failure as counting an unchecked
    row as clean.
    """
    target = path or _default_path()
    if not os.path.exists(target):
        return []
    out = []
    with open(target, encoding="utf-8") as fh:
        for number, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
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
