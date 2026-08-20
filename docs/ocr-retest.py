"""Re-test the receipt corpus with an engine Crossfoot never tried.

Crossfoot measured Tesseract and EasyOCR and reported 0 of 112 receipts
reconciling. That number is not very informative on its own: crossfooting is a
conjunction, so forty numeric fields at 98% per-field accuracy reconcile about
45% of the time and at 92% essentially never. A single zero therefore collapses
a wide range of engine quality.

So this measures two things the original did not:

  found      how many numbers the engine reads off the receipt at all
  legible    whether the read is clean enough to be worth arithmetic

It deliberately does *not* claim a reconciliation rate. Deciding which numbers
are line items and which is the total is Crossfoot's job, not this script's,
and guessing at it here would produce exactly the kind of number this project
exists not to publish.
"""
import json
import os
import re
import sys
import time

CORPUS = r"C:\mcp-servers\crossfoot\tests\corpus\photographs"
MONEY = re.compile(r"\d+[.,]\d{2}\b")


def engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def read(ocr, path):
    result, _ = ocr(path)
    if not result:
        return [], 0.0
    lines = [(box_text, float(score)) for _, box_text, score in result]
    return lines, sum(s for _, s in lines) / max(len(lines), 1)


def main(limit=None):
    ocr = engine()
    files = sorted(
        os.path.join(CORPUS, f)
        for f in os.listdir(CORPUS)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    )
    if limit:
        files = files[:limit]

    out = []
    started = time.time()
    for i, path in enumerate(files, 1):
        try:
            lines, mean_conf = read(ocr, path)
        except Exception as e:
            out.append({"file": os.path.basename(path), "error": str(e)[:80]})
            continue
        text = "\n".join(t for t, _ in lines)
        amounts = MONEY.findall(text)
        out.append(
            {
                "file": os.path.basename(path),
                "kind": os.path.basename(path).split("--")[0],
                "lines": len(lines),
                "chars": len(text),
                "amounts": len(amounts),
                "mean_conf": round(mean_conf, 3),
            }
        )
        if i % 10 == 0:
            print(f"  {i}/{len(files)}  {time.time()-started:.0f}s", flush=True)

    with open(os.path.join(os.path.dirname(__file__), "ocr_retest.json"), "w") as f:
        json.dump(out, f, indent=1)

    ok = [r for r in out if "error" not in r]
    withtext = [r for r in ok if r["lines"] > 0]
    withmoney = [r for r in ok if r.get("amounts", 0) >= 3]
    print(f"\n{len(out)} receipts, {len(out)-len(ok)} errored")
    print(f"  any text read ............ {len(withtext)}")
    print(f"  three or more amounts .... {len(withmoney)}")
    if withtext:
        conf = sorted(r["mean_conf"] for r in withtext)
        print(f"  median line confidence ... {conf[len(conf)//2]:.3f}")
        print(f"  median amounts found ..... {sorted(r['amounts'] for r in withtext)[len(withtext)//2]}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
