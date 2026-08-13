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

from crossfoot.ingest import statement as S
from crossfoot.match import candidates as M
from crossfoot.read import document, receipt as R
from crossfoot.review import queue as Q


def _money(c) -> str:
    c = abs(int(c or 0))
    return f"{c // 100:,}.{c % 100:02d}"


def _receipts_in(directory: str):
    receipts, unreadable = [], []
    if not os.path.isdir(directory):
        return receipts, unreadable
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        try:
            read = document.read(path)
        except document.UnreadableDocument as e:
            unreadable.append((name, str(e)))
            continue
        parsed = R.as_receipt(R.extract(read["text"]))
        # The name the receipt prints, falling back to the filename. A photo
        # called IMG_2043 names no merchant, and the matcher tests this string
        # against the bank's descriptor.
        parsed["merchant"] = (parsed.get("merchant")
                              or os.path.splitext(name)[0].replace("_", " "))
        parsed["source"] = name
        parsed["reader"] = read["reader"]
        parsed["degraded"] = read.get("degraded", False)
        receipts.append(parsed)
    return receipts, unreadable


def check(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="crossfoot check")
    parser.add_argument("--statement", required=True)
    parser.add_argument("--receipts", default="receipts")
    args = parser.parse_args(argv)

    try:
        with open(args.statement, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as e:
        # A mistyped path is the commonest first run and it answered with a
        # traceback, which reads as broken software rather than a typo.
        print(f"Cannot read {args.statement}: {e.strerror}.", file=sys.stderr)
        return 2

    try:
        parsed = S.parse(text, args.statement)
    except S.StatementError as e:
        # Refusals are the point of the ingest step, not a crash. They carry
        # the reason and what to do about it, so print the reason.
        print(f"This statement cannot be used:\n  {e}")
        return 2
    acceptance = S.accept(parsed)
    if not acceptance["usable"]:
        print("This statement is not complete, so nothing below it can be trusted:")
        for problem in acceptance["problems"]:
            print(f"  {problem}")
        return 2
    if not acceptance["verified_complete"]:
        print("Note: this export carries neither a running balance nor a declared\n"
              "period total, so nothing here can confirm it is whole.\n")

    receipts, unreadable = _receipts_in(args.receipts)
    for name, why in unreadable:
        print(f"unreadable: {name}: {why}")

    charges = [{"amount": l["amount"], "description": l["description"],
                "date": l["date"]} for l in parsed["lines"]]
    built = Q.build(M.match_all(receipts, charges))

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
    print("usage: crossfoot check --statement FILE [--receipts DIR]\n"
          "       crossfoot review --statement FILE [--receipts DIR]", file=sys.stderr)
    return 2


if __name__ == "__main__":                  # pragma: no cover
    raise SystemExit(main())
