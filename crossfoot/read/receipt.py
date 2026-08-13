"""
Step 2 — Read. Getting numbers off a receipt, and knowing which ones to doubt.

Every field carries three things, never one: the value, a confidence, and where
on the page it came from. A bare value is unusable here, because the whole
product downstream is a verdict, and a verdict built on a number nobody can
trace is exactly the thing this is meant to replace.

The confidence is not a model's self-report. It is how the field was found:

    LABELLED   a line said "TOTAL" and a number followed it     1.00
    INFERRED   the largest amount in the last few lines         0.55
    GUESSED    anything else                                    0.20

`THRESHOLD` is what separates a value that may be used from one that must be
shown to a person as evidence -- the line of text it was read from, since
nothing in this project handles images and there is no crop to show. Set at
0.6, above INFERRED on purpose: a receipt whose total had to be inferred from
position is a receipt worth ten seconds of somebody's attention, and the
alternative is a silent wrong number in a ledger that claims to be checked.

The text this reads comes from `crossfoot.read.document`, which uses Docling
where it is installed. Nothing in this module knows or cares which reader
produced the text -- that seam is the point, since layout parsing is a solved
problem with sixty thousand stars behind it and reconciliation is not.
"""
import re

from crossfoot.verdict import cents

LABELLED = 1.0
INFERRED = 0.55
GUESSED = 0.2

#: Below this, a value is evidence for a human rather than an input to a check.
THRESHOLD = 0.6

#: Label -> field. Ordered longest-first at match time so that "SUB TOTAL" is
#: never read as "TOTAL", which would put the subtotal in the total and make a
#: receipt reconcile against itself by accident.
_LABELS = {
    "subtotal": ("subtotal", "sub total", "sub-total", "net total", "goods total",
                 "merchandise", "items total"),
    # The corpus found "tva" missing, so a French receipt's tax line was
    # invisible and its arithmetic could not be checked at all. Sales tax has a
    # different name in every country and there is no way to derive the list --
    # it grows when a receipt shows up that this could not read.
    "tax": ("tax", "sales tax", "vat", "gst", "hst", "pst", "qst",
            "iva", "tva", "mwst", "ust", "btw", "moms", "alv", "iva incl"),
    "tip": ("tip", "gratuity", "service charge", "service"),
    "discount": ("discount", "coupon", "savings", "promotion", "you saved"),
    # "delivery" was here and had to go. On a furniture receipt it is a line
    # item that belongs inside the subtotal, and reading it as a fee removed it
    # from the column being summed *and* added it to the total being built --
    # two errors from one word, and a receipt that failed for a reason having
    # nothing to do with the merchant.
    "fees": ("fee", "fees", "surcharge", "service fee", "booking fee"),
    "total": ("total", "amount due", "balance due", "grand total", "total due",
              "amount paid", "total sale", "to pay"),
}

#: A number that looks like money: optional currency mark, digits, two decimals.
_AMOUNT = re.compile(r"(?<![\d.])(-?\d{1,3}(?:[,\s]\d{3})*|-?\d+)[.,](\d{2})(?![\d])")

_CURRENCY = re.compile(r"[$£€¥₹]|\b(usd|eur|gbp|jpy|thb|sgd|aud|cad)\b", re.I)


class Field:
    """A value, how sure we are, and where it came from."""

    __slots__ = ("value", "confidence", "line_number", "line", "how", "box")

    def __init__(self, value, confidence, line_number=None, line="", how="",
                 box=None):
        self.value = value
        self.confidence = confidence
        self.line_number = line_number
        self.line = line
        self.how = how
        #: (left, top, right, bottom) on the original image, when the text came
        #: from a photograph. None for a PDF or a text file, where there is no
        #: page to point at. This is what lets the queue show somebody the ink a
        #: doubtful total was read from instead of asking them to trust it.
        self.box = box

    @property
    def trusted(self) -> bool:
        return self.confidence >= THRESHOLD

    def __repr__(self):
        return (f"<Field {self.value} conf={self.confidence:.2f} "
                f"line={self.line_number} {self.how}>")


def _amounts_in(line: str):
    """Every money-shaped number on a line, as cents, left to right."""
    out = []
    for match in _AMOUNT.finditer(line):
        whole = match.group(1).replace(",", "").replace(" ", "")
        out.append(cents(f"{whole}.{match.group(2)}"))
    return [a for a in out if a is not None]


def _label_on(line: str):
    """
    Which field this line is labelled as, or None.

    Longest label first, so "SUB TOTAL" cannot be matched as "TOTAL". Getting
    that wrong writes the subtotal into the total, and a receipt whose total is
    its subtotal passes `subtotal_builds_total` whenever tax is zero -- a wrong
    reading that produces a clean verdict, which is the worst kind.
    """
    lowered = re.sub(r"[^a-z ]", " ", line.lower())
    best = None
    for field, labels in _LABELS.items():
        for label in labels:
            if re.search(rf"(?<![a-z]){re.escape(label)}(?![a-z])", lowered):
                if best is None or len(label) > best[1]:
                    best = (field, len(label))
    return best[0] if best else None


def _boxes_by_line(ocr_lines):
    """
    Line index -> the rectangle that line occupies, from an OCR reading.

    The bounding box of the whole line rather than of the number, deliberately.
    A box drawn round "17.31" is a crop of four digits with no context; a box
    round "TOTAL      17.31" is a picture a person can actually check.
    """
    boxes = {}
    for index, line in enumerate(ocr_lines or []):
        words = line.get("words") or []
        if not words:
            continue
        boxes[index] = (min(w.left for w in words), min(w.top for w in words),
                        max(w.left + w.width for w in words),
                        max(w.top + w.height for w in words))
    return boxes


def extract(text: str, ocr_lines=None) -> dict:
    """
    A receipt's fields, each with its confidence and the line it came from.

    Line items are only collected between the first item-looking line and the
    subtotal, so a phone number, a loyalty balance or the change due never
    enters the column that is about to be summed.

    `ocr_lines` is what `read.ocr` produced, when the text came off a
    photograph. Passing it attaches a rectangle to every field, which is the
    difference between telling somebody a total is doubtful and showing them
    the paper it was read from.
    """
    lines = [l.rstrip() for l in (text or "").splitlines()]
    boxes = _boxes_by_line(ocr_lines)
    fields = {}
    subtotal_at = None

    for number, line in enumerate(lines):
        if not line.strip():
            continue
        label = _label_on(line)
        amounts = _amounts_in(line)
        if not label or not amounts:
            continue
        # The rightmost amount on a labelled line: receipts print
        # "TAX 8.25%    4.12", and the rate is not the money.
        value = amounts[-1]
        if label in fields and fields[label].confidence >= LABELLED:
            # A second "TOTAL" further down wins -- "TOTAL" then "TOTAL DUE"
            # then a card slip's own total is the order these print in, and the
            # last is the one that was charged.
            if label != "total":
                continue
        fields[label] = Field(value, LABELLED, number, line, "labelled",
                              box=boxes.get(number))
        if label == "subtotal":
            subtotal_at = number

    if "total" not in fields:
        fields["total"] = _infer_total(lines, boxes)

    return {
        "fields": fields,
        "lines": _line_items(lines, subtotal_at),
        "merchant": _merchant(lines),
        "currency": _currency(text),
        "text_lines": lines,
        "needs_human": sorted(name for name, f in fields.items()
                              if f.value is not None and not f.trusted),
    }


def _merchant(lines):
    """
    The name printed at the top, which is what the receipt says it is.

    Worth doing properly because the matcher tests this name against the bank's
    descriptor, and the fallback -- a filename -- is whatever the phone called
    the photo. "IMG_2043" matches nothing, so every receipt would land in the
    review queue; worse, an unrelated one could be accepted on amount alone.

    First non-empty line that prices nothing and labels nothing. Address lines
    follow the name, so only the first is taken.
    """
    for line in lines[:6]:
        stripped = line.strip()
        if not stripped or _amounts_in(line) or _label_on(line):
            continue
        # At least two letters. A row of hashes or asterisks is a scanning
        # artefact, not a shop, and returning it as the merchant name gives the
        # matcher a string that can only mislead it.
        if sum(c.isalpha() for c in stripped) < 2:
            continue
        return stripped
    return ""


def _infer_total(lines, boxes=None) -> Field:
    """
    No line said TOTAL. The largest amount in the last third is the usual
    answer and it is usually right, which is exactly why it is not trusted:
    "usually right" is the failure mode this whole project is about.
    """
    tail = list(enumerate(lines))[max(0, len(lines) * 2 // 3):]
    best = None
    for number, line in tail:
        for amount in _amounts_in(line):
            if best is None or amount > best[0]:
                best = (amount, number, line)
    if best is None:
        return Field(None, 0.0, how="no amount found anywhere")
    return Field(best[0], INFERRED, best[1], best[2],
                 "no TOTAL label; largest amount near the foot of the receipt",
                 box=(boxes or {}).get(best[1]))


def _line_items(lines, subtotal_at):
    """
    The priced rows above the subtotal.

    Bounded above by the first priced line and below by the subtotal. Without
    the lower bound the tax, the total, the change and the card's last four
    digits all join the column being summed, and the sum agrees with nothing.
    Without a subtotal there is no bound to trust, so nothing is collected --
    an empty list leaves check 1 unrun, which is the honest state.
    """
    if subtotal_at is None:
        return []
    items = []
    for number, line in enumerate(lines[:subtotal_at]):
        if _label_on(line):
            continue
        amounts = _amounts_in(line)
        if not amounts:
            continue
        description = _AMOUNT.sub("", line).strip(" .-\t")
        if not description:
            continue                       # a bare number is not an item
        items.append({"row": number, "description": description,
                      "amount": amounts[-1], "line": line})
    return items


def _currency(text: str):
    match = _CURRENCY.search(text or "")
    return match.group(0).upper() if match else None


def as_receipt(extracted: dict) -> dict:
    """
    The shape `crossfoot.verdict` checks, carrying only trusted values.

    A field below threshold is omitted rather than passed along, which turns
    into an *unchecked* verdict rather than a check run on a number nobody
    stands behind. The extraction is kept alongside so the review queue can
    show the line the doubt is about.
    """
    fields = extracted["fields"]
    receipt = {name: f.value for name, f in fields.items()
               if f.trusted and f.value is not None}
    receipt["lines"] = extracted["lines"]
    receipt["merchant"] = extracted.get("merchant") or ""
    receipt["currency"] = extracted.get("currency")
    receipt["_extraction"] = extracted
    return receipt
