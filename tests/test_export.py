"""
Step 6 — the verdict travels with the transaction, or nothing does.

The refusal that shapes this whole module, asserted from several directions:
**an unchecked row never leaves as though it reconciled.** A ledger that says
clean must be clean, and one that says nothing was checked must say so in the
transaction itself, where it is still visible next April.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot import cli
from crossfoot import pipeline as P
from crossfoot.export import rows as E
from crossfoot.export import targets as T
from crossfoot.match import candidates as M
from crossfoot.review import decisions as D
from crossfoot.review import ledger as L
from crossfoot.review import queue as Q

STATEMENT = """\
Date,Description,Amount,Balance
2026-08-06,SQ *BLUE BOTTLE 0042,-17.31,982.69
2026-08-09,SUNRISE CAFE SF,-104.20,878.49
2026-08-14,HOME DEPOT #4471,-842.19,36.30
"""

COFFEE = """\
BLUE BOTTLE COFFEE
Latte                    5.50
Croissant                4.25
Drip Coffee              3.75
SUBTOTAL                13.50
TAX                      1.11
TIP                      2.70
TOTAL                   17.31
"""

HARDWARE = """\
THE HOME DEPOT #4471
Lumber                 791.44
SUBTOTAL               797.44
TAX                     44.75
TOTAL                  842.19
"""


@pytest.fixture()
def inbox(tmp_path):
    (tmp_path / "bank.csv").write_text(STATEMENT, encoding="utf-8")
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "Blue_Bottle_Coffee.txt").write_text(COFFEE, encoding="utf-8")
    (receipts / "The_Home_Depot.txt").write_text(HARDWARE, encoding="utf-8")
    return tmp_path


def _built(inbox):
    return P.load(str(inbox / "bank.csv"), str(inbox / "receipts"))["built"]


def _rows(inbox, decided=()):
    built = _built(inbox)
    return E.rows_for(built["needs_you"] + built["filed_items"], decided)


# --------------------------------------------------------------------------
# The refusal
# --------------------------------------------------------------------------

def test_every_row_carries_its_verdict(inbox):
    rows = _rows(inbox)
    assert {r["verdict"] for r in rows} == {
        E.RECONCILED, E.DISCREPANT, E.UNCHECKED}


def test_an_unchecked_row_never_leaves_as_reconciled(inbox):
    """The one rule the whole module exists for."""
    unchecked = [r for r in _rows(inbox) if "SUNRISE" in r["description"]]
    assert unchecked and unchecked[0]["verdict"] == E.UNCHECKED
    assert unchecked[0]["why"] == "no receipt is matched to this charge"


def test_a_discrepancy_leaves_carrying_both_numbers(inbox):
    """
    "Does not reconcile" tells whoever opens this in April nothing they can act
    on. The two numbers that disagree do.
    """
    failed = [r for r in _rows(inbox) if "HOME DEPOT" in r["description"]][0]
    assert failed["verdict"] == E.DISCREPANT
    assert "791.44" in failed["why"] and "797.44" in failed["why"]


def test_the_checks_that_ran_travel_with_the_row(inbox):
    """So a person can see what was compared rather than trusting a word."""
    failed = [r for r in _rows(inbox) if "HOME DEPOT" in r["description"]][0]
    assert "lines_sum_to_subtotal=FAILED" in failed["checks"]
    assert "receipt_matches_charge=ok" in failed["checks"]


def test_reconciled_rows_are_exported_too(inbox):
    """
    They leave the review *queue* because nobody has to look at them. They do
    not stop having happened, and exporting only the interesting ones hands
    somebody a ledger missing most of their money.
    """
    assert len(_rows(inbox)) == 3


def test_the_summary_never_rounds_the_unchecked_away(inbox):
    summary = E.summary(_rows(inbox))
    assert "unchecked" in summary
    assert summary.startswith("3 transactions")


# --------------------------------------------------------------------------
# A human's decision is its own state
# --------------------------------------------------------------------------

def test_an_accepted_discrepancy_is_neither_reconciled_nor_unchecked(inbox, tmp_path):
    """
    A person looked at it and made a call — the merchant's arithmetic really
    was wrong. Exporting that as either neighbour loses the only fact that
    matters about it.
    """
    log = str(tmp_path / "decisions.jsonl")
    failed = [i for i in _built(inbox)["needs_you"] if i["state"] == Q.FAILED][0]
    D.record(failed, D.ACCEPT_AS_PRINTED, actor=D.HUMAN,
             note="their maths, not mine", path=log)

    rows = _rows(inbox, L.read_all(log))
    accepted = [r for r in rows if "HOME DEPOT" in r["description"]][0]
    assert accepted["verdict"] == E.ACCEPTED
    assert "you accepted this" in accepted["why"]
    assert "their maths, not mine" in accepted["why"]


def test_an_ignored_row_is_not_promoted_to_accepted(inbox, tmp_path):
    """Ignoring is not approving, and the ledger must not say it was."""
    log = str(tmp_path / "decisions.jsonl")
    failed = [i for i in _built(inbox)["needs_you"] if i["state"] == Q.FAILED][0]
    D.record(failed, D.IGNORE, actor=D.HUMAN, path=log)

    row = [r for r in _rows(inbox, L.read_all(log))
           if "HOME DEPOT" in r["description"]][0]
    assert row["verdict"] == E.DISCREPANT


def test_a_decision_about_different_numbers_does_not_travel(inbox, tmp_path):
    """
    The stale-decision rule, reaching the export. An approval is about the
    figures on the screen at the time.
    """
    log = str(tmp_path / "decisions.jsonl")
    failed = [i for i in _built(inbox)["needs_you"] if i["state"] == Q.FAILED][0]
    moved = dict(failed, seen=dict(failed["seen"], charge_amount=-99999))
    D.record(moved, D.ACCEPT_AS_PRINTED, actor=D.HUMAN, path=log)

    row = [r for r in _rows(inbox, L.read_all(log))
           if "HOME DEPOT" in r["description"]][0]
    assert row["verdict"] == E.DISCREPANT


# --------------------------------------------------------------------------
# The targets
# --------------------------------------------------------------------------

def test_actual_puts_the_verdict_where_actual_can_filter_on_it(inbox):
    """
    Actual has no tag column; it reads `#hashtags` out of the note. A verdict
    written as prose is a verdict nobody can filter on.
    """
    text = T.actual(_rows(inbox))
    assert text.splitlines()[0] == "Date,Payee,Notes,Amount"
    assert "#crossfoot-unchecked" in text
    assert "#crossfoot-does-not-reconcile" in text


def test_firefly_puts_the_verdict_in_the_tags_column(inbox):
    text = T.firefly(_rows(inbox))
    assert text.splitlines()[0] == "date,description,amount,tags,notes"
    assert "crossfoot:unchecked" in text


def test_the_firefly_config_maps_the_columns_it_writes():
    """
    The mapping is twenty dropdowns by hand the first time and twenty again
    next month, so it ships beside the CSV.
    """
    config = json.loads(T.firefly_config("7"))
    assert config["roles"] == ["date_transaction", "description", "amount",
                               "tags-comma", "note"]
    assert config["default_account"] == 7
    assert config["date"] == "Y-m-d"


def test_an_unknown_account_is_left_for_the_importer_to_ask_about():
    """A wrong account id files somebody's whole month against the wrong balance."""
    assert json.loads(T.firefly_config(""))["default_account"] == 0
    assert json.loads(T.firefly_config("not a number"))["default_account"] == 0


def test_beancount_flags_the_unreconciled_with_beancounts_own_mark(inbox):
    """
    `!` is what bean-check surfaces, so a ledger shows the unreconciled ones
    without anyone remembering a tag.
    """
    text = T.beancount(_rows(inbox))
    assert '2026-08-06 * "SQ *BLUE BOTTLE 0042"' in text
    assert '2026-08-14 ! "HOME DEPOT #4471"' in text
    assert '2026-08-09 ! "SUNRISE CAFE SF"' in text


def test_beancount_never_emits_an_undated_entry():
    """A dated ledger cannot hold one, and bean-check refuses the whole file."""
    rows = [{"date": "", "description": "NO DATE", "amount": "-1.00",
             "verdict": E.UNCHECKED, "why": "", "receipt": "", "checks": ""}]
    assert T.beancount(rows).strip() == ""


def test_a_quote_in_a_merchant_name_does_not_break_beancount():
    rows = [{"date": "2026-08-06", "description": 'JOE"S BAR', "amount": "-1.00",
             "verdict": E.UNCHECKED, "why": 'said "no"', "receipt": "", "checks": ""}]
    text = T.beancount(rows)
    assert text.count('"') % 2 == 0
    assert "JOE'S BAR" in text


def test_every_target_writes_unix_line_endings(inbox):
    """
    Mixed endings are the classic reason an importer sees one enormous row.
    """
    for name, target in T.TARGETS.items():
        assert "\r" not in target["render"](_rows(inbox)), name


def test_every_target_is_reachable_from_the_command_line():
    assert set(T.TARGETS) == {"generic", "actual", "firefly", "beancount"}


# --------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------

def test_export_writes_the_file_and_says_what_left(inbox, capsys):
    out = inbox / "ledger.csv"
    assert cli.main(["export", "--statement", str(inbox / "bank.csv"),
                     "--receipts", str(inbox / "receipts"),
                     "--to", "generic", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("date,description,amount")
    err = capsys.readouterr().err
    assert "3 transactions" in err and "unchecked" in err


def test_firefly_writes_its_config_alongside(inbox, capsys):
    out = inbox / "ledger.csv"
    cli.main(["export", "--statement", str(inbox / "bank.csv"),
              "--receipts", str(inbox / "receipts"),
              "--to", "firefly", "--out", str(out), "--account", "3"])
    config = inbox / "ledger.json"
    assert config.exists()
    assert json.loads(config.read_text(encoding="utf-8"))["default_account"] == 3


def test_export_refuses_a_short_statement_exactly_as_check_does(inbox, capsys):
    """
    An exporter more permissive than the checker writes a ledger the checker
    would not stand behind. They share one loader for that reason.
    """
    (inbox / "bank.csv").write_text(
        "Date,Description,Amount,Balance\n"
        "2026-08-06,A,-17.31,982.69\n"
        "2026-08-14,C,-842.19,100.00\n", encoding="utf-8")     # a row is missing
    assert cli.main(["export", "--statement", str(inbox / "bank.csv"),
                     "--receipts", str(inbox / "receipts")]) == 2
    assert "not complete" in capsys.readouterr().err


def test_export_refuses_a_tampered_decision_log(inbox, tmp_path, capsys):
    """
    The log is what says which discrepancies a person accepted. Exporting
    against one that cannot be trusted writes somebody's ledger from a record
    somebody edited.
    """
    log = tmp_path / "decisions.jsonl"
    failed = [i for i in _built(inbox)["needs_you"] if i["state"] == Q.FAILED][0]
    D.record(failed, D.IGNORE, actor=D.HUMAN, path=str(log))
    log.write_text('{"actor":"human","action":"accept_as_printed"}\n', encoding="utf-8")

    assert cli.main(["export", "--statement", str(inbox / "bank.csv"),
                     "--receipts", str(inbox / "receipts"),
                     "--decisions", str(log)]) == 2
    assert "Refusing to export" in capsys.readouterr().err


def test_a_missing_decision_log_is_simply_no_decisions(inbox, tmp_path):
    """Nobody has reviewed anything yet. That is a normal first run."""
    assert cli.main(["export", "--statement", str(inbox / "bank.csv"),
                     "--receipts", str(inbox / "receipts"),
                     "--decisions", str(tmp_path / "nothing.jsonl"),
                     "--out", str(tmp_path / "out.csv")]) == 0


# --------------------------------------------------------------------------
# The wall, after the split
# --------------------------------------------------------------------------

def test_reading_the_log_does_not_reach_the_writer():
    """
    The reason `ledger` was split out of `decisions`. Export has to know which
    discrepancies a person accepted; if reading meant importing the writer,
    every consumer of the ledger would have `record` one attribute away.
    """
    assert not hasattr(L, "record")
    assert not hasattr(L, "_append")
    assert hasattr(L, "read_all") and hasattr(L, "verify")


def test_the_cli_reads_the_log_and_still_cannot_write_one():
    import ast

    tree = ast.parse(open(cli.__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(f"{node.module or ''}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)

    assert any("ledger" in name for name in imported)
    assert not any("decisions" in name for name in imported)
