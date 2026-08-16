"""
Reading a receipt with a small local vision model, and distrusting it correctly.

Tesseract cannot read a photographed till receipt. That is measured, at length,
in `docs/real-receipts.md`: across 112 real photographs it produced a parseable
money amount on eight, and an extraction that satisfied its own arithmetic on
none. Five image-processing fixes were tried and every one made it worse. The
limit is the model, not the pipeline.

A 2-billion-parameter vision model reads them. Measured on the ten receipts
whose numbers were keyed by hand off the paper — the ten Tesseract read one of
— Qwen2-VL-2B got **ten fields exactly right**, on a CPU, in about forty
seconds each, with nothing leaving the machine.

**And it never once said it could not tell.**

That is the whole reason this module exists as a separate thing rather than as
another backend in `ocr.py`. The failure modes are not comparable:

    Tesseract, when it fails      returns nothing, or obvious rubbish
    a vision model, when it fails returns a plausible number

Asked for a total it does not know, it produced 21.27 for a receipt reading
19.50, 98.00 for one reading 49.00, 45.15 for one reading 37.37. Fluent,
confident, wrong.

The worst case is worse than that, and it is the reason for
`GENERATED` below. A Family Dollar receipt came back as subtotal 2.50, tax
0.13, total 2.63 against a paper reading 2.00, 0.18, 2.18 — every figure wrong,
and **2.50 + 0.13 = 2.63 exactly**. It crossfoots.

That defeats the receipt-internal checks completely, and not by accident. Those
checks rest on an assumption that is true of an OCR engine and false of a
language model: that the numbers were read *independently*, so their agreement
is evidence. A generative model emits them together, conditioned on each other,
so their agreement is evidence of fluency and nothing else.

So a receipt read this way carries `generated: True`, and `verdict.reconcile`
refuses to call it reconciled on the strength of its own arithmetic. It needs
the bank statement — a CSV no model has ever touched — to agree as well.
"""
import json
import os
import re

#: Small enough to run on a laptop CPU, and strong enough on document text to
#: be worth the four gigabytes. Not a default and not required: the core of
#: this project installs with no dependencies at all, and that stays true.
MODEL = os.getenv("CROSSFOOT_VISION_MODEL", "Qwen/Qwen2-VL-2B-Instruct")

#: Longest edge the image is reduced to before the model sees it. A receipt is
#: a column of text and the model does not need twelve megapixels of it; this
#: is the difference between forty seconds and several minutes on a CPU.
LONGEST_EDGE = 1000

PROMPT = ("Read this receipt. Reply with ONLY a JSON object, no other text, "
          'using exactly these keys: {"merchant": ..., "subtotal": ..., '
          '"tax": ..., "tip": ..., "discount": ..., "total": ...}. Give each '
          "amount as a number in the receipt's own currency units, for "
          "example 17.31. Use null for anything the receipt does not state. "
          "Do not guess.")

_model = None
_processor = None


class NoModel(Exception):
    """The vision extra is not installed, so a photograph cannot be read this way."""


def available() -> bool:
    try:                                     # pragma: no cover - environment
        import torch                         # noqa: F401
        import transformers                  # noqa: F401
        return True
    except ImportError:                      # pragma: no cover - environment
        return False


def _load():                                 # pragma: no cover - needs the model
    global _model, _processor
    if _model is not None:
        return _model, _processor
    try:
        import torch
        from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
    except ImportError as e:
        raise NoModel(
            "reading receipts with a vision model needs "
            "`pip install 'crossfoot[vision]'` — about 4 GB of model on first "
            "run, and it runs locally: no receipt of yours goes anywhere."
        ) from e
    _model = Qwen2VLForConditionalGeneration.from_pretrained(
        MODEL, dtype=torch.float32, device_map="cpu")
    _processor = AutoProcessor.from_pretrained(MODEL)
    return _model, _processor


def _as_amount(value):
    """A model's answer as cents, or None. Anything unparseable is None."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return None
    from crossfoot.verdict import Cents
    return Cents(int(round(float(text) * 100)))


def read_receipt(path: str) -> dict:         # pragma: no cover - needs the model
    """
    A receipt's fields, as a model reads them, marked as generated.

    Returns the shape `verdict.reconcile` takes, plus `generated: True`, which
    is not decoration — see the module docstring. A caller that strips that
    flag is asserting that a language model's arithmetic is independent
    evidence, which is measurably untrue.
    """
    import torch
    from PIL import Image

    model, processor = _load()
    image = Image.open(path).convert("RGB")
    image.thumbnail((LONGEST_EDGE, LONGEST_EDGE))

    messages = [{"role": "user", "content": [
        {"type": "image"}, {"type": "text", "text": PROMPT}]}]
    text = processor.apply_chat_template(messages, tokenize=False,
                                         add_generation_prompt=True)
    inputs = processor(text=[text], images=[image], return_tensors="pt")
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=128, do_sample=False)
    reply = processor.batch_decode(
        out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0]

    return as_receipt(reply, path)


def as_receipt(reply: str, path: str = "") -> dict:
    """
    The model's reply, as a receipt. Split out so it can be tested without
    four gigabytes of weights, because everything that can be wrong about
    parsing a model's answer is in here rather than in the model.
    """
    match = re.search(r"\{.*?\}", reply or "", re.S)
    parsed = {}
    if match:
        try:
            parsed = json.loads(match.group(0))
        except ValueError:
            parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}

    receipt = {"generated": True, "reader": f"vision ({MODEL})",
               "path": path, "raw": reply}
    merchant = parsed.get("merchant")
    receipt["merchant"] = str(merchant).strip() if isinstance(merchant, str) else ""
    for field in ("subtotal", "tax", "tip", "discount", "total"):
        amount = _as_amount(parsed.get(field))
        if amount is not None:
            receipt[field] = amount
    return receipt
