"""
Step 4 — the queue, and the gate that only a person can pass.

Two claims are pinned here. That the queue never counts an unchecked row as
clean, and that nothing but a human clears one — the second structurally, by
checking that the module a model would be handed cannot reach the write path.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot import verdict as V
from crossfoot.match import candidates as M
from crossfoot.review import decisions as D
from crossfoot.review import queue as Q


def clean_receipt(total="17.31"):
    return {"lines": [{"amount": "13.50"}], "subtotal": "13.50",
            "tax": "1.11", "tip": "2.70", "total": total, "merchant": "Blue Bottle"}


def broken_receipt():
    r = clean_receipt()
    r["subtotal"] = "19.50"          # its own items disagree with its own subtotal
    return r


def match(receipt, amount, description="BLUE BOTTLE", ambiguous=()):
    return {"charge": {"amount": amount, "description": description,
                       "date": "2026-08-09"},
            "receipt": receipt, "ambiguous": list(ambiguous)}


# --------------------------------------------------------------------------
# States
# --------------------------------------------------------------------------

def test_a_reconciled_charge_is_filed_and_leaves_the_queue():
    built = Q.build([match(clean_receipt(), "17.31")])
    assert built["needs_you"] == []
    assert built["filed"] == 1


def test_a_receipt_disagreeing_with_itself_needs_you():
    item = Q.build([match(broken_receipt(), "17.31")])["needs_you"][0]
    assert item["state"] == Q.FAILED


def test_a_charge_with_no_receipt_is_unverified_and_not_filed():
    """The state every incumbent throws away."""
    item = Q.build([match(None, "263.88")])["needs_you"][0]
    assert item["state"] == Q.UNVERIFIED
    assert item["verdict"] == V.UNCHECKED


def test_an_unresolved_tie_reaches_the_queue_as_a_tie():
    charge = {"amount": "-17.31", "description": "BLUE BOTTLE",
              "date": "2026-08-09"}
    outcome = M.resolve(M.candidates([clean_receipt(), clean_receipt()], charge))
    item = Q.build([{"charge": charge, **outcome}])["needs_you"][0]
    assert item["state"] == Q.AMBIGUOUS
    assert len(item["ambiguous"]) == 2


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------

def test_the_queue_is_ordered_by_money_at_risk():
    """
    Sorting by count treats a $3.20 artefact and an $842 discrepancy as equals,
    which they are only to a computer.
    """
    built = Q.build([match(broken_receipt(), "3.20"),
                     match(broken_receipt(), "842.19"),
                     match(broken_receipt(), "104.20")])
    assert [i["at_risk"] for i in built["needs_you"]] == [84219, 10420, 320]


def test_failures_outrank_unverified_regardless_of_size():
    """
    A number known to be wrong is worth more attention than one nobody could
    check, even when the unchecked one is larger.
    """
    built = Q.build([match(None, "999.00"), match(broken_receipt(), "1.00")])
    assert built["needs_you"][0]["state"] == Q.FAILED


def test_the_headline_never_rounds_the_unchecked_away():
    """
    "347 reconciled" is true and misleading in the same breath: out of how
    many, and what happened to the rest?
    """
    built = Q.build([match(clean_receipt(), "17.31"), match(None, "263.88")])
    assert "unchecked" in built["headline"]


def test_a_page_with_nothing_outstanding_still_reports_the_unchecked():
    built = Q.build([match(clean_receipt(), "17.31")])
    assert "nothing outstanding" in built["headline"]


def test_the_reason_shown_is_the_disagreement_not_the_verdict_word():
    """"Does not reconcile" tells a person nothing they can act on."""
    item = Q.build([match(broken_receipt(), "17.31")])["needs_you"][0]
    assert "13.50" in item["why"] and "19.50" in item["why"]


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------

def test_the_queue_module_cannot_reach_the_write_path():
    """
    Structural, not polite. An assistant handed the whole of queue.py still has
    no function that clears an item — the separation is the guarantee, and a
    convention would not be one.

    Read from the import graph rather than the text. The first version of this
    grepped for the word and failed on the paragraph explaining the rule, which
    is a test that punishes documenting the thing it is testing.
    """
    import ast

    tree = ast.parse(open(Q.__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module or ''}.{a.name}" for a in node.names)

    assert not any("decisions" in name for name in imported), sorted(imported)
    assert not hasattr(Q, "record")
    assert not any(name.startswith("record") or name.startswith("write")
                   for name in dir(Q) if not name.startswith("_"))


def test_only_a_human_may_record_a_decision(tmp_path):
    item = Q.build([match(None, "263.88")])["needs_you"][0]
    log = str(tmp_path / "decisions.jsonl")
    for actor in ("assistant", "claude", "script", "", None):
        with pytest.raises(D.NotAHumanDecision):
            D.record(item, D.IGNORE, actor=actor, path=log)
    assert not os.path.exists(log)


def test_a_human_decision_is_appended_with_the_numbers_they_saw(tmp_path):
    item = Q.build([match(broken_receipt(), "17.31")])["needs_you"][0]
    log = str(tmp_path / "decisions.jsonl")
    D.record(item, D.ACCEPT_AS_PRINTED, actor=D.HUMAN, note="merchant's maths",
             path=log)

    written = D.read_all(log)
    assert len(written) == 1
    assert written[0]["seen"]["charge_amount"] == 1731
    assert written[0]["action"] == D.ACCEPT_AS_PRINTED


def test_the_log_is_append_only(tmp_path):
    item = Q.build([match(None, "263.88")])["needs_you"][0]
    log = str(tmp_path / "decisions.jsonl")
    D.record(item, D.IGNORE, actor=D.HUMAN, path=log)
    D.record(item, D.MATCH, actor=D.HUMAN, path=log)
    assert [e["action"] for e in D.read_all(log)] == [D.IGNORE, D.MATCH]


def test_a_correction_must_say_what_the_number_should_be(tmp_path):
    item = Q.build([match(broken_receipt(), "17.31")])["needs_you"][0]
    with pytest.raises(ValueError):
        D.record(item, D.CORRECT, actor=D.HUMAN, path=str(tmp_path / "d.jsonl"))


def test_an_unknown_action_is_refused(tmp_path):
    item = Q.build([match(None, "1.00")])["needs_you"][0]
    with pytest.raises(ValueError, match="unknown action"):
        D.record(item, "approve_everything", actor=D.HUMAN,
                 path=str(tmp_path / "d.jsonl"))


def test_a_decision_does_not_travel_to_numbers_it_was_not_about(tmp_path):
    """
    An approval is about the figures on the screen at the time. Re-read the
    document, get a different total, and the old click must not cover it.
    """
    log = str(tmp_path / "decisions.jsonl")
    original = Q.build([match(clean_receipt("17.31"), "17.31")])
    same = Q.build([match(clean_receipt("17.31"), "17.31")])["filed"]
    item = Q.build([match(broken_receipt(), "17.31")])["needs_you"][0]
    D.record(item, D.ACCEPT_AS_PRINTED, actor=D.HUMAN, path=log)

    moved = Q.build([match(broken_receipt(), "18.00")])["needs_you"][0]
    entry = D.read_all(log)[0]
    assert D.applies_to(entry, item) is True
    assert D.applies_to(entry, moved) is False
    assert original["filed"] == same == 1


def test_outstanding_hides_only_what_a_person_actually_decided(tmp_path):
    log = str(tmp_path / "decisions.jsonl")
    items = Q.build([match(broken_receipt(), "17.31"), match(None, "263.88")])["needs_you"]
    D.record(items[0], D.IGNORE, actor=D.HUMAN, path=log)
    left = D.outstanding(items, log)
    assert len(left) == 1
    assert left[0]["seen"]["charge_amount"] == 26388


def test_a_malformed_line_is_reported_rather_than_skipped(tmp_path):
    """
    Silently dropping it would quietly un-decide something a person decided,
    which is the same class of failure as counting an unchecked row as clean.
    """
    log = tmp_path / "decisions.jsonl"
    log.write_text('{"actor": "human"}\nnot json at all\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        D.read_all(str(log))


def test_a_decision_survives_the_process(tmp_path):
    """Flushed and fsynced before the call returns; a click is not a buffer."""
    log = str(tmp_path / "decisions.jsonl")
    item = Q.build([match(None, "1.00")])["needs_you"][0]
    D.record(item, D.IGNORE, actor=D.HUMAN, path=log)
    with open(log, encoding="utf-8") as fh:
        assert json.loads(fh.readline())["actor"] == D.HUMAN


# --------------------------------------------------------------------------
# Found in the audit sweep
# --------------------------------------------------------------------------

def test_no_function_copies_the_decision_log_anywhere():
    """
    `snapshot()` wrote the whole log — merchants, dates, amounts — into the
    system temp directory and never removed it, and nothing called it. Dead
    code that only creates exposure.
    """
    import inspect
    source = inspect.getsource(D)
    assert "tempfile" not in source
    assert not hasattr(D, "snapshot")


def test_the_repository_ignores_what_a_run_produces():
    """
    The sister project shipped a portfolio history to PyPI because files were
    listed one by one and one was missed. Globs, not names.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ignored = open(os.path.join(root, ".gitignore"), encoding="utf-8").read()
    for pattern in ("*.jsonl", "receipts/", "*.sqlite", ".env"):
        assert pattern in ignored, pattern
