"""Getting a photo ready to read: turned upright, the page cut out and flattened, straightened
and sized.

Every step depends only on the file's bytes, so preparing the same photo twice gives the same
picture. That matters because the song page shows the prepared picture with a box around each
line that was read, and the picture is made again when it's first shown, long after reading.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np

MAX_SIDE = 2000  # longest side of the prepared picture, in pixels
MIN_SIDE = 1400  # smaller pictures (screenshots) are enlarged to this, so small letters read
MAX_TILT = 6.0  # degrees: a photo tilted more than this is left as it is
TILT_STEP = 0.2


class UnreadableImage(ValueError):
    """The file is not a picture that can be opened."""


@dataclass
class Prepared:
    """A picture ready to read, in blue-green-red order as OpenCV keeps it."""

    image: np.ndarray
    steps: list[str] = field(default_factory=list)  # what was done, for tests and notes

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])

    def png(self) -> bytes:
        import cv2

        ok, buffer = cv2.imencode(".png", self.image, [cv2.IMWRITE_PNG_COMPRESSION, 6])
        if not ok:
            raise UnreadableImage("the picture could not be saved as PNG")
        return buffer.tobytes()

    def jpeg(self, quality: int = 88) -> bytes:
        import cv2

        ok, buffer = cv2.imencode(".jpg", self.image, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            raise UnreadableImage("the picture could not be saved as JPEG")
        return buffer.tobytes()


def _register_heif() -> bool:
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        return False
    register_heif_opener()
    return True


def decode(data: bytes) -> np.ndarray:
    """The picture upright (as the phone's orientation tag says), in BGR order."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    heif = _register_heif()
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                white = Image.new("RGBA", im.size, (255, 255, 255, 255))
                im = Image.alpha_composite(white, im)
            rgb = np.asarray(im.convert("RGB"))
    except UnidentifiedImageError as exc:
        if data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc") and not heif:
            raise UnreadableImage(
                "This is an iPhone HEIC photo, and the part that opens those (pillow-heif) "
                "isn't installed."
            ) from exc
        raise UnreadableImage("This file isn't a picture that can be opened.") from exc
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise UnreadableImage("This picture is damaged or too big to open.") from exc
    return np.ascontiguousarray(rgb[:, :, ::-1])


def _gray(image: np.ndarray) -> np.ndarray:
    import cv2

    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image


def _order(quad: np.ndarray) -> np.ndarray:
    """Corners in the order top left, top right, bottom right, bottom left."""
    s = quad.sum(axis=1)
    d = np.diff(quad, axis=1).ravel()
    return np.array(
        [quad[np.argmin(s)], quad[np.argmin(d)], quad[np.argmax(s)], quad[np.argmax(d)]],
        dtype=np.float32,
    )


def find_page(image: np.ndarray) -> np.ndarray | None:
    """The four corners of a sheet of paper photographed on a darker background, or None.

    Only a clear case counts: a four-cornered shape covering 30 to 97 percent of the photo,
    clearly lighter than what is around it. A screenshot or a photo filled by the page has
    no such edge, and is left as it is.
    """
    import cv2

    gray = _gray(image)
    h, w = gray.shape
    scale = 600 / max(h, w)
    small = cv2.resize(gray, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    blur = cv2.GaussianBlur(small, (5, 5), 0)
    edges = cv2.Canny(blur, 40, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area = small.shape[0] * small.shape[1]
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        hull = cv2.convexHull(contour)
        quad = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True)
        if len(quad) != 4 or not 0.3 * area < cv2.contourArea(quad) < 0.97 * area:
            continue
        mask = np.zeros_like(small)
        cv2.fillConvexPoly(mask, quad.reshape(4, 2), 255)
        inside = float(small[mask > 0].mean())
        outside_px = small[mask == 0]
        if outside_px.size < 0.02 * area or inside - float(outside_px.mean()) < 25:
            continue
        return _order(quad.reshape(4, 2).astype(np.float32) / scale)
    return None


def flatten(image: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """The page inside the four corners, cut out and seen straight from above."""
    import cv2

    tl, tr, br, bl = quad
    width = round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    target = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], np.float32
    )
    matrix = cv2.getPerspectiveTransform(quad, target)
    return cv2.warpPerspective(image, matrix, (width, height), flags=cv2.INTER_CUBIC)


def resize(image: np.ndarray) -> np.ndarray:
    """Shrink a big photo to ``MAX_SIDE``, enlarge a small screenshot to ``MIN_SIDE``."""
    import cv2

    h, w = image.shape[:2]
    longest = max(h, w)
    if longest > MAX_SIDE:
        scale = MAX_SIDE / longest
        interpolation = cv2.INTER_AREA
    elif longest < MIN_SIDE:
        scale = MIN_SIDE / longest
        interpolation = cv2.INTER_CUBIC
    else:
        return image
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    return cv2.resize(image, size, interpolation=interpolation)


def _ink(gray: np.ndarray) -> np.ndarray:
    """Dark marks (letters) as 1, paper as 0, at a small size for measuring the tilt."""
    import cv2

    h, w = gray.shape
    scale = 800 / max(h, w)
    small = cv2.resize(gray, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    ink = cv2.adaptiveThreshold(small, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 15)
    return ink.astype(np.float32)


def tilt(image: np.ndarray) -> float:
    """The turn, in degrees counterclockwise, that makes the lines of text level: the angle at
    which the rows of ink are most sharply separated."""
    import cv2

    ink = _ink(_gray(image))
    if ink.sum() < 50:
        return 0.0
    h, w = ink.shape
    centre = (w / 2, h / 2)

    def sharpness(angle: float) -> float:
        matrix = cv2.getRotationMatrix2D(centre, angle, 1.0)
        rotated = cv2.warpAffine(ink, matrix, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
        return float(np.var(rotated.sum(axis=1)))

    angles = np.arange(-MAX_TILT, MAX_TILT + TILT_STEP / 2, TILT_STEP)
    scores = [sharpness(a) for a in angles]
    best = int(np.argmax(scores))
    flat = sharpness(0.0)
    if best in (0, len(angles) - 1) or scores[best] < 1.02 * flat:
        return 0.0  # no clear slope, or more than the limit: leave it
    return float(round(angles[best], 2))


def straighten(image: np.ndarray, angle: float) -> np.ndarray:
    """Turn the picture by ``angle`` degrees, filling the corners with white."""
    import cv2

    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_w, new_h = round(h * sin + w * cos), round(h * cos + w * sin)
    matrix[0, 2] += new_w / 2 - w / 2
    matrix[1, 2] += new_h / 2 - h / 2
    border = (255, 255, 255) if image.ndim == 3 else 255
    return cv2.warpAffine(image, matrix, (new_w, new_h), flags=cv2.INTER_CUBIC, borderValue=border)


def prepare(data: bytes) -> Prepared:
    """A photo or screenshot made ready to read; the same bytes always give the same picture."""
    image = decode(data)
    steps: list[str] = []
    quad = find_page(image)
    if quad is not None:
        image = flatten(image, quad)
        steps.append("page")
    image = resize(image)
    angle = tilt(image)
    if abs(angle) >= 0.3:
        image = straighten(image, angle)
        steps.append(f"tilt {angle:+.1f}")
    return Prepared(image, steps)


def from_array(image: np.ndarray) -> Prepared:
    """An image already drawn at a known size (a page of a scanned PDF): nothing moved."""
    return Prepared(np.ascontiguousarray(image), [])
