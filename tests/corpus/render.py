"""
Turning the receipt corpus into images, including bad ones.

The corpus already carries hand-keyed truth for 22 receipts. Rendering them as
pictures gives the photograph path the same measurement the text path has: run
them through OCR, compare against what a person read off the paper, and count
the receipts that come out wrong *and reconcile anyway*.

The degradations matter more than the clean render. A crisp 300-dpi image of
typed text is not what anybody photographs; it is the easiest possible input,
and an accuracy figure from it would flatter the tool. Rotation, blur, noise
and washed-out contrast are the four things that actually happen when somebody
takes a picture of a till receipt on a kitchen table, and each is applied
separately so a failure says which one caused it.

Still not a photograph of crumpled thermal paper. Nothing here claims to be.
"""
import io
import os
import random

try:                                        # pragma: no cover - environment
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    HAVE_PILLOW = True
except ImportError:                         # pragma: no cover - environment
    Image = ImageDraw = ImageFilter = ImageFont = None
    HAVE_PILLOW = False

#: Monospaced, because a till prints monospaced and because a proportional
#: font would put the amounts in a ragged column that no real receipt has.
_FONT_CANDIDATES = ("consola.ttf", "DejaVuSansMono.ttf", "cour.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")

MARGIN = 40
LINE_HEIGHT = 34
FONT_SIZE = 24


def _font():
    for name in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, FONT_SIZE)
        except OSError:
            continue
    return ImageFont.load_default()         # pragma: no cover - unusual machine


def render(text: str, width: int = 560) -> "Image.Image":
    """A receipt as a clean black-on-white image, the easiest possible input."""
    lines = text.splitlines() or [""]
    height = MARGIN * 2 + LINE_HEIGHT * len(lines)
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    font = _font()
    for index, line in enumerate(lines):
        draw.text((MARGIN, MARGIN + index * LINE_HEIGHT), line, fill=0, font=font)
    return image


# --------------------------------------------------------------------------
# The four things that happen to a real photograph
# --------------------------------------------------------------------------

def rotated(image, degrees: float = 2.5):
    """A receipt on a table is never square to the camera."""
    return image.rotate(degrees, expand=True, fillcolor=255,
                        resample=Image.BICUBIC)


def blurred(image, radius: float = 1.2):
    """A phone that focused on the table instead of the paper."""
    return image.filter(ImageFilter.GaussianBlur(radius))


def noisy(image, amount: int = 40, seed: int = 20260813):
    """Sensor noise in a dim kitchen."""
    random.seed(seed)
    out = image.copy()
    pixels = out.load()
    for y in range(out.height):
        for x in range(0, out.width, 3):    # every third pixel; enough to bite
            value = pixels[x, y] + random.randint(-amount, amount)
            pixels[x, y] = max(0, min(255, value))
    return out


def faded(image, floor: int = 90):
    """
    Thermal paper that has been in a wallet, or a photograph into the light.

    Contrast is compressed towards mid-grey rather than the image being
    darkened, because that is what actually destroys thermal print.
    """
    return image.point(lambda v: floor + int(v * (255 - floor) / 255))


DEGRADATIONS = {
    "clean": lambda image: image,
    "rotated": rotated,
    "blurred": blurred,
    "noisy": noisy,
    "faded": faded,
}


def write(image, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    image.save(path, format="PNG")
    return path


def as_png_bytes(image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Closer to a photograph
# --------------------------------------------------------------------------
#
# Everything above is a scanner's idea of damage: uniform, in-plane, evenly
# applied. A phone photograph is none of those things, and the difference is
# not cosmetic -- perspective alone is what separates "a picture of a document"
# from "a document".

def _perspective_coefficients(source, target):
    """
    The eight coefficients Pillow's PERSPECTIVE transform wants.

    Solved rather than guessed. The first version of this used QUAD with
    hand-assembled corner data, which did not tilt the image, it scrambled it:
    the OCR output was punctuation soup and the ink fraction went *up*, which a
    geometric warp cannot do. It scored 1 of 22 and was measuring the test
    helper rather than the tool -- the precise failure this whole corpus exists
    to avoid, committed inside the corpus.

    Eight unknowns, eight equations, plain Gaussian elimination. No numpy: this
    project has no required dependencies and a test helper is not the place to
    acquire one.
    """
    matrix = []
    for (sx, sy), (tx, ty) in zip(source, target):
        matrix.append([tx, ty, 1, 0, 0, 0, -sx * tx, -sx * ty])
        matrix.append([0, 0, 0, tx, ty, 1, -sy * tx, -sy * ty])
    vector = [c for corner in source for c in corner]

    size = 8
    for column in range(size):
        pivot = max(range(column, size), key=lambda r: abs(matrix[r][column]))
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        vector[column], vector[pivot] = vector[pivot], vector[column]
        divisor = matrix[column][column]
        for row in range(size):
            if row == column:
                continue
            factor = matrix[row][column] / divisor
            for k in range(column, size):
                matrix[row][k] -= factor * matrix[column][k]
            vector[row] -= factor * vector[column]
    return [vector[i] / matrix[i][i] for i in range(size)]


def perspective(image, tilt: float = 0.08):
    """
    Photographed at an angle, which every hand-held photograph is.

    The top edge is narrowed relative to the bottom, so the text is trapezoidal
    rather than merely rotated. Tesseract deskews a rotation and cannot deskew
    this, which is why it is the degradation most likely to find something --
    and why it was worth getting right rather than approximately.
    """
    width, height = image.size
    inset = width * tilt
    source = [(0, 0), (width, 0), (width, height), (0, height)]
    target = [(inset, 0), (width - inset, 0), (width, height), (0, height)]
    return image.transform(
        (width, height), Image.PERSPECTIVE,
        _perspective_coefficients(source, target),
        resample=Image.BICUBIC, fillcolor=255)


def lit_unevenly(image, strength: float = 0.45):
    """
    One side brighter than the other, which is what a kitchen light does.

    Applied as a horizontal ramp multiplied into the image, so the dark side
    loses contrast rather than the whole picture dimming. A global threshold
    then cannot serve both halves, which is the actual problem uneven lighting
    causes for OCR.
    """
    width, height = image.size
    ramp = Image.linear_gradient("L").resize((width, height))
    ramp = ramp.point(lambda v: int(255 - strength * v))
    return Image.composite(image, Image.new("L", image.size, 255),
                           ramp).point(
        lambda v: min(255, int(v * 1.0)))


def compressed(image, quality: int = 30):
    """JPEG, because every photograph from a phone has been through it."""
    buffer = io.BytesIO()
    image.convert("L").save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert("L")


def small(image, factor: float = 0.45):
    """
    A phone at arm's length: fewer pixels per character than a scan.

    Downscaled and left there rather than scaled back up, because the thing
    being tested is whether the engine can work at that density.
    """
    return image.resize((int(image.width * factor), int(image.height * factor)),
                        Image.LANCZOS)


def creased(image, position: float = 0.55):
    """A fold across the middle: a dark line, and the print either side of it."""
    out = image.copy()
    draw = ImageDraw.Draw(out)
    y = int(out.height * position)
    for offset, shade in ((-1, 200), (0, 120), (1, 200)):
        draw.line([(0, y + offset), (out.width, y + offset)], fill=shade)
    return out


def photographed(image):
    """
    All of it at once, in the order a camera applies them.

    The realistic case. Each of the others isolates one thing so a failure says
    which; this one says whether the whole path survives a photograph, and it
    is the number to quote.
    """
    return compressed(small(lit_unevenly(perspective(blurred(image, 0.8)))), 35)


DEGRADATIONS.update({
    "perspective": perspective,
    "lit_unevenly": lit_unevenly,
    "compressed": compressed,
    "small": small,
    "creased": creased,
    "photographed": photographed,
})
