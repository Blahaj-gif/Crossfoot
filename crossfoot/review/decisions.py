"""
The only place a queue item is cleared.

Reading the log is `crossfoot.review.ledger`, which cannot write. This module
is the write path and `review/app.py` is its only importer -- so an assistant
handed the checker, the matcher, the queue, the exporter and the CLI still has
no reachable function that marks an unchecked row as accepted.

Not a security boundary, and worth saying in the same breath as the claim: any
process on this machine can import this module and pass the string "human".
What makes that visible afterwards is the hash chain in `ledger`, not this
separation. The separation is what stops it happening by accident, or by a
model being helpful.

  * **Actor recorded, and only one actor accepted.** `record` refuses anything
    that is not a human. It is a *statement*, so that a log claiming a person
    cleared 847 items in four seconds visibly contradicts itself -- and now one
    that cannot be quietly repaired afterwards.
  * **The numbers seen at the time.** A decision references the figures the
    person was actually shown. Re-read the documents, get a different total,
    and `ledger.applies_to` says the old approval does not cover the new number.
"""
import json
import os
import time

from crossfoot.review.ledger import (  # noqa: F401  (re-exported on purpose)
    ACCEPT_AS_PRINTED, ACTIONS, CORRECT, GENESIS, IGNORE, MATCH, SCHEMA, SPLIT,
    StaleDecision, TamperedLog, _default_path, _tip, applies_to, outstanding,
    read_all, verify)

HUMAN = "human"


class NotAHumanDecision(Exception):
    """Something other than a person tried to clear a queue item."""


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


