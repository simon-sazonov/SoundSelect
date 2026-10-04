"""Makes the test PDFs in this folder from the sample sheets (needs WeasyPrint and its fonts).

    uv run python backend/tests/data/pdf/make.py

found_a_love_mono.pdf    the sample sheet in a typewriter font, as printed from a chord site
found_a_love_word.pdf    the same in a proportional font, each chord line typed with spaces
                         to sit over its syllables, as in a word processor
two_columns.pdf          the sheet printed in two columns, with the title across both
russian_two_pages.pdf    the Russian sample over two pages, with a web address and page
                         numbers in the margins
scanned.pdf              a page that is only a picture of a sheet
"""

from __future__ import annotations

import base64
import html
import io
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from weasyprint import HTML

HERE = Path(__file__).parent
DATA = HERE.parent


def page(body: str, css: str = "") -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
    @page {{ size: A4; margin: 20mm 18mm; }}
    body {{ margin: 0; }}
    {css}
    </style></head><body>{body}</body></html>"""


def write(name: str, text: str) -> None:
    HTML(string=text).write_pdf(HERE / name)
    print("wrote", name)


CHORD = re.compile(r"[A-H][#b]?[a-z0-9#b]*(?:/[A-H][#b]?)?")


def is_chord_line(line: str) -> bool:
    words = line.split()
    return bool(words) and all(CHORD.fullmatch(w) for w in words)


FONTS = Path("/usr/share/fonts/truetype/liberation")
SERIF = ImageFont.truetype(FONTS / "LiberationSerif-Regular.ttf", 130)
SERIF_BOLD = ImageFont.truetype(FONTS / "LiberationSerif-Bold.ttf", 130)


def typed_chord_line(chords: list[tuple[int, str]], lyric: str) -> str:
    """A chord line typed with spaces, the way a writer lines chords up by eye in a word
    processor: before each chord, as many spaces as bring it closest to its syllable."""
    line = ""
    for col, chord in chords:
        target = SERIF.getlength(lyric[:col]) + 0.5 * SERIF.getlength(" ")
        spaces = 1 if line else 0
        while SERIF_BOLD.getlength(line + " " * (spaces + 1)) <= target:
            spaces += 1
        line += " " * spaces + chord
    return line


def word_lines(text: str) -> str:
    """The sheet in a proportional font; chord lines typed with spaces over their lyrics."""
    lines = text.split("\n")
    out = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if is_chord_line(line) and nxt.strip() and not is_chord_line(nxt):
            chords = [(m.start(), m.group(0)) for m in re.finditer(r"\S+", line)]
            line = typed_chord_line(chords, nxt.ljust(max(c for c, _ in chords)))
            out.append(f'<div class="chords">{html.escape(line)}</div>')
            continue
        out.append(f'<div class="plain">{html.escape(line) or "&nbsp;"}</div>')
    return "\n".join(out)


WORD_CSS = """
body { font-family: "Liberation Serif"; font-size: 13pt; }
.plain, .chords { white-space: pre; line-height: 1.25; }
.chords { font-weight: bold; }
"""


def main() -> None:
    love = (DATA / "found_a_love.txt").read_text(encoding="utf-8")
    russian = (DATA / "russian_h.txt").read_text(encoding="utf-8")

    write(
        "found_a_love_mono.pdf",
        page(
            f"<pre>{html.escape(love)}</pre>",
            'pre { font-family: "Liberation Mono"; font-size: 11pt; line-height: 1.2; }',
        ),
    )
    write("found_a_love_word.pdf", page(word_lines(love), WORD_CSS))

    head, rest = love.split("[Chorus]")
    title, verse = head.split("\n", 1)
    write(
        "two_columns.pdf",
        page(
            f'<h1>{html.escape(title)}</h1><div class="cols"><pre>{html.escape(verse)}</pre>'
            f"<pre>[Chorus]{html.escape(rest)}</pre></div>",
            'h1 { font: bold 14pt "Liberation Sans"; margin: 0 0 12pt; }'
            ".cols { display: flex; gap: 40pt; }"
            'pre { font-family: "Liberation Mono"; font-size: 8.5pt; line-height: 1.2; '
            "margin: 0; }",
        ),
    )

    first, second = russian.split("Припев:")
    write(
        "russian_two_pages.pdf",
        page(
            word_lines(first)
            + '<div style="break-before: page"></div>'
            + word_lines("Припев:" + second),
            WORD_CSS
            + '@page { @top-left { content: "https://amdm.ru/akkordi/test/pesnya_pro_leto/"; '
            'font: 8pt "Liberation Sans"; } @bottom-center { content: "Страница " counter(page) '
            '" из " counter(pages); font: 8pt "Liberation Sans"; } }',
        ),
    )

    font = ImageFont.truetype(FONTS / "LiberationMono-Regular.ttf", 28)
    image = Image.new("L", (1200, 900), 255)
    draw = ImageDraw.Draw(image)
    for n, line in enumerate(love.split("\n")):
        draw.text((40, 40 + 36 * n), line, fill=0, font=font)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    data = base64.b64encode(buffer.getvalue()).decode()
    write("scanned.pdf", page(f'<img src="data:image/png;base64,{data}" style="width: 100%">'))


if __name__ == "__main__":
    main()
