"""
Render the README's demo from the real command output.

A screenshot is a claim about what a program does, and a screenshot taken by
hand is a claim nobody can re-check. This runs the actual commands, captures
what they actually print, and draws that — so regenerating it is the way to
find out that the demo has drifted.

    python docs/render_demo.py

SVG rather than PNG because it is a few kilobytes, stays sharp, survives a diff
in a way a binary does not, and renders on GitHub.
"""
import html
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SAMPLE = os.path.join(ROOT, "examples", "statement.csv")

#: A terminal that reads as one on either a light or a dark GitHub theme.
#: Fixed colours rather than theme-aware ones: an image cannot query the
#: reader's theme, and a dark panel is legible against both page grounds.
BACKGROUND = "#12151c"
CHROME = "#1b1f29"
TEXT = "#d6dae4"
DIM = "#7d8798"
GREEN = "#7fd18d"
AMBER = "#e6b566"
RED = "#e2807f"
BLUE = "#7fb2e6"

LINE = 19
SIZE = 13
PAD = 18


def run(arguments, text=None):
    """One command, its output, in a temporary copy of the sample if needed."""
    path = SAMPLE
    scratch = None
    if text is not None:
        scratch = os.path.join(HERE, "_demo_tmp.csv")
        with open(scratch, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        path = scratch
    try:
        done = subprocess.run(
            [sys.executable, "-m", "crossfoot.cli", "audit", path, *arguments],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        out = (done.stdout or "") + (done.stderr or "")
        # The temporary name would leak into the picture and date it.
        return out.replace(os.path.basename(path), "statement.csv").rstrip("\n")
    finally:
        if scratch and os.path.exists(scratch):
            os.remove(scratch)


#: Columns before a line is wrapped. GitHub renders a README image at roughly
#: 900 css pixels, so a picture wider than about this many monospace characters
#: is shrunk until the text is unreadable — which is the failure mode of every
#: terminal screenshot ever put in a README. The longest real line here is 193
#: characters and would have been clipped off the canvas entirely.
COLUMNS = 92


def wrapped(lines):
    """Long lines folded, keeping their indentation so columns still line up."""
    out = []
    for line in lines:
        if len(line) <= COLUMNS:
            out.append(line)
            continue
        indent = " " * (len(line) - len(line.lstrip()) + 2)
        rest = line
        while len(rest) > COLUMNS:
            cut = rest.rfind(" ", 0, COLUMNS)
            if cut <= len(indent):
                cut = COLUMNS
            out.append(rest[:cut].rstrip())
            rest = indent + rest[cut:].lstrip()
        if rest.strip():
            out.append(rest)
    return out


def colour_of(line):
    stripped = line.strip()
    if stripped.startswith("PAID TWICE") or "PAID TWICE" in line:
        return RED
    if "PRICE ROSE" in line or "NEW RECURRING" in line:
        return AMBER
    if stripped.startswith("$") or "at stake" in line or "a year," in line:
        return TEXT
    if "incomplete" in line or "not complete" in line:
        return AMBER
    if line.endswith("whole"):
        return GREEN
    if stripped.startswith("Nothing else is reported") or stripped.startswith("a statement"):
        return DIM
    return TEXT


def panel(out, title, body, top, width):
    height = PAD * 2 + LINE * (len(body) + 1) + 10
    out.write(f'<g transform="translate(0,{top})">')
    out.write(f'<rect width="{width}" height="{height}" rx="8" fill="{BACKGROUND}"/>')
    out.write(f'<rect width="{width}" height="30" rx="8" fill="{CHROME}"/>')
    out.write(f'<rect y="22" width="{width}" height="8" fill="{CHROME}"/>')
    for index, colour in enumerate(("#e2807f", "#e6b566", "#7fd18d")):
        out.write(f'<circle cx="{18 + index * 15}" cy="15" r="5" fill="{colour}"/>')
    out.write(f'<text x="{width / 2}" y="19" fill="{DIM}" font-size="11" '
              f'text-anchor="middle" font-family="ui-monospace,monospace">'
              f'{html.escape(title)}</text>')

    y = 30 + PAD + SIZE
    out.write(f'<text x="{PAD}" y="{y}" font-size="{SIZE}" '
              f'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace">'
              f'<tspan fill="{GREEN}">$</tspan>'
              f'<tspan fill="{BLUE}"> crossfoot audit </tspan>'
              f'<tspan fill="{TEXT}">statement.csv</tspan></text>')
    for line in body:
        y += LINE
        out.write(f'<text x="{PAD}" y="{y}" fill="{colour_of(line)}" '
                  f'font-size="{SIZE}" xml:space="preserve" '
                  f'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace">'
                  f'{html.escape(line)}</text>')
    out.write("</g>")
    return height


def main():
    clean = wrapped(run([]).splitlines())

    with open(SAMPLE, encoding="utf-8") as handle:
        rows = handle.read().splitlines()
    columns = rows[8].split(",")
    columns[-1] = f"{float(columns[-1]) + 100:.2f}"      # one balance, off by 100
    rows[8] = ",".join(columns)
    broken = wrapped(run([], text="\n".join(rows) + "\n").splitlines())

    width = 7.85 * max(len(l) for l in clean + broken) + PAD * 2 + 10

    body = io.StringIO()
    first = panel(body, "what is wrong with this statement", clean, 0, width)
    gap = 26
    caption = first + gap
    body_text = body.getvalue()

    note = ("now change one balance by 100 — the whole report goes silent, "
            "because a duplicate found in a statement with rows missing is an "
            "artefact of the gap")
    lines = []
    while note:
        cut = note[:96].rfind(" ") if len(note) > 96 else len(note)
        lines.append(note[:cut].strip())
        note = note[cut:].strip()

    second = io.StringIO()
    height_two = panel(second, "the same statement, one balance changed", broken,
                       0, width)

    total = first + gap + LINE * len(lines) + gap + height_two
    with open(os.path.join(HERE, "demo.svg"), "w", encoding="utf-8") as handle:
        handle.write(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
            f'height="{total:.0f}" viewBox="0 0 {width:.0f} {total:.0f}" '
            f'role="img" aria-label="Crossfoot audits a bank statement, then '
            f'refuses to report anything once one balance is altered">')
        handle.write(f'<title>crossfoot audit</title>')
        handle.write(body_text)
        y = caption
        for line in lines:
            y += LINE
            handle.write(f'<text x="{PAD}" y="{y}" fill="{DIM}" font-size="12" '
                         f'font-family="ui-monospace,monospace">'
                         f'{html.escape(line)}</text>')
        handle.write(f'<g transform="translate(0,{y + gap - LINE + 8})">'
                     + second.getvalue() + "</g>")
        handle.write("</svg>")
    print(f"docs/demo.svg  {width:.0f}x{total:.0f}")


if __name__ == "__main__":
    main()
