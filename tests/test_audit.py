"""
The statement, checked against itself.

This is the path that survived the 55-receipt measurement, so it is the one
that has to be right. Nothing here involves an OCR engine, a receipt, or any
optional dependency: a bank export is a CSV and a CSV cannot be misread by a
camera.

Two rules are asserted throughout, and they are the same rule the verdict layer
runs on:

  * a finding is a fact the statement states, or it is not reported
  * a check that could not run never counts as a check that passed
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot import audit as A
from crossfoot import cli
from crossfoot.ingest import statement as S
from crossfoot.verdict import Cents

HEADER = "Date,Description,Amount,Balance\n"


def _rows(*rows):
    """
    Rows in the shape the statement parser produces them.

    Amounts are `Cents`, not plain integers, and the difference is not
    cosmetic: `cents(-1199)` is *minus eleven ninety-nine*, because a bare int
    is read as whole units and multiplied by a hundred. Writing -1199 here and
    meaning cents produced an "at risk" figure a hundred times too large, in a
    test whose entire subject is that the figure is the one a person will quote
    back. The marker type exists to make that impossible across module
    boundaries and it only works if the fixtures use it.
    """
    return [{"row": index + 1, "date": date, "description": description,
             "amount": Cents(amount) if amount is not None else None,
             "balance": Cents(balance) if balance is not None else None}
            for index, (date, description, amount, balance) in enumerate(rows)]


def _monthly(merchant, amount, months, day=14, year=2026, start=1):
    """A subscription, as a bank writes one."""
    return [(f"{year}-{month:02d}-{day:02d}", merchant, amount, None)
            for month in range(start, start + months)]


# --------------------------------------------------------------------------
# Completeness, in three states
# --------------------------------------------------------------------------

def test_an_export_with_no_balance_and_no_total_is_unverifiable_not_whole():
    """
    The common case, and the one worth getting right. Most exports carry
    neither, and calling that "whole" would be claiming the file was checked
    when nothing checked it — the exact move this project refuses everywhere
    else.
    """
    statement = {"lines": _rows(("2026-01-05", "COFFEE", -420, None))}
    assert A.completeness(statement)["state"] == A.UNVERIFIABLE


def test_an_export_whose_balances_walk_is_whole():
    statement = {"lines": _rows(("2026-01-05", "COFFEE", -420, 9580),
                                ("2026-01-06", "BOOKS", -1000, 8580))}
    assert A.completeness(statement)["state"] == A.WHOLE


def test_an_export_with_a_row_missing_is_incomplete():
    statement = {"lines": _rows(("2026-01-05", "COFFEE", -420, 9580),
                                ("2026-01-07", "BOOKS", -1000, 7580))}
    found = A.completeness(statement)
    assert found["state"] == A.INCOMPLETE
    assert found["failed"]


def test_a_file_truncated_at_the_end_is_incomplete():
    """
    The failure a balance walk cannot see. Every surviving row is consistent
    with the one before it, right up to where the file stops — only the
    declared total, or an opening and closing balance, notices the missing tail.

    This is the case that caught a real bug: `audit` first ran its own
    completeness checks and picked the weaker of the two declared-total checks
    in this codebase, the one that does not accept opening and closing balances.
    It called this file whole. `check` called it incomplete. Two commands from
    one tool, disagreeing about whether somebody's bank statement can be
    trusted.
    """
    statement = {"lines": _rows(("2026-01-05", "COFFEE", -420, 9580),
                                ("2026-01-06", "BOOKS", -1000, 8580)),
                 "opening_balance": Cents(10000),
                 "closing_balance": Cents(5000)}      # 50.00 of rows never arrived
    assert A.completeness(statement)["state"] == A.INCOMPLETE


def test_the_audit_and_the_pipeline_agree_about_every_statement():
    """
    Pinned, because they were computing it twice and had already drifted.

    One definition of "can this file be trusted", used by both commands. The
    project makes the same argument for statement *recognition* — a file the
    intake calls a statement is a file the parser can read, rather than two
    independent guesses that disagree in front of the user — and this is the
    same argument about the same file.
    """
    cases = [
        {"lines": _rows(("2026-01-05", "COFFEE", -420, None))},
        {"lines": _rows(("2026-01-05", "COFFEE", -420, 9580),
                        ("2026-01-06", "BOOKS", -1000, 8580))},
        {"lines": _rows(("2026-01-05", "COFFEE", -420, 9580),
                        ("2026-01-07", "BOOKS", -1000, 7580))},
        {"lines": _rows(("2026-01-05", "COFFEE", -420, 9580),
                        ("2026-01-06", "BOOKS", -1000, 8580)),
         "opening_balance": Cents(10000), "closing_balance": Cents(5000)},
    ]
    for statement in cases:
        mine = A.completeness(statement)
        theirs = S.accept(statement)
        assert (mine["state"] == A.INCOMPLETE) is not theirs["usable"]
        assert (mine["state"] == A.WHOLE) is theirs["verified_complete"]


# --------------------------------------------------------------------------
# The gate with teeth
# --------------------------------------------------------------------------

def test_findings_are_withheld_entirely_when_the_export_is_incomplete():
    """
    The single most important behaviour in this module.

    A duplicate found in a statement missing rows is an artefact of the gap.
    Worse, the rows that were never read cannot be reported as missing — so
    without this the page is short, clean and wrong, and somebody reads it and
    concludes their account is fine.
    """
    rows = _rows(("2026-01-05", "NOW TV", -3599, 9641),
                 ("2026-01-05", "NOW TV", -3599, 6042),
                 # balance jumps: a row between these was never exported
                 ("2026-01-09", "BOOKS", -1000, 3000))
    found = A.audit({"lines": rows})
    assert found["suppressed"] is True
    assert found["findings"] == []
    assert found["recurring"] == []
    assert "not complete" in found["why"]


def test_the_same_statement_reports_the_duplicate_once_it_is_whole():
    """The suppression is about the gap, not about the finding."""
    rows = _rows(("2026-01-05", "NOW TV", -3599, 9641),
                 ("2026-01-05", "NOW TV", -3599, 6042),
                 ("2026-01-09", "BOOKS", -1000, 5042))
    found = A.audit({"lines": rows})
    assert found["suppressed"] is False
    assert [f["kind"] for f in found["findings"]] == ["paid_twice"]
    assert int(found["at_risk"]) == 3599


# --------------------------------------------------------------------------
# Recurring charges: an inventory, not an accusation
# --------------------------------------------------------------------------

def test_a_monthly_charge_is_listed_with_what_it_costs_a_year():
    statement = {"lines": _rows(*_monthly("SPOTIFY", -1199, 6))}
    found = A.recurring(statement["lines"])
    assert len(found) == 1
    assert found[0]["merchant"].startswith("spotify")
    assert int(found[0]["a_year"]) == 1199 * 12
    assert found[0]["charges"] == 6


def test_two_charges_a_month_apart_are_not_yet_recurring():
    """
    A great many people buy something from the same supermarket twice, a month
    apart, and calling that a subscription is how a list stops being read.
    """
    statement = {"lines": _rows(*_monthly("TESCO", -2000, 2))}
    assert A.recurring(statement["lines"]) == []


def test_the_inventory_is_not_a_finding():
    """
    Whether somebody still wants a subscription is not in the statement. The
    first draft of this module had a "still charging" finding and it had to go:
    the tool cannot see whether you use the thing, and every commercial product
    that ships that finding is guessing.
    """
    statement = {"lines": _rows(*_monthly("AUDIBLE", -999, 12))}
    found = A.audit(statement)
    assert found["findings"] == []
    assert len(found["recurring"]) == 1


# --------------------------------------------------------------------------
# Price rises
# --------------------------------------------------------------------------

def test_a_subscription_that_went_up_is_reported_with_the_annual_difference():
    rows = _monthly("SPOTIFY", -1199, 3) + _monthly("SPOTIFY", -1499, 3, start=4)
    found = A.price_rises(_rows(*rows))
    assert len(found) == 1
    assert int(found[0]["was"]) == 1199
    assert int(found[0]["now"]) == 1499
    assert int(found[0]["at_risk"]) == 300 * 12
    assert found[0]["when"] == "2026-04-14"


def test_a_few_pence_of_drift_is_not_a_price_rise():
    """
    A utility bill moves every month. Reporting that would bury the streaming
    service that went up by three pounds, which is the one worth seeing.
    """
    rows = [("2026-01-14", "WATER", -4210, None),
            ("2026-02-14", "WATER", -4235, None),
            ("2026-03-14", "WATER", -4228, None),
            ("2026-04-14", "WATER", -4241, None)]
    assert A.price_rises(_rows(*rows)) == []


def test_a_subscription_that_got_cheaper_is_not_reported():
    rows = _monthly("GYM", -4000, 3) + _monthly("GYM", -3000, 3, start=4)
    assert A.price_rises(_rows(*rows)) == []


# --------------------------------------------------------------------------
# New recurring charges
# --------------------------------------------------------------------------

def test_a_subscription_that_started_mid_statement_is_reported():
    rows = (_monthly("RENT", -80000, 8)
            + _monthly("NEW THING", -799, 5, start=4))
    found = A.new_recurring(_rows(*rows))
    assert [f["merchant"] for f in found] == ["new thing"]
    assert found[0]["since"] == "2026-04-14"


def test_a_subscription_whose_reference_changes_is_one_subscription():
    """
    The bug a realistic statement found, and the worst kind this module can
    have: a false accusation.

    Banks put a per-transaction reference in the descriptor — `SPOTIFY P0A1B2`
    one month, `SPOTIFY P4Z9Q1` the next — and PayPal and Amazon do it too.
    Compared whole, those are two merchants, so one subscription was reported
    as **newly started** every time its reference changed, and the price rise
    disappeared because the before and after sat in different groups.

    "You started paying for this" is a statement about something that did not
    happen. The duplicate checker's own note applies: a tool that is
    confidently wrong gets turned off, and being turned off is the only way a
    check fails completely.
    """
    rows = [("2026-01-03", "SPOTIFY P0A1B2", -1199, None),
            ("2026-02-03", "SPOTIFY P1C3D4", -1199, None),
            ("2026-03-03", "SPOTIFY P2E5F6", -1199, None),
            ("2026-04-03", "SPOTIFY P3G7H8", -1499, None),
            ("2026-05-03", "SPOTIFY P4J9K1", -1499, None),
            ("2026-06-03", "SPOTIFY P5L2M3", -1499, None)]
    lines = _rows(*rows)

    assert len(A.recurring(lines)) == 1
    assert A.new_recurring(lines) == []
    rises = A.price_rises(lines)
    assert len(rises) == 1
    assert int(rises[0]["was"]) == 1199 and int(rises[0]["now"]) == 1499


def test_a_reference_is_only_stripped_from_the_end():
    """`7 ELEVEN` and `O2` begin with a digit and are not references."""
    assert A._stable_name("7 eleven store 4471") == "7 eleven store"
    assert A._stable_name("o2 uk") == "o2 uk"
    assert A._stable_name("spotify p0a1b2") == "spotify"
    # Never everything: a descriptor that is all reference keeps its last word
    # rather than becoming the empty string, which would group every such row
    # into one merchant named nothing.
    assert A._stable_name("4471") == "4471"


def test_a_subscription_present_from_the_first_weeks_is_not_called_new():
    """
    Every subscription looks new at the start of any export, because the file
    does not reach back far enough to show the earlier charges. Without the
    settling period this reports a person's whole subscription list as newly
    started, every month.
    """
    rows = _monthly("SPOTIFY", -1199, 8)
    assert A.new_recurring(_rows(*rows)) == []


# --------------------------------------------------------------------------
# Money at risk
# --------------------------------------------------------------------------

def test_money_at_risk_is_the_sum_of_the_findings_and_nothing_else():
    """
    The number a person quotes back. Folding the recurring inventory into it
    would claim their whole subscription bill is at stake, which is not what
    the statement says and would not survive one person checking it.
    """
    rows = _rows(*(_monthly("SPOTIFY", -1199, 3)
                   + _monthly("SPOTIFY", -1499, 3, start=4)))
    found = A.audit({"lines": rows})
    assert int(found["at_risk"]) == sum(int(f["at_risk"]) for f in found["findings"])
    assert int(found["at_risk"]) == 3600


# --------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------

def test_the_audit_command_runs_on_a_statement_alone(tmp_path, capsys):
    path = tmp_path / "export.csv"
    path.write_text(
        HEADER
        + "2026-01-05,NOW TV,-35.99,96.41\n"
        + "2026-01-05,NOW TV,-35.99,60.42\n"
        + "2026-01-09,BOOKS,-10.00,50.42\n", encoding="utf-8")
    code = cli.main(["audit", str(path)])
    out = capsys.readouterr().out
    assert code == 1                         # something to act on
    assert "PAID TWICE" in out
    assert "35.99" in out


def test_the_audit_command_says_nothing_looks_wrong_rather_than_nothing(
        tmp_path, capsys):
    """
    An empty page reads as a broken tool. A sentence reads as an answer.
    """
    path = tmp_path / "export.csv"
    path.write_text(HEADER + "2026-01-05,COFFEE,-4.20,95.80\n", encoding="utf-8")
    assert cli.main(["audit", str(path)]) == 0
    assert "Nothing looks wrong" in capsys.readouterr().out


def test_the_audit_command_refuses_an_incomplete_export_loudly(tmp_path, capsys):
    path = tmp_path / "export.csv"
    path.write_text(
        HEADER
        + "2026-01-05,NOW TV,-35.99,96.41\n"
        + "2026-01-05,NOW TV,-35.99,60.42\n"
        + "2026-01-09,BOOKS,-10.00,30.00\n", encoding="utf-8")
    code = cli.main(["audit", str(path)])
    out = capsys.readouterr().out
    assert code == 2
    assert "PAID TWICE" not in out
    assert "misleading" in out


def test_the_audit_command_needs_no_receipts_folder(tmp_path, capsys):
    """
    The whole point of this command. `check` wants a folder of receipts and
    everything that reads them; this wants a file.
    """
    path = tmp_path / "export.csv"
    path.write_text(HEADER + "2026-01-05,COFFEE,-4.20,95.80\n", encoding="utf-8")
    assert cli.main(["audit", str(path)]) == 0


def test_audit_appears_in_the_usage_text():
    assert "crossfoot audit" in cli._usage()


def test_a_file_that_is_not_a_statement_is_refused_by_name(tmp_path, capsys):
    path = tmp_path / "notes.csv"
    path.write_text("Name,Note\nAda,hello\n", encoding="utf-8")
    assert cli.main(["audit", str(path)]) == 2
    assert "Cannot read" in capsys.readouterr().err
