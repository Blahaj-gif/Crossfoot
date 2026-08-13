"""
The window, which is the whole product.

Everything a person needs to do happens here: drop the files in, see what does
not add up, decide, and take the result away. There is no second command to
type and no file path to invent, because the friction that actually stops
people is not the checking -- it is the three terminal invocations that used to
surround it.

This module is also the sole importer of `crossfoot.review.decisions`, and that
is still the safety argument: an assistant handed the checker, the matcher, the
queue, the exporter and the command line has no reachable function that clears
a queue item, because clearing one exists only behind a button in this file.

Run it with `crossfoot`, with `crossfoot review`, or by double-clicking the
launcher. All three end up here.
"""
import argparse
import os
import re
import sys

import streamlit as st

from crossfoot import doctor
from crossfoot import pipeline as P
from crossfoot import verdict as V
from crossfoot.export import rows as E
from crossfoot.export import targets as T
from crossfoot.ingest import inbox as I
from crossfoot.read import ocr
from crossfoot.review import decisions as D  # the write path; this file only
from crossfoot.review import queue as Q

#: Re-exported from the intake module, which owns it. See `ingest.inbox.DEFAULT`.
DEFAULT_INBOX = I.DEFAULT

_LABELS = {"actual": "Actual Budget", "firefly": "Firefly III",
           "beancount": "Beancount", "generic": "Spreadsheet (CSV)"}


def _escape(text) -> str:
    """
    A merchant descriptor is a string that merchant chose, rendered in our UI.

    Streamlit blocks raw HTML by default, so the exposure is markdown rather
    than script -- but a descriptor containing brackets and a parenthesis is a
    link, and one containing asterisks can hide the characters around it. A
    name printed on a page about money should be the name.
    """
    return re.sub(r"([\\`*_{}\[\]()#+.!|~>-])", r"\\\1", str(text or ""))


def _money(c) -> str:
    if c is None:
        return "-"
    c = abs(int(c))
    return f"{c // 100:,}.{c % 100:02d}"


@st.cache_data(show_spinner="Reading...")
def _load(statement_path: str, receipts_dir: str, _stamp: float):
    """
    Read both sides once, through the same loader the command line uses.

    `_stamp` is the newest mtime under the inputs, so an edited file re-reads
    and an untouched one does not -- rather than a fixed TTL, which would
    either re-read a hundred PDFs every minute or serve a stale total after
    somebody fixed the file it came from.

    The work itself is `crossfoot.pipeline.load`, not a copy of it. There were
    two copies and they had drifted: this one dropped the statement's currency,
    so the cross-currency check was silently dead in the one window where a
    person actually approves things.
    """
    return P.load(statement_path, receipts_dir)


def _stamp_for(*paths) -> float:
    newest = 0.0
    for path in paths:
        if os.path.isfile(path):
            newest = max(newest, os.path.getmtime(path))
        elif os.path.isdir(path):
            for name in os.listdir(path):
                full = os.path.join(path, name)
                if os.path.isfile(full):
                    newest = max(newest, os.path.getmtime(full))
    return newest


# --------------------------------------------------------------------------
# Intake
# --------------------------------------------------------------------------

def _intake(inbox: str):
    """
    The drop zone, and an honest account of what is in the folder.

    Files are written into the inbox folder rather than a hidden temporary one,
    so what the tool is reading is a directory the person can open, and
    deleting a file there is how you take it back.
    """
    dropped = st.file_uploader(
        "Drop your bank export and your receipts here",
        accept_multiple_files=True,
        help="Which file is the statement is worked out by reading them, so it "
             "does not matter what they are called.")
    for upload in dropped or []:
        I.make(inbox)
        target = os.path.join(inbox, upload.name)
        if not os.path.exists(target):
            with open(target, "wb") as fh:
                fh.write(upload.getbuffer())

    found = I.sort(inbox)
    for name, why in found["ignored"]:
        st.caption(f"skipped `{name}` - {why}")
    return found


def _first_run(inbox: str):
    """
    What to say to somebody who has dropped nothing in yet.

    Names the one thing that works with no receipts and nothing installed,
    because "export your bank CSV and you will find out whether you were billed
    twice" is a reason to continue, and "please supply documents" is not.
    """
    st.markdown(
        "#### Start with your bank export\n"
        "Log in to your bank, find **Export** or **Download transactions**, and "
        "choose **CSV**. Drop it above.\n\n"
        "That alone finds charges you may have been **billed twice** for - no "
        "receipts needed, nothing else to install. Add receipts as well and it "
        "will also check that each one adds up and matches what actually left "
        "your account.")
    with st.expander("What this computer can read"):
        _capabilities()
    st.caption(f"Files are kept in `{os.path.abspath(inbox)}`. Nothing is "
               "uploaded anywhere - this window is running on your own machine.")


def _capabilities():
    """The doctor report, inline, so a missing piece is answered before it bites."""
    for capability in doctor.report():
        if capability.ok:
            st.markdown(f"**{capability.name}** - {capability.detail}")
        else:
            st.markdown(f"**{capability.name}** - not yet. {capability.detail}")
            if capability.fix:
                st.code(capability.fix, language="text")


# --------------------------------------------------------------------------
# The queue
# --------------------------------------------------------------------------

_BADGE = {
    Q.DUPLICATE: ":red[possibly billed twice]",
    Q.FAILED: ":red[does not add up]",
    Q.AMBIGUOUS: ":orange[more than one receipt fits]",
    Q.UNVERIFIED: ":grey[not checked]",
}


def _render_item(item, index, log_path):
    charge = item["charge"]

    with st.container(border=True):
        left, right = st.columns([5, 1])
        left.markdown(f"**{_escape(charge.get('date', ''))} - "
                      f"{_escape(charge.get('description', ''))}**  \n"
                      f"{_BADGE[item['state']]}")
        right.markdown(f"### {_money(item['at_risk'])}")

        st.markdown(item["why"])

        if item["state"] == Q.DUPLICATE and item.get("duplicate_of"):
            other = item["duplicate_of"]
            st.caption(f"the earlier one: {_escape(other.get('date', ''))} - "
                       f"{_escape(other.get('description', ''))}")

        # Both numbers, side by side. "Does not reconcile" on its own tells a
        # person nothing they can act on.
        for check in item["checks"]:
            if check.ok is False:
                st.markdown(
                    f"- `{check.name}` - the receipt states "
                    f"**{_money(check.expected)}** and its own parts make "
                    f"**{_money(check.actual)}**")

        if item["ambiguous"]:
            st.markdown("**Which receipt is this?**")
            for n, candidate in enumerate(item["ambiguous"], start=1):
                r = candidate["receipt"]
                st.markdown(f"{n}. {_escape(r.get('source') or r.get('merchant'))} - "
                            f"{_money(V.cents(r.get('total')))}, name similarity "
                            f"{candidate['name_similarity']:.2f}")

        receipt = item.get("receipt") or {}
        if receipt.get("degraded"):
            st.warning(f"`{receipt.get('source')}` was read poorly "
                       f"({receipt.get('reader')}). Treat its numbers as "
                       "evidence, not as figures.")
        extraction = receipt.get("_extraction") or {}
        if extraction.get("needs_human"):
            with st.expander("Numbers this could not read confidently"):
                for name in extraction["needs_human"]:
                    field = extraction["fields"][name]
                    st.markdown(f"**{name}** - `{field.line.strip()}`")
                    # The ink itself, when the text came off a photograph.
                    if field.box and receipt.get("path"):
                        try:
                            st.image(ocr.crop(receipt["path"], field.box),
                                     caption=f"{name}, as it appears on the receipt")
                        except Exception as e:
                            st.caption(f"(could not crop the original: {e})")

        # The gate. Nothing above this point can write; nothing below it runs
        # without a click.
        note = st.text_input("Note", key=f"note{index}",
                             placeholder="why - for whoever reads this next year")
        a, b, c = st.columns(3)
        if a.button("That's fine, file it", key=f"acc{index}",
                    help="you have looked at it and you accept it as it stands"):
            D.record(item, D.ACCEPT_AS_PRINTED, actor=D.HUMAN, note=note,
                     path=log_path)
            st.rerun()
        if b.button("Ignore", key=f"ign{index}"):
            D.record(item, D.IGNORE, actor=D.HUMAN, note=note, path=log_path)
            st.rerun()
        if item["ambiguous"]:
            choice = c.number_input("Pick", min_value=1, key=f"pick{index}",
                                    max_value=len(item["ambiguous"]), step=1)
            if c.button("Use this one", key=f"use{index}"):
                D.record(item, D.MATCH, actor=D.HUMAN,
                         note=f"candidate {choice}: {note}", path=log_path)
                st.rerun()


# --------------------------------------------------------------------------
# Taking the result away
# --------------------------------------------------------------------------

def _downloads(built, decided):
    """
    Every export, as a button. No `--out`, no path to invent, no second command.

    All four are rendered rather than a dropdown-then-generate: the files are a
    few kilobytes, building them all costs nothing, and somebody who does not
    know what Beancount is should be able to see that the answer is "not for
    you" without clicking anything.
    """
    rows = E.rows_for(built["needs_you"] + built["filed_items"], decided)
    st.markdown(f"**{E.summary(rows)}**")

    for column, (name, target) in zip(st.columns(len(T.TARGETS)),
                                      sorted(T.TARGETS.items())):
        column.download_button(
            _LABELS.get(name, name),
            data=target["render"](rows),
            file_name=f"crossfoot-{name}{target['suffix']}",
            mime="text/plain",
            help=target["note"],
            use_container_width=True)

    with st.expander("Firefly III: the column mapping"):
        st.caption("Upload this beside the CSV and the importer will not ask "
                   "you to map twenty columns by hand.")
        account = st.text_input("Asset account id (leave blank to be asked)")
        st.download_button("crossfoot-firefly.json",
                           data=T.firefly_config(account),
                           file_name="crossfoot-firefly.json",
                           mime="application/json")


# --------------------------------------------------------------------------
# The page
# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(prog="crossfoot")
    parser.add_argument("--inbox", default=DEFAULT_INBOX)
    parser.add_argument("--statement")
    parser.add_argument("--receipts")
    parser.add_argument("--decisions", default="decisions.jsonl")
    args, _ = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    st.set_page_config(page_title="Crossfoot", page_icon="🧾", layout="centered")
    st.title("Crossfoot")
    st.caption("Check your receipts against your bank statement. Everything "
               "happens on this computer.")

    # An explicit pair still works, for somebody who keeps their files apart.
    if args.statement:
        statement_path, receipts_dir = args.statement, args.receipts or "receipts"
    else:
        found = _intake(args.inbox)
        if found["problem"]:
            if not found["statements"] and not found["receipts"]:
                _first_run(args.inbox)
            else:
                st.info(found["problem"])
            return
        statement_path, receipts_dir = found["statements"][0], args.inbox

    try:
        loaded = _load(statement_path, receipts_dir,
                       _stamp_for(statement_path, receipts_dir))
    except P.Refused as e:
        st.error(str(e))
        return

    acceptance, built = loaded["acceptance"], loaded["built"]

    # A short statement stops the page. Every verdict below would be
    # individually correct and the page as a whole would be a lie.
    if not acceptance["usable"]:
        st.error("This statement is not complete, so nothing below it can be "
                 "trusted:\n\n"
                 + "\n\n".join(f"- {p}" for p in acceptance["problems"]))
        return
    if not acceptance["verified_complete"]:
        st.info("This export carries neither a running balance nor a declared "
                "period total, so nothing here can confirm it is whole. Every "
                "verdict below is about the rows that are present.")

    for name, why in loaded["unreadable"]:
        st.warning(f"`{name}` could not be read: {why}")

    try:
        outstanding = D.outstanding(built["needs_you"], args.decisions)
        decided = D.read_all(args.decisions) if os.path.exists(args.decisions) else []
    except D.TamperedLog as e:
        # Not a warning. Everything this page hides, it hides because the log
        # said a person decided it, and a log that cannot be trusted hides the
        # wrong things.
        st.error(str(e))
        return

    money = sum(abs(i["at_risk"]) for i in outstanding)
    a, b, c = st.columns(3)
    a.metric("Need you", len(outstanding))
    b.metric("At risk", _money(money))
    c.metric("Reconciled", built["filed"])

    if built["duplicates"]:
        st.error(f"**{built['duplicates']} charge(s) look like you were billed "
                 "twice.** Nothing here proves it - two identical charges could "
                 "be one purchase billed twice or two genuine visits - so have "
                 "a look and decide.")

    st.caption(f"{len(loaded['receipts'])} receipts read - {doctor.summary()} - "
               f"decisions kept in `{args.decisions}`")

    if not outstanding:
        st.success("Nothing outstanding." if not built["unverified"] else
                   f"Nothing outstanding - but {built['unverified']} charges "
                   "were never checked, which is not the same as clean.")
    else:
        for index, item in enumerate(outstanding):
            _render_item(item, index, args.decisions)

    st.divider()
    st.markdown("### Take it away")
    _downloads(built, decided)
    with st.expander("What this computer can read"):
        _capabilities()


if __name__ == "__main__":                  # pragma: no cover - streamlit entry
    main()
