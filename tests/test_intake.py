"""
Getting things in, and reading a photograph.

Two features that exist because the README claimed them before the code had
them. The rule they are built to: **decide what a file is by looking at it.**
A bank export saved as `download (3).csv` and a receipt saved as
`statement.pdf` are both entirely normal, and any rule based on filenames gets
both of them wrong.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossfoot import cli
from crossfoot.ingest import inbox as I
from crossfoot.read import document, ocr
from crossfoot.read import receipt as R

STATEMENT = ("Date,Description,Amount,Balance\n"
             "2026-08-06,SQ *BLUE BOTTLE 0042,-17.31,982.69\n"
             "2026-08-14,HOME DEPOT #4471,-842.19,140.50\n")

RECEIPT = ("BLUE BOTTLE COFFEE\nLatte  13.50\nSUBTOTAL  13.50\n"
           "TAX  1.11\nTIP  2.70\nTOTAL  17.31\n")


# --------------------------------------------------------------------------
# One folder, sorted by content
# --------------------------------------------------------------------------

def test_a_statement_is_recognised_however_it_is_named(tmp_path):
    """`download (3).csv` is what a bank export is actually called."""
    path = tmp_path / "download (3).csv"
    path.write_text(STATEMENT, encoding="utf-8")
    assert I.looks_like_a_statement(str(path)) is True


def test_a_receipt_named_statement_is_still_a_receipt(tmp_path):
    """The name is not evidence. The contents are."""
    path = tmp_path / "statement.txt"
    path.write_text(RECEIPT, encoding="utf-8")
    assert I.looks_like_a_statement(str(path)) is False


def test_ofx_is_recognised_by_its_transaction_blocks(tmp_path):
    path = tmp_path / "export.txt"
    path.write_text("<OFX><STMTTRN><TRNAMT>-1.00<NAME>X</STMTTRN></OFX>",
                    encoding="utf-8")
    assert I.looks_like_a_statement(str(path)) is True


def test_a_csv_with_no_amount_column_is_not_a_statement(tmp_path):
    """
    Recognition reuses the parser's own header table, so a file this calls a
    statement is a file the parser can read — rather than two independent
    guesses that disagree in front of the user.
    """
    path = tmp_path / "contacts.csv"
    path.write_text("Date,Name\n2026-08-06,Ada\n", encoding="utf-8")
    assert I.looks_like_a_statement(str(path)) is False


def test_one_folder_splits_into_the_two_kinds(tmp_path):
    (tmp_path / "download (3).csv").write_text(STATEMENT, encoding="utf-8")
    (tmp_path / "statement.txt").write_text(RECEIPT, encoding="utf-8")
    (tmp_path / "IMG_2043.txt").write_text(RECEIPT, encoding="utf-8")
    found = I.sort(str(tmp_path))
    assert [os.path.basename(p) for p in found["statements"]] == ["download (3).csv"]
    assert len(found["receipts"]) == 2
    assert found["problem"] is None


def test_a_skipped_file_is_reported_rather_than_silently_dropped(tmp_path):
    """
    Somebody who drops a file in and sees nothing happen concludes the tool is
    broken, when it is being careful.
    """
    (tmp_path / "bank.csv").write_text(STATEMENT, encoding="utf-8")
    (tmp_path / "notes.docx").write_bytes(b"PK\x03\x04")
    found = I.sort(str(tmp_path))
    assert found["ignored"] == [("notes.docx", "not a document type this reads")]


def test_hidden_files_are_left_alone(tmp_path):
    (tmp_path / "bank.csv").write_text(STATEMENT, encoding="utf-8")
    (tmp_path / ".DS_Store").write_text("junk", encoding="utf-8")
    assert I.sort(str(tmp_path))["ignored"] == []


def test_no_statement_says_so_and_says_why(tmp_path):
    (tmp_path / "receipt.txt").write_text(RECEIPT, encoding="utf-8")
    problem = I.sort(str(tmp_path))["problem"]
    assert "no bank statement found" in problem
    assert "missing" in problem


def test_two_statements_are_refused_rather_than_merged(tmp_path):
    """
    Two exports may overlap, and concatenating them would manufacture the
    duplicate charges this tool exists to find.
    """
    (tmp_path / "january.csv").write_text(STATEMENT, encoding="utf-8")
    (tmp_path / "february.csv").write_text(STATEMENT, encoding="utf-8")
    problem = I.sort(str(tmp_path))["problem"]
    assert "one at a time" in problem
    assert "manufacture" in problem


def test_a_folder_that_is_not_a_folder_says_so(tmp_path):
    assert "not a folder" in I.sort(str(tmp_path / "nope"))["problem"]


def test_the_fingerprint_notices_every_kind_of_change(tmp_path):
    (tmp_path / "bank.csv").write_text(STATEMENT, encoding="utf-8")
    first = I.fingerprint(str(tmp_path))

    (tmp_path / "receipt.txt").write_text(RECEIPT, encoding="utf-8")
    assert I.fingerprint(str(tmp_path)) != first          # added

    (tmp_path / "receipt.txt").write_text(RECEIPT + "x", encoding="utf-8")
    second = I.fingerprint(str(tmp_path))

    os.remove(tmp_path / "receipt.txt")
    assert I.fingerprint(str(tmp_path)) != second          # removed


def test_watch_stops_when_it_is_told_to(tmp_path):
    """A loop a person starts and stops, not a service reconciling in the dark."""
    (tmp_path / "bank.csv").write_text(STATEMENT, encoding="utf-8")
    seen = []
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 2

    I.watch(str(tmp_path), seen.append, interval=0, stop=stop)
    assert len(seen) == 1                    # one change: the initial contents


def test_the_command_line_takes_one_folder(tmp_path, capsys):
    (tmp_path / "download (3).csv").write_text(STATEMENT, encoding="utf-8")
    (tmp_path / "coffee.txt").write_text(RECEIPT, encoding="utf-8")
    code = cli.main(["check", "--inbox", str(tmp_path)])
    out, err = capsys.readouterr()
    assert code in (0, 1)
    assert "1 statement, 1 receipts" in err
    assert "reconciled" in out


def test_neither_inbox_nor_statement_is_an_error_not_a_traceback(capsys):
    with pytest.raises(SystemExit):
        cli.main(["check"])


def test_no_arguments_opens_the_window(monkeypatch):
    """
    For most of the people this is for, a page of usage text *is* the failure:
    they came to look at their receipts, not to learn a flag.

    Patched, because the real call starts a server and blocks — which is
    exactly what it should do for a person and exactly what hung the test
    suite, and CI with it, the moment this behaviour landed.
    """
    opened = []
    monkeypatch.setattr(cli, "window_available", lambda: True)
    monkeypatch.setattr(cli, "review", lambda argv: opened.append(argv) or 0)
    assert cli.main([]) == 0
    assert opened == [[]]


def test_no_arguments_without_the_window_explains_rather_than_hangs(monkeypatch, capsys):
    """
    Both branches are asserted, and neither asks the machine it is running on
    — the first version of these did, so they passed here and failed on CI.
    """
    monkeypatch.setattr(cli, "window_available", lambda: False)
    assert cli.main([]) == 1
    message = capsys.readouterr().err
    assert "crossfoot[ui]" in message
    assert "crossfoot check" in message      # the way through without the window


def test_help_is_still_reachable_for_anyone_who_wants_it(capsys):
    for flag in ("--help", "-h", "help"):
        assert cli.main([flag]) == 0
        assert "crossfoot doctor" in capsys.readouterr().out


def test_doctor_says_what_works_before_anything_breaks(capsys):
    assert cli.main(["doctor"]) == 0
    said = capsys.readouterr().out
    assert "What works on this machine" in said
    # The thing that works with nothing installed leads the good news, because
    # it is the reason to keep going on a bare machine.
    assert "billed twice" in said


# --------------------------------------------------------------------------
# Photographs
# --------------------------------------------------------------------------

def test_an_image_is_recognised_by_suffix():
    for name in ("a.jpg", "b.JPEG", "c.png", "d.heic", "e.webp"):
        assert ocr.is_image(name), name
    for name in ("a.pdf", "b.csv", "c.txt"):
        assert not ocr.is_image(name), name


def test_a_photograph_with_no_engine_is_refused_not_read_as_bytes(
        tmp_path, monkeypatch):
    """
    The failure this prevents: a JPEG read as text is binary noise that a
    parser will cheerfully find amounts in. Refusing names the fix; reading it
    would invent numbers.

    The engines are patched off rather than skipped on. The first version asked
    the machine whether an engine was installed, so it tested one thing on a
    developer's laptop and another on CI, and it started failing the day
    Tesseract was installed here — which is a test measuring its surroundings
    rather than the code.
    """
    monkeypatch.setattr(ocr, "HAVE_TESSERACT", False)
    monkeypatch.setattr(ocr, "HAVE_EASYOCR", False)
    monkeypatch.setattr(ocr, "_tesseract_binary_works", lambda: False)
    path = tmp_path / "receipt.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0 not really a jpeg")
    with pytest.raises(document.UnreadableDocument) as caught:
        document.read(str(path))
    assert "nothing here can read one yet" in str(caught.value)
    assert "crossfoot[ocr]" in str(caught.value)


def test_the_readers_list_says_what_is_actually_installed():
    """Stated, not implied — a verdict must never rest on a reader nobody knew about."""
    listed = document.readers()
    assert "plain text" in listed
    assert ("docling" in listed) == document.HAVE_DOCLING
    for engine in ocr.available():
        assert f"ocr:{engine}" in listed


def _word(text, confidence, left, top, width=40, height=12, line=0):
    return ocr.Word(text, confidence, left, top, width, height, line)


def test_words_become_lines_in_reading_order():
    """
    The receipt parser works on lines — "TOTAL" then an amount — so
    reconstructing them faithfully is the whole job. Right-to-left assembly
    would put the amount before its label and nothing would be found.
    """
    words = [_word("17.31", 96, 300, 10), _word("TOTAL", 98, 10, 10),
             _word("VISA", 90, 10, 30, line=1)]
    assembled = ocr._assemble(words, "test", "r.jpg")
    assert assembled["text"].splitlines() == ["TOTAL 17.31", "VISA"]


def test_a_photograph_read_confidently_is_not_degraded():
    words = [_word("TOTAL", 96, 10, 10), _word("17.31", 94, 300, 10)]
    assembled = ocr._assemble(words, "test", "r.jpg")
    assert assembled["degraded"] is False
    assert assembled["confidence"] == 100.0


def test_a_smudged_photograph_is_marked_degraded():
    """
    A fifth of the words below threshold is a picture worth retaking, and
    saying so is cheaper than a wrong total in a ledger that claims to be
    checked.
    """
    words = [_word("TOTAL", 96, 10, 10), _word("17.31", 20, 300, 10),
             _word("TAX", 30, 10, 30, line=1)]
    assembled = ocr._assemble(words, "test", "r.jpg")
    assert assembled["degraded"] is True
    assert "17.31" in assembled["doubtful"]


def test_a_photograph_yielding_nothing_is_degraded_not_empty():
    assembled = ocr._assemble([], "test", "r.jpg")
    assert assembled["degraded"] is True and assembled["text"] == ""


# --------------------------------------------------------------------------
# Boxes, and the crop that makes them worth keeping
# --------------------------------------------------------------------------

def test_a_field_read_from_a_photograph_keeps_its_rectangle():
    """
    What lets the queue show somebody the ink instead of asking them to trust a
    number and go and find the original.
    """
    words = [_word("TOTAL", 96, 10, 100), _word("17.31", 95, 300, 100)]
    assembled = ocr._assemble(words, "test", "r.jpg")
    extracted = R.extract(assembled["text"], assembled["lines"])
    assert extracted["fields"]["total"].box == (10, 100, 340, 112)


def test_the_box_covers_the_whole_line_not_just_the_number():
    """
    A crop of four digits has no context. A crop of "TOTAL   17.31" is a
    picture a person can actually check.
    """
    words = [_word("TOTAL", 96, 10, 100), _word("17.31", 95, 300, 100)]
    assembled = ocr._assemble(words, "test", "r.jpg")
    box = R.extract(assembled["text"], assembled["lines"])["fields"]["total"].box
    assert box[0] == 10 and box[2] == 340


def test_text_that_never_came_from_a_page_has_no_box():
    """A PDF or a text file has no rectangle, and inventing one would be a lie."""
    assert R.extract("TOTAL  17.31\n")["fields"]["total"].box is None


def test_cropping_without_an_imaging_library_says_which_one():
    if ocr.HAVE_TESSERACT:                               # pragma: no cover
        pytest.skip("Pillow is installed, so this path is not taken")
    with pytest.raises(ocr.NoEngine, match="crossfoot\\[ocr\\]"):
        ocr.crop("r.jpg", (0, 0, 10, 10))


def test_no_ocr_backend_reaches_the_network():
    """
    The property the whole project rests on. There is deliberately no cloud
    engine: an OCR API is the one line of code that would turn "your receipts
    never leave this machine" into a lie.
    """
    import ast

    source = open(ocr.__file__, encoding="utf-8").read()
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    banned = {"requests", "httpx", "urllib", "http", "socket", "boto3",
              "google", "openai", "anthropic"}
    assert not {n.split(".")[0] for n in names} & banned, sorted(names)
    # And the one engine that *could* fetch weights only does so on an
    # explicit opt-in, never by default.
    assert "download_enabled=allowed" in source
    assert 'os.getenv(ALLOW_MODEL_DOWNLOAD, "")' in source


def test_the_usage_screen_names_every_command_and_leads_with_the_easy_one(capsys):
    """
    The one screen a confused person is guaranteed to see. It told people to
    name two paths on the command line for a week after the one-folder intake
    shipped, because a patch silently failed to apply and nothing tested this
    text. Every subcommand and every export target has to appear in it, so
    adding one and forgetting the help is a failing test rather than a user
    who never finds the feature.
    """
    cli.main(["--help"])
    usage = capsys.readouterr().out
    for command in ("check", "review", "export"):
        assert command in usage, command
    for target in ("generic", "actual", "firefly", "beancount"):
        assert target in usage, target
    # The easy path first: --inbox must appear before --statement.
    assert usage.index("--inbox") < usage.index("--statement")


def test_installing_the_wrapper_without_the_program_says_which_is_missing(
        tmp_path, monkeypatch):
    """
    `pip install crossfoot[ocr]` installs pytesseract and cannot install
    tesseract, which is not a Python package. That left HAVE_TESSERACT true
    and every photograph raising TesseractNotFoundError from the middle of a
    run. Telling somebody "no OCR engine installed" would send them to
    reinstall the thing they already have.
    """
    monkeypatch.setattr(ocr, "HAVE_TESSERACT", True)
    monkeypatch.setattr(ocr, "HAVE_EASYOCR", False)
    monkeypatch.setattr(ocr, "_tesseract_binary_works", lambda: False)

    path = tmp_path / "receipt.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0")
    with pytest.raises(ocr.NoEngine) as caught:
        ocr.read_image(str(path))
    message = str(caught.value)
    assert "the tesseract program itself is not" in message
    assert "pip cannot install it" in message
    assert "ocr-heavy" in message            # the way out for a locked-down machine


def test_available_reports_what_will_work_not_what_is_importable(monkeypatch):
    """"Installed" is not the question a person cares about. "Will this work" is."""
    monkeypatch.setattr(ocr, "HAVE_TESSERACT", True)
    monkeypatch.setattr(ocr, "HAVE_EASYOCR", False)
    monkeypatch.setattr(ocr, "_tesseract_binary_works", lambda: False)
    assert ocr.available() == []

    monkeypatch.setattr(ocr, "_tesseract_binary_works", lambda: True)
    assert ocr.available() == ["tesseract"]


def test_nothing_installed_at_all_names_both_ways_forward(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "HAVE_TESSERACT", False)
    monkeypatch.setattr(ocr, "HAVE_EASYOCR", False)
    monkeypatch.setattr(ocr, "_tesseract_binary_works", lambda: False)

    path = tmp_path / "receipt.png"
    path.write_bytes(b"\x89PNG")
    with pytest.raises(ocr.NoEngine) as caught:
        ocr.read_image(str(path))
    assert "crossfoot[ocr]" in str(caught.value)
    assert "crossfoot[ocr-heavy]" in str(caught.value)


def test_the_model_download_is_opt_in_and_the_message_says_what_it_costs():
    """
    The first version blocked it outright on the reasoning that no network
    request may ever happen. That conflated "your documents never leave this
    machine" — the promise — with "nothing is ever fetched", and it killed the
    only OCR path available to somebody who cannot install system software,
    which is most people.
    """
    source = open(ocr.__file__, encoding="utf-8").read()
    assert "CROSSFOOT_ALLOW_MODEL_DOWNLOAD" in source
    assert "download_enabled=allowed" in source
    # And the distinction is stated where somebody will actually read it.
    # Matched on a phrase short enough to survive line wrapping — the first
    # version of this assertion looked for a sentence the formatter had split
    # across two lines, so it failed on prose that was present.
    assert "receipts are involved" in source
    assert "documents still never leave this" in source


def test_the_drop_folder_refuses_to_be_committed(tmp_path):
    """
    The folder the window drops bank statements into lives inside a git
    checkout, because a person has to be able to open it. So somebody who
    clones this, double-clicks the launcher and drops a statement in would see
    it in `git status`, and one `git add -A` publishes their bank statement.
    The sister project shipped a portfolio history to PyPI exactly this way.

    Two defences, and the second is not redundant: this repository ignores the
    folder, and the folder ignores itself so it stays protected wherever it is
    copied, moved or synced to.
    """
    inbox = I.make(str(tmp_path / "crossfoot-inbox"))
    guard = os.path.join(inbox, ".gitignore")
    assert os.path.exists(guard)
    assert open(guard, encoding="utf-8").read().strip().endswith("*")


def test_the_repository_ignores_the_default_drop_folder():
    import subprocess

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    probe = os.path.join(I.DEFAULT, "somebodys-bank-export.csv")
    result = subprocess.run(["git", "check-ignore", "-q", probe],
                            cwd=root, capture_output=True)
    assert result.returncode == 0, (
        f"{probe} is not ignored — a user's bank statement would appear in "
        "git status")
