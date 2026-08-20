"""Can the amounts an engine reads be resolved into line items and a total?

The previous pass counted how many money-shaped strings RapidOCR finds. That is
necessary and not sufficient: crossfooting needs to know which of them are line
items and which is the total, and then needs every one of them to be right.

This asks the question directly, and the test is the product's own rule: **does
some subset of the amounts sum to another amount?** If it does, the page
contains an arithmetic relationship an engine could act on. If it does not, the
next question is how far away it was, which is the measurement Crossfoot never
had — "0 of 112" collapses "wildly wrong" and "off by one digit" into the same
zero.

Reported per receipt:

  exact       a subset sums to the largest amount, to the cent
  near        the best subset misses by <= 0.10, or by a single-digit OCR
              confusion (4/8, 1/7, 3/8, 5/6, 0/8) in one of its members
  far         neither

Nothing here is a reconciliation rate for Crossfoot. It has no idea which rows
are tax or tip, it does not read the printed total's label, and it is allowed
to search subsets, which a real reader is not. It is an upper bound on what is
*available* in the text, which is exactly what has to be known before deciding
whether the pipeline is worth building.
"""
import itertools
import json
import os
import re
import sys

CORPUS = r"C:\mcp-servers\crossfoot\tests\corpus\photographs"
MONEY = re.compile(r"(?<![\d.,])(\d{1,6})[.,](\d{2})(?![\d])")
CONFUSIONS = [("4", "8"), ("8", "4"), ("1", "7"), ("7", "1"),
              ("3", "8"), ("8", "3"), ("5", "6"), ("6", "5"),
              ("0", "8"), ("8", "0"), ("9", "4"), ("6", "8")]


def cents(text):
    out = []
    for whole, frac in MONEY.findall(text):
        try:
            out.append(int(whole) * 100 + int(frac))
        except ValueError:
            pass
    return out


def best_subset(parts, target, cap=18):
    """Closest a subset of `parts` gets to `target`. Exhaustive but bounded."""
    parts = sorted(parts, reverse=True)[:cap]
    best = None
    for size in range(1, len(parts) + 1):
        for combo in itertools.combinations(parts, size):
            gap = abs(sum(combo) - target)
            if best is None or gap < best:
                best = gap
            if best == 0:
                return 0
    return best if best is not None else target


def one_digit_away(parts, target):
    """Would a single known OCR confusion in one member close the gap?"""
    for i, p in enumerate(parts):
        s = str(p)
        for a, b in CONFUSIONS:
            if a in s:
                swapped = int(s.replace(a, b, 1))
                trial = parts[:i] + [swapped] + parts[i + 1:]
                if best_subset(trial, target) == 0:
                    return True
    return False


def main():
    from rapidocr_onnxruntime import RapidOCR

    ocr = RapidOCR()
    files = sorted(
        os.path.join(CORPUS, f)
        for f in os.listdir(CORPUS)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    )
    rows = []
    for i, path in enumerate(files, 1):
        name = os.path.basename(path)
        try:
            result, _ = ocr(path)
        except Exception as e:
            rows.append({"file": name, "error": str(e)[:60]})
            continue
        text = "\n".join(t for _, t, _ in (result or []))
        amounts = cents(text)
        row = {"file": name, "kind": name.split("--")[0], "n": len(amounts)}
        if len(amounts) >= 3:
            target = max(amounts)
            rest = [a for a in amounts if a is not target]
            rest = amounts[:]
            rest.remove(target)
            gap = best_subset(rest, target)
            row["target"] = target
            row["gap"] = gap
            if gap == 0:
                row["verdict"] = "exact"
            elif gap <= 10 or one_digit_away(rest, target):
                row["verdict"] = "near"
            else:
                row["verdict"] = "far"
        else:
            row["verdict"] = "too few amounts"
        rows.append(row)
        if i % 10 == 0:
            print(f"  {i}/{len(files)}", flush=True)

    with open(os.path.join(os.path.dirname(__file__), "ocr_lineitems.json"), "w") as f:
        json.dump(rows, f, indent=1)

    from collections import Counter
    c = Counter(r.get("verdict", "error") for r in rows)
    print(f"\n{len(rows)} receipts")
    for k in ("exact", "near", "far", "too few amounts", "error"):
        if c[k]:
            print(f"  {k:<18} {c[k]}")
    interesting = [r for r in rows if r.get("verdict") in ("exact", "near")]
    print(f"\narithmetic is available on {len(interesting)} of {len(rows)}")
    for r in sorted(interesting, key=lambda r: r.get("gap", 0))[:12]:
        print(f"    {r['verdict']:<6} gap {r.get('gap',0):>6}  {r['n']:>3} amounts  {r['file'][:52]}")


if __name__ == "__main__":
    main()
