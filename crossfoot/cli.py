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

from crossfoot.export import rows as E
from crossfoot.export import targets as T
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


def check(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="crossfoot check")
    parser.add_argument("--statement", required=True)
    parser.add_argument("--receipts", default="receipts")
    args = parser.parse_args(argv)

    try:
        loaded = load(args.statement, args.receipts)
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
    parser.add_argument("--statement", required=True)
    parser.add_argument("--receipts", default="receipts")
    parser.add_argument("--decisions", default="decisions.jsonl")
    parser.add_argument("--to", default="generic", choices=sorted(T.TARGETS))
    parser.add_argument("--out", help="output file; stdout when omitted")
    parser.add_argument("--account", default="",
                        help="firefly: the asset account id these belong to")
    args = parser.parse_args(argv)

    try:
        loaded = load(args.statement, args.receipts)
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
    if argv and argv[0] == "check":
        return check(argv[1:])
    if argv and argv[0] == "export":
        return export(argv[1:])
    print("usage: crossfoot check  --statement FILE [--receipts DIR]\n"
          "       crossfoot export --statement FILE [--receipts DIR]\n"
          "                        [--to generic|actual|firefly|beancount] [--out FILE]\n"
          "       crossfoot review --statement FILE [--receipts DIR]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":                  # pragma: no cover
    raise SystemExit(main())
