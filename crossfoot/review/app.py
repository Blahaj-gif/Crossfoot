"""
The review queue, and the only place a decision is taken.

This module is the sole importer of `crossfoot.review.decisions`. That is the
whole safety argument: a model can be handed the ingest, the reader, the
matcher and the queue and still have no reachable path to clearing an item,
because clearing one exists only behind a button in this file.

Run it with:

    crossfoot-review --statement bank.csv --receipts ./receipts
"""
import argparse
import os
import re
import sys

import streamlit as st

from crossfoot import verdict as V
from crossfoot import pipeline as P
from crossfoot.read import document
from crossfoot.review import decisions as D  # the write path; this file only
from crossfoot.review import queue as Q


def _escape(text) -> str:
    """
    A merchant descriptor is a string that merchant chose, rendered in our UI.

    Streamlit blocks raw HTML by default, so the exposure is markdown rather
    than script -- but a descriptor containing brackets and a parenthesis is a
    link, and one containing asterisks can hide the characters around it. A
    name printed on a page about money should be the name.
    """
    return re.sub(r"([\`*_{}\[\]()#+.!|~>-])", r"\", str(text or ""))


def _money(c) -> str:
    if c is None:
        return "—"
    c = abs(int(c))
    return f"{c // 100:,}.{c % 100:02d}"


@st.cache_data(show_spinner="Reading…")
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


def _render_item(item, index, log_path):
    charge = item["charge"]
    badge = {Q.FAILED: ":red[does not reconcile]",
             Q.AMBIGUOUS: ":orange[more than one receipt fits]",
             Q.UNVERIFIED: ":gray[unchecked]"}[item["state"]]

    with st.container(border=True):
        left, right = st.columns([5, 1])
        left.markdown(f"**{_escape(charge.get('date', ''))} · "
                      f"{_escape(charge.get('description', ''))}**"
                      f"  \n{badge}")
        right.markdown(f"### {_money(item['at_risk'])}")

        st.markdown(item["why"])

        # Both numbers, side by side. "Does not reconcile" on its own tells a
        # person nothing they can act on.
        for check in item["checks"]:
            if check.ok is False:
                st.markdown(
                    f"- `{check.name}` — the filing states **{_money(check.expected)}** "
                    f"and its own parts make **{_money(check.actual)}**")

        if item["ambiguous"]:
            st.markdown("**Candidates:**")
            for n, candidate in enumerate(item["ambiguous"], start=1):
                r = candidate["receipt"]
                st.markdown(f"{n}. {_escape(r.get('source') or r.get('merchant'))} — "
                            f"{_money(V.cents(r.get('total')))}, name similarity "
                            f"{candidate['name_similarity']:.2f}")

        receipt = item.get("receipt") or {}
        if receipt.get("degraded"):
            st.warning(f"`{receipt.get('source')}` was read without a layout "
                       f"parser ({receipt.get('reader')}). Treat its numbers as "
                       "evidence, not as figures.")
        extraction = receipt.get("_extraction") or {}
        if extraction.get("needs_human"):
            with st.expander("Fields this could not read confidently"):
                for name in extraction["needs_human"]:
                    field = extraction["fields"][name]
                    st.markdown(f"**{name}** — `{field.line.strip()}` "
                                f"(line {field.line_number}, {field.how})")

        # The gate. Nothing above this point can write; nothing below it runs
        # without a click.
        note = st.text_input("Note", key=f"note{index}",
                             placeholder="why, for whoever reads this next year")
        a, b, c = st.columns(3)
        if a.button("Accept as printed", key=f"acc{index}",
                    help="the merchant's own arithmetic is wrong and you know it"):
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


def main(argv=None):
    parser = argparse.ArgumentParser(prog="crossfoot-review")
    parser.add_argument("--statement", required=True)
    parser.add_argument("--receipts", default="receipts")
    parser.add_argument("--decisions", default="decisions.jsonl")
    args, _ = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    st.set_page_config(page_title="Crossfoot", layout="centered")
    st.title("Crossfoot")

    try:
        loaded = _load(args.statement, args.receipts,
                       _stamp_for(args.statement, args.receipts))
    except P.Refused as e:
        st.error(str(e))
        st.stop()
    acceptance, receipts = loaded["acceptance"], loaded["receipts"]
    unreadable = loaded["unreadable"]

    # A short statement stops the page. Every verdict below would be
    # individually correct and the page as a whole would be a lie.
    if not acceptance["usable"]:
        st.error("This statement is not complete, so nothing below it can be "
                 "trusted:\n\n" + "\n\n".join(f"- {p}" for p in acceptance["problems"]))
        st.stop()
    if not acceptance["verified_complete"]:
        st.info("This export carries neither a running balance nor a declared "
                "period total, so nothing here can confirm it is whole. Every "
                "verdict below is about the rows that are present.")

    for name, why in unreadable:
        st.warning(f"`{name}` could not be read: {why}")

    built = loaded["built"]
    try:
        outstanding = D.outstanding(built["needs_you"], args.decisions)
    except D.TamperedLog as e:
        # Not a warning. Everything this page hides, it hides because the log
        # said a person decided it, and a log that cannot be trusted hides the
        # wrong things.
        st.error(str(e))
        st.stop()

    st.subheader(built["headline"])
    st.caption(f"{len(receipts)} receipts read · decisions logged to "
               f"`{args.decisions}` · readers: {', '.join(document.readers())}")

    if not outstanding:
        st.success("Nothing outstanding." if not built["unverified"] else
                   f"Nothing outstanding — but {built['unverified']} charges were "
                   "never checked, which is not the same as clean.")
        return

    for index, item in enumerate(outstanding):
        _render_item(item, index, args.decisions)


if __name__ == "__main__":                  # pragma: no cover - streamlit entry
    main()
