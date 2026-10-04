"""Makes the test pictures from the sample sheets. Run from the repository root:

    uv run python backend/tests/data/photos/make.py

screenshot.png        found_a_love.txt drawn in a proportional font, chords over their syllables
photo.jpg             the same page photographed: on a dark table, at an angle, tilted, soft
page1.png, page2.png  the sheet cut in two, for a song that runs over two pictures
russian.png           russian_h.txt drawn the same way (Cyrillic lyrics, H chords)
russian_photo.jpg     russian.png photographed

The pictures are kept in the repository, so the fonts are needed only to make them again.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
DATA = HERE.parent
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _is_chords(line: str) -> bool:
    words = line.split()
    return bool(words) and all(w[0] in "ABCDEFGH" and len(w) <= 6 for w in words)


def draw_sheet(lines: list[str], width: int = 1100, size: int = 26) -> Image.Image:
    """The sheet on white paper. A chord line's chords go over the letters of the lyric line
    under it, as a word processor user lines them up by eye."""
    font = ImageFont.truetype(FONT, size)
    bold = ImageFont.truetype(BOLD, size)
    step = round(size * 1.55)
    image = Image.new("RGB", (width, 80 + step * len(lines)), "white")
    draw = ImageDraw.Draw(image)
    left = 60
    for i, line in enumerate(lines):
        y = 40 + i * step
        if _is_chords(line):
            below = lines[i + 1] if i + 1 < len(lines) else ""
            for word_start, word in _words(line):
                prefix = below[:word_start]
                x = left + draw.textlength(prefix, font=font)
                if word_start > len(below):
                    x = (
                        left
                        + draw.textlength(below, font=font)
                        + (word_start - len(below)) * draw.textlength(" ", font=font) * 1.0
                    )
                draw.text((x, y), word, font=bold, fill=(20, 20, 20))
        else:
            draw.text((left, y), line, font=font, fill=(0, 0, 0))
    return image


def _words(line: str) -> list[tuple[int, str]]:
    out = []
    i = 0
    for word in line.split(" "):
        if word:
            out.append((i, word))
        i += len(word) + 1
    return out


def photograph(page: Image.Image, seed: int = 1) -> np.ndarray:
    """The page as a phone photo: on a dark table, seen at an angle, a little tilted and soft,
    with uneven light and some grain."""
    rng = np.random.default_rng(seed)
    paper = cv2.cvtColor(np.asarray(page), cv2.COLOR_RGB2BGR)
    h, w = paper.shape[:2]
    out_w, out_h = round(w * 1.5), round(h * 1.45)
    table = np.full((out_h, out_w, 3), (45, 52, 60), np.uint8)
    table = cv2.add(table, rng.integers(0, 18, table.shape, dtype=np.uint8))
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    ox, oy = out_w * 0.16, out_h * 0.14
    dst = np.float32(
        [
            [ox + w * 0.04, oy],
            [ox + w * 1.02, oy + h * 0.035],
            [ox + w * 0.98, oy + h * 1.0],
            [ox - w * 0.01, oy + h * 0.97],
        ]
    )
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(paper, matrix, (out_w, out_h), borderValue=(0, 0, 0))
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), matrix, (out_w, out_h))
    photo = np.where(mask[:, :, None] > 0, warped, table)
    light = (
        np.linspace(1.0, 0.82, out_w)[None, :, None] * np.linspace(1.0, 0.9, out_h)[:, None, None]
    )
    photo = np.clip(photo * light, 0, 255).astype(np.uint8)
    photo = cv2.GaussianBlur(photo, (3, 3), 0.9)
    noise = rng.normal(0, 5, photo.shape)
    return np.clip(photo + noise, 0, 255).astype(np.uint8)


def save_jpeg(path: Path, image: np.ndarray, quality: int = 72) -> None:
    cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, quality])


def main() -> None:
    sheet = (DATA / "found_a_love.txt").read_text(encoding="utf-8").splitlines()
    page = draw_sheet(sheet)
    page.save(HERE / "screenshot.png", optimize=True)
    save_jpeg(HERE / "photo.jpg", photograph(page))
    cut = sheet.index("[Chorus]")
    draw_sheet(sheet[:cut]).save(HERE / "page1.png", optimize=True)
    draw_sheet(sheet[cut:]).save(HERE / "page2.png", optimize=True)
    russian = (DATA / "russian_h.txt").read_text(encoding="utf-8").splitlines()
    russian_page = draw_sheet(russian)
    russian_page.save(HERE / "russian.png", optimize=True)
    save_jpeg(HERE / "russian_photo.jpg", photograph(russian_page, seed=2))


if __name__ == "__main__":
    main()
