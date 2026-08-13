"""
The command line, and the wall that runs through it.

`crossfoot check` is the surface anything automated would reach for — a script,
a cron job, a model. So the test that matters here is not that it prints nicely.
It is that neither it nor anything it imports can clear a queue item.
"""
import ast
import io
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot import cli

STATEMENT = """\
Date,Description,Amount,Balance
2026-08-06,SQ *BLUE BOTTLE 0042,-17.31,982.69
2026-08-14,HOME DEPOT #4471,-842.19,140.50
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


def _run(argv, capsys):
    code = cli.main(argv)
    return code, capsys.readouterr().out


# --------------------------------------------------------------------------
# The wall
# --------------------------------------------------------------------------

def _imports_of(module):
    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(f"{node.module or ''}.{a.name}" for a in node.names)
    return names


def test_the_cli_never_imports_the_decision_writer():
    """
    The read path is what a script or a model reaches for, and it must have no
    way to mark an unchecked row as accepted. The reviewer starts Streamlit as
    a subprocess; the decision writer is imported inside that process and never
    inside this one.
    """
    assert not any("decisions" in name for name in _imports_of(cli))


def test_only_the_review_ui_imports_the_decision_writer():
    """
    One importer, and the test names it so a second one is a visible change.

    Reads the source rather than importing the modules — deliberately. The
    first version imported `crossfoot.review.app`, which imports Streamlit,
    which is an *optional* extra. So the test asserting this project's central
    safety claim silently did not run on any install that had not asked for the
    UI, and CI found that on its first ever run. A safety check that only fires
    when an optional dependency happens to be present is not a safety check.
    """
    from crossfoot.review import decisions

    root = os.path.dirname(os.path.dirname(os.path.abspath(decisions.__file__)))
    importers = []
    for folder, _, files in os.walk(root):
        if "__pycache__" in folder or f"{os.sep}tests" in folder:
            continue
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            if os.path.samefile(path, decisions.__file__):
                continue
            source = open(path, encoding="utf-8").read()
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")) and "decisions" in stripped:
                    importers.append(os.path.relpath(path, root))
    assert importers == [os.path.join("review", "app.py")], importers


# --------------------------------------------------------------------------
# Behaviour
# --------------------------------------------------------------------------

def test_check_reports_the_failure_and_exits_non_zero(inbox, capsys):
    code, out = _run(["check", "--statement", str(inbox / "bank.csv"),
                      "--receipts", str(inbox / "receipts")], capsys)
    assert code == 1                       # something still needs a person
    assert "842.19" in out
    assert "791.44" in out and "797.44" in out


def test_a_fully_reconciled_month_exits_zero(inbox, capsys):
    """
    So this can be a step in something larger without the caller parsing prose.
    """
    (inbox / "bank.csv").write_text(
        "Date,Description,Amount,Balance\n"
        "2026-08-06,SQ *BLUE BOTTLE 0042,-17.31,982.69\n", encoding="utf-8")
    os.remove(inbox / "receipts" / "The_Home_Depot.txt")
    code, out = _run(["check", "--statement", str(inbox / "bank.csv"),
                      "--receipts", str(inbox / "receipts")], capsys)
    assert code == 0
    assert "nothing outstanding" in out


def test_a_short_statement_stops_before_any_verdict(inbox, capsys):
    (inbox / "bank.csv").write_text(
        "Date,Description,Amount,Balance\n"
        "2026-08-06,A,-17.31,982.69\n"
        "2026-08-14,C,-842.19,100.00\n", encoding="utf-8")   # a row is missing
    code, out = _run(["check", "--statement", str(inbox / "bank.csv"),
                      "--receipts", str(inbox / "receipts")], capsys)
    assert code == 2
    assert "not complete" in out
    assert "does_not_reconcile" not in out


def test_an_export_that_cannot_be_checked_for_completeness_says_so(tmp_path, capsys):
    path = tmp_path / "plain.csv"
    path.write_text("Date,Description,Amount\n2026-08-06,A,-17.31\n", encoding="utf-8")
    code, out = _run(["check", "--statement", str(path),
                      "--receipts", str(tmp_path / "none")], capsys)
    assert "cannot confirm it is whole" in out or "confirm it is whole" in out


def test_no_arguments_prints_usage_rather_than_a_traceback(capsys):
    assert cli.main([]) == 2


def test_the_checking_layer_imports_nothing_optional():
    """
    The generalisation of the bug above. `pip install crossfoot` with no extras
    must import and run — the verdict layer is arithmetic and stdlib, and that
    is a claim the README makes. Only the review UI and the document reader may
    reach for an optional package, and only inside their own module.
    """
    optional = {"streamlit", "docling", "plotly", "pandas", "numpy"}
    allowed = {"crossfoot/review/app.py", "crossfoot/read/document.py"}
    root = os.path.dirname(os.path.dirname(os.path.abspath(cli.__file__)))

    offenders = []
    for path in sorted(pathlib.Path(root, "crossfoot").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative in allowed:
            continue
        # Module level only. An import inside a function runs when that
        # function is called, which is the sanctioned way to reach an optional
        # package -- `cli.review` does exactly that and answers a missing
        # Streamlit with the install line rather than a traceback. A
        # module-level import runs at import time and breaks the whole install.
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom)
                     else [])
            for name in names:
                if name.split(".")[0] in optional:
                    offenders.append(f"{relative}: {name}")
    assert not offenders, offenders


def test_a_deferred_optional_import_answers_with_the_install_line(monkeypatch, capsys):
    """
    The other half of the rule above: reaching for Streamlit when it is absent
    must produce a sentence, not a stack trace.
    """
    import builtins

    real = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "streamlit":
            raise ImportError("no streamlit here")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    assert cli.review([]) == 1
    assert "crossfoot[ui]" in capsys.readouterr().err


def test_the_command_line_and_the_reviewer_read_through_one_loader():
    """
    They had two copies and the copies had drifted: the UI dropped the
    statement's currency, so the cross-currency check fired for `crossfoot
    check` and was silently dead in the one window where a person approves
    things. Both surfaces now call `pipeline.load`, and neither keeps a private
    reimplementation of it.
    """
    import ast

    root = os.path.dirname(os.path.dirname(os.path.abspath(cli.__file__)))
    for relative in ("crossfoot/cli.py", "crossfoot/review/app.py"):
        source = open(os.path.join(root, relative), encoding="utf-8").read()
        names = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
                names.update(f"{node.module or ''}.{a.name}" for a in node.names)
            elif isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
        assert any("pipeline" in n for n in names), relative
        # Neither may rebuild the charge list itself; that is where they drifted.
        assert "l[\"description\"]" not in source, relative


def test_the_shared_pipeline_cannot_write_a_decision():
    """It is what every reader goes through, so it must reach no write path."""
    import ast

    from crossfoot import pipeline

    names = set()
    for node in ast.walk(ast.parse(open(pipeline.__file__, encoding="utf-8").read())):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    assert not any("decisions" in n or "ledger" in n for n in names), sorted(names)
