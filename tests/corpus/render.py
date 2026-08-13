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
