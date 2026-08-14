"""
Two commands: run the pipeline and print what it found, or open the reviewer.

`crossfoot check` is read-only by construction — it imports the queue and never
the decision writer, so it can be run from anything, including a model, without
being able to clear a single item.
"""
import argparse
import os
import subprocess
import sys

from crossfoot import audit as A
from crossfoot import doctor as DOC
from crossfoot.export import rows as E
from crossfoot.export import targets as T
from crossfoot.ingest import inbox as I
from crossfoot.ingest import statement as S
from crossfoot.pipeline import Refused, load
# The *reader* of the decision log, which cannot write one. `export` needs to
# know which discrepancies a person accepted; importing the writer to find out
# would put `record` one attribute away from every consumer of this module.
from crossfoot.review import ledger as D
from crossfoot.review import queue as Q


def _money(c) -> str:
    c = abs(int(c or 0))
    return f"{c // 100:,}.{c % 100:02d}"


def _inputs(args):
    """
    Resolve --inbox into a statement and a receipts folder, or pass the
    explicit pair through.

    One folder is the first run; the explicit pair is every run after, when
    somebody has a place they keep things. Both reach the same loader.
    """
    if not getattr(args, "inbox", None):
        return args.statement, args.receipts, None
    sorted_folder = I.sort(args.inbox)
    if sorted_folder["problem"]:
        return None, None, sorted_folder
    return sorted_folder["statements"][0], args.inbox, sorted_folder


def _report_inbox(sorted_folder):
    if not sorted_folder:
        return
    for name, why in sorted_folder["ignored"]:
        # Skipped files are announced. Somebody who drops a file in and sees
        # nothing happen concludes the tool is broken when it is being careful.
        print(f"skipped {name}: {why}", file=sys.stderr)
    print(f"inbox: 1 statement, {len(sorted_folder['receipts'])} receipts",
          file=sys.stderr)


def audit(argv=None) -> int:
    """
    The statement alone. No receipts, no OCR, nothing optional installed.

    This is the command that works on the first run, before anybody has
    photographed anything — and after the 55-receipt measurement it is the one
    whose inputs cannot be misread, because a bank export is a CSV.
    """
    parser = argparse.ArgumentParser(prog="crossfoot audit")
    parser.add_argument("statement", nargs="?", help="a CSV or OFX bank export")
    parser.add_argument("--statement", dest="named")
    parser.add_argument("--inbox", help="a folder; the statement is found by content")
    parser.add_argument("--window", type=int, default=None,
                        help="days apart two identical charges can be (default 3)")
    args = parser.parse_args(argv)

    path = args.statement or args.named
    sorted_folder = None
    if not path and args.inbox:
        sorted_folder = I.sort(args.inbox)
        if sorted_folder["problem"]:
            print(sorted_folder["problem"], file=sys.stderr)
            return 2
        path = sorted_folder["statements"][0]
    if not path:
        parser.error("give a statement file, or --inbox FOLDER")

    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
            text = handle.read()
        statement = (S.parse_ofx(text) if "<OFX" in text[:2000].upper()
                     else S.parse_csv(text))
    except S.StatementError as e:
        print(f"Cannot read {os.path.basename(path)}: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"Cannot open {path}: {e}", file=sys.stderr)
        return 2

    found = A.audit(statement, args.window)
    _print_audit(found, os.path.basename(path))
    # 1 when there is something to act on, 0 when there is not, 2 when the file
    # could not be trusted. A script can branch on it.
    if found["suppressed"]:
        return 2
    return 1 if found["findings"] else 0


def _print_audit(found, name):
    state = found["completeness"]["state"]
    print(f"{name}: {found['rows']} rows, {state}")

    if found["suppressed"]:
        print()
        print("  " + found["why"])
        print()
        print("  Nothing else is reported from this file. A duplicate found in")
        print("  a statement with rows missing is an artefact of the gap, and")
        print("  the rows that were never read cannot be reported as missing —")
        print("  so a short, clean page here would be a misleading one.")
        return

    if state == A.UNVERIFIABLE:
        print(f"  {found['completeness']['why']}")

    print()
    if found["findings"]:
        print(f"  What looks wrong — {_money(found['at_risk'])} at stake")
        for finding in found["findings"]:
            label = {"paid_twice": "PAID TWICE",
                     "price_rose": "PRICE ROSE",
                     "new_recurring": "NEW RECURRING"}[finding["kind"]]
            print(f"    {_money(finding['at_risk']):>10}  {label:<14} "
                  f"{finding['why']}")
    else:
        print("  Nothing looks wrong.")

    if found["recurring"]:
        print()
        # Deliberately not called a finding. Whether somebody still wants a
        # subscription is not in the statement, and a tool that says "you are
        # not using this" is guessing at the one thing it cannot see.
        yearly = sum(int(r["a_year"]) for r in found["recurring"])
        print(f"  Recurring charges — {_money(yearly)} a year, "
              f"not a finding, just what is there")
        for item in found["recurring"]:
            print(f"    {_money(item['a_year']):>10}/yr  "
                  f"{_money(item['latest']):>8} × {item['charges']:<3} "
                  f"{item['merchant']}  since {item['first_seen']}")


def check(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="crossfoot check")
    parser.add_argument("--inbox", help="one folder holding both; sorted by content")
    parser.add_argument("--statement")
    parser.add_argument("--receipts", default="receipts")
    args = parser.parse_args(argv)
    if not args.inbox and not args.statement:
        parser.error("give --inbox FOLDER, or --statement FILE")

    statement, receipts, sorted_folder = _inputs(args)
    if statement is None:
        print(sorted_folder["problem"], file=sys.stderr)
        return 2
    _report_inbox(sorted_folder)

    try:
        loaded = load(statement, receipts)
    except Refused as e:
        print(str(e), file=sys.stderr if "Cannot read" in str(e) else sys.stdout)
        return e.code

    if not loaded["acceptance"]["verified_complete"]:
        print("Note: this export carries neither a running balance nor a declared\n"
              "period total, so nothing here can confirm it is whole.\n")
    for name, why in loaded["unreadable"]:
        print(f"unreadable: {name}: {why}")

    built = loaded["built"]
    print(built["headline"])
    print("-" * len(built["headline"]))
    for item in built["needs_you"]:
        charge = item["charge"]
        print(f"{item['state']:>10}  {_money(item['at_risk']):>12}  "
              f"{charge.get('date', ''):>10}  {charge.get('description', '')[:34]}")
        print(f"{'':>10}  {item['why']}")
    # A non-zero exit for anything a person still has to look at, so this can be
    # a step in something larger without the caller parsing prose.
    return 1 if built["needs_you"] else 0


def export(argv=None) -> int:
    """
    Write the ledger, verdict attached, for a target's own importer to read.

    Reads the decision log so that a discrepancy a person looked at and
    accepted leaves as `accepted-by-you` rather than being flattened into
    either neighbour — but never *writes* to it, which is why this lives here
    and not in the reviewer.
    """
    parser = argparse.ArgumentParser(prog="crossfoot export")
    parser.add_argument("--inbox", help="one folder holding both; sorted by content")
    parser.add_argument("--statement")
    parser.add_argument("--receipts", default="receipts")
    parser.add_argument("--decisions", default="decisions.jsonl")
    parser.add_argument("--to", default="generic", choices=sorted(T.TARGETS))
    parser.add_argument("--out", help="output file; stdout when omitted")
    parser.add_argument("--account", default="",
                        help="firefly: the asset account id these belong to")
    args = parser.parse_args(argv)
    if not args.inbox and not args.statement:
        parser.error("give --inbox FOLDER, or --statement FILE")

    statement, receipts, sorted_folder = _inputs(args)
    if statement is None:
        print(sorted_folder["problem"], file=sys.stderr)
        return 2

    try:
        loaded = load(statement, receipts)
    except Refused as e:
        print(str(e), file=sys.stderr)
        return e.code

    try:
        decided = D.read_all(args.decisions)
    except D.TamperedLog as e:
        # Not a warning. The log is what says which discrepancies a person
        # accepted, and exporting against a log that cannot be trusted writes
        # somebody's ledger from a record somebody edited.
        print(f"Refusing to export: {e}", file=sys.stderr)
        return 2
    except OSError:
        decided = []

    built = loaded["built"]
    rows = E.rows_for(built["needs_you"] + built["filed_items"], decided)
    rendered = T.TARGETS[args.to]["render"](rows)

    if not args.out:
        sys.stdout.write(rendered)
    else:
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            fh.write(rendered)
        # Firefly's importer wants a column mapping, and doing it by hand is
        # twenty dropdowns the first time and twenty again next month.
        if args.to == "firefly":
            config = os.path.splitext(args.out)[0] + ".json"
            with open(config, "w", encoding="utf-8") as fh:
                fh.write(T.firefly_config(args.account))
            print(f"wrote {args.out} and {config}", file=sys.stderr)
        else:
            print(f"wrote {args.out}", file=sys.stderr)

    print(E.summary(rows), file=sys.stderr)
    print(T.TARGETS[args.to]["note"], file=sys.stderr)
    return 0


def review(argv=None) -> int:
    """Hand off to Streamlit, which owns the only path to a decision."""
    app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review", "app.py")
    try:
        import streamlit                      # noqa: F401
    except ImportError:
        print("The reviewer needs Streamlit, which is an optional extra so that\n"
              "the checking layer stays installable on its own:\n"
              "    pip install 'crossfoot[ui]'", file=sys.stderr)
        return 1
    return subprocess.call([sys.executable, "-m", "streamlit", "run", app, "--",
                            *(argv if argv is not None else sys.argv[1:])])


def _survive_a_narrow_console():
    """
    Never lose a whole report to one character.

    Found by running this on a Windows console at code page 874: a middle dot
    in the summary line raised UnicodeEncodeError and took the entire output
    with it. The tests could not see it because pytest captures text and never
    encodes. Keeping the terminal's own encoding and only relaxing the error
    handler means a UTF-8 console still prints the real character and a narrow
    one substitutes a question mark, which is a cosmetic loss rather than a
    traceback.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass                             # a pipe or a capture; nothing to fix


def main(argv=None) -> int:
    _survive_a_narrow_console()
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] == "review":
        return review(argv[1:])
    if argv and argv[0] == "audit":
        return audit(argv[1:])
    if argv and argv[0] == "check":
        return check(argv[1:])
    if argv and argv[0] == "export":
        return export(argv[1:])
    if argv and argv[0] == "doctor":
        print(DOC.render())
        return 0
    if argv and argv[0] in ("-h", "--help", "help"):
        print(_usage())
        return 0

    # No arguments opens the window, because for most of the people this is
    # for, a page of usage text *is* the failure -- they came to look at their
    # receipts, not to learn a flag. Anyone who wanted the command line typed a
    # subcommand and never reaches here.
    if not window_available():
        print("Crossfoot needs one more piece to open its window:\n"
              "    pip install 'crossfoot[ui]'\n\n"
              "Or use it from the command line:\n" + _usage(), file=sys.stderr)
        return 1
    return review(argv)


def window_available() -> bool:
    """
    Whether the window can be opened at all.

    A function rather than an inline import so a test can say which case it is
    testing. The first version asked the environment, so the "opens the window"
    tests passed on my machine, where Streamlit is installed, and failed on CI,
    where it is not -- measuring the runner instead of the behaviour, which is
    the same mistake this project's sister repo had to fix in its conftest.
    """
    try:
        import streamlit                    # noqa: F401
        return True
    except ImportError:
        return False


def _usage() -> str:
    """
    The screen a confused person sees. It leads with the easy path, and every
    subcommand and export target appears in it -- there is a test, because it
    once told people to name two paths on the command line for a week after
    the one-folder intake shipped.
    """
    return (
        "Crossfoot - check your bank statement, and your receipts against it.\n"
        "\n"
        "  crossfoot audit statement.csv         what is wrong with the\n"
        "                                        statement alone: paid twice,\n"
        "                                        price rises, new subscriptions\n"
        "\n"
        "  crossfoot                             open the window (does everything)\n"
        "  crossfoot doctor                      what this computer can read\n"
        "\n"
        "  `audit` needs nothing installed and no receipts. Start there.\n"
        "\n"
        "  Or from the command line, with one folder holding both:\n"
        "\n"
        "    crossfoot check  --inbox ./inbox    what does not add up\n"
        "    crossfoot review --inbox ./inbox    the window, on that folder\n"
        "    crossfoot export --inbox ./inbox --to actual --out ledger.csv\n"
        "\n"
        "  Which file is the statement is worked out by reading them, so it\n"
        "  does not matter what they are called.\n"
        "\n"
        "  --to    generic | actual | firefly | beancount\n"
        "  If you keep them apart: --statement FILE --receipts DIR")


if __name__ == "__main__":                  # pragma: no cover
    raise SystemExit(main())
