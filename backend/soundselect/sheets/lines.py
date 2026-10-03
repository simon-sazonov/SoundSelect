"""Sorting a sheet's lines.

Each line is marked as header (title and artist), meta (capo, tuning, key, tempo), section
label ([Verse], Припев:), chord line, lyric line, guitar tab or chord diagram. Chords written
inside the lyrics, ChordPro style ([Am]words), are found here too, with their positions.
"""

from __future__ import annotations

import re

from ..core.chords import parse_chord
from ..core.song import SectionKind
from .model import SheetMeta, SheetText, SortedLine, SortedSheet, Token, TokenKind

VERSION = "1"

_SECTION_WORDS: list[tuple[str, SectionKind]] = [
    (r"pre[\s-]?chorus|предприпев|пред[\s-]?припев", "pre_chorus"),
    (r"intro(?:duction)?|вступление|вступ|интро", "intro"),
    (r"verse|куплет", "verse"),
    (r"chorus|refrain|hook|припев|рефрен", "chorus"),
    (r"bridge|middle\s*8|бридж|мост", "bridge"),
    (r"(?:guitar\s+|sax\s+|piano\s+|keys\s+)?solo|соло", "solo"),
    (r"instrumental|инструментал", "instrumental"),
    (r"interlude|break|проигрыш|перебивка", "interlude"),
    (r"outro|ending|аутро|концовка|окончание|финал", "outro"),
    (r"coda|кода", "coda"),
    (r"tag|riff|рифф|post[\s-]?chorus", "other"),
]
_SECTION_RE = re.compile(r"(?:" + "|".join(w for w, _ in _SECTION_WORDS) + r")", re.IGNORECASE)
_REPEAT = r"(?:[xх×]\s*(\d+)|(\d+)\s*(?:[xх×]|раза?|times))"
_REPEAT_RE = re.compile(r"^\(?\s*" + _REPEAT + r"\s*\)?$", re.IGNORECASE)
_REPEAT_TAIL_RE = re.compile(r"\s*\(?\s*" + _REPEAT + r"\s*\)?\s*$", re.IGNORECASE)
_NC_RE = re.compile(r"^\(?(?:N\.?\s?C\.?|Н\.?\s?С\.?|no\s+chord)\)?$", re.IGNORECASE)
_BAR_RE = re.compile(r"^[|:/\\%.\-–—~>]+$")
_DIAGRAM_RE = re.compile(r"^\[?(?:[x0-9]{6}|(?:[x0-9]{1,2}-){5}[x0-9]{1,2})\]?$", re.IGNORECASE)
_TAB_RE = re.compile(r"^\s*[A-Ha-h]?[#b]?\s*[|:]?[-\d|hpbrxsv/\\~*().=\s]+$")
_BRACKET_LABEL_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(.*)$")
_PAREN_LABEL_RE = re.compile(r"^\s*\(([^)]+)\)\s*:?\s*$")
_CHORDPRO_RE = re.compile(r"\[([^\]]*)\]")
_DIRECTIVE_RE = re.compile(r"^\s*\{\s*([a-z_]+)\s*(?::\s*(.*?))?\s*\}\s*$", re.IGNORECASE)
_UG_TAGS_RE = re.compile(r"\[/?(?:ch|tab)\]", re.IGNORECASE)
_ROMAN = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
    "xi": 11,
    "xii": 12,
}

_META_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("capo", re.compile(r"^\s*(?:capo|каподастр|капо)\b\.?\s*[:=-]?\s*(.*)$", re.I)),
    ("tuning", re.compile(r"^\s*(?:tuning|строй|настройка)\b\s*[:=-]?\s*(.*)$", re.I)),
    ("key", re.compile(r"^\s*(?:key|тональность|тон)\b\s*[:=-]?\s*(.+)$", re.I)),
    ("tempo", re.compile(r"^\s*(?:tempo|bpm|темп)\b\s*[:=-]?\s*(\d+(?:\.\d+)?)", re.I)),
    (
        "time",
        re.compile(r"^\s*(?:time(?:\s+signature)?|размер)\b\s*[:=-]?\s*(\d+\s*/\s*\d+)", re.I),
    ),
    ("title", re.compile(r"^\s*(?:title|song|название|песня)\s*[:=-]\s*(.+)$", re.I)),
    (
        "artist",
        re.compile(r"^\s*(?:artist|band|by|исполнитель|группа|артист)\s*[:=-]\s*(.+)$", re.I),
    ),
    (
        "other",
        re.compile(
            r"^\s*(?:author|words|music|lyrics|composer|difficulty|strumming|tabbed\s+by|"
            r"слова|музыка|автор|аккорды|бой|перебор|сложность)\b.*[:=-]",
            re.I,
        ),
    ),
]
_TITLE_NOISE_RE = re.compile(
    r"\s*[\(\[]?\b(?:chords?|tabs?|ukulele|guitar|аккорды|табы|разбор)\b[\)\]]?\s*$", re.IGNORECASE
)


def section_kind(label: str) -> SectionKind | None:
    for pattern, kind in _SECTION_WORDS:
        if re.search(pattern, label, re.IGNORECASE):
            return kind
    return None


def repeat_count(text: str) -> int | None:
    m = _REPEAT_RE.match(text.strip())
    if not m:
        return None
    return int(m.group(1) or m.group(2))


def clean_chord_text(token: str) -> str:
    t = token.strip()
    if t.startswith("(") and t.endswith(")"):
        t = t[1:-1]
    t = t.rstrip("*!,;")
    while t.endswith("..."):
        t = t[:-3]
    return t.strip()


def classify_token(text: str) -> TokenKind:
    if _NC_RE.match(text):
        return "nc"
    if repeat_count(text) is not None:
        return "repeat"
    if _BAR_RE.match(text):
        return "bar"
    core = clean_chord_text(text)
    if core and parse_chord(core) is not None:
        return "chord"
    return "other"


def _split_token(text: str, pos: int) -> list[tuple[str, int]]:
    """Split bar lines and a trailing (x2) off a token: '|Am|' -> '|', 'Am', '|'."""
    out: list[tuple[str, int]] = []
    m = re.match(r"^(.*?)(\(\s*[xх×]?\s*\d+\s*[xх×]?\s*\))$", text)
    tail = None
    if m and m.group(1) and repeat_count(m.group(2)) is not None:
        text, tail = m.group(1), (m.group(2), pos + len(m.group(1)))
    for part in re.finditer(r"\|+:?|:\|+|[^|]+", text):
        out.append((part.group(0), pos + part.start()))
    if tail:
        out.append(tail)
    return out


def tokenize(line: str) -> list[Token]:
    tokens = []
    for m in re.finditer(r"\S+", line):
        for text, pos in _split_token(m.group(0), m.start()):
            tokens.append(Token(text=text, pos=pos, kind=classify_token(text)))
    return tokens


def is_chord_line(tokens: list[Token]) -> bool:
    chords = sum(1 for t in tokens if t.kind == "chord")
    others = sum(1 for t in tokens if t.kind == "other")
    if chords == 0:
        return any(t.kind == "nc" for t in tokens) and others == 0
    return others == 0 or (chords >= 2 and chords >= 3 * others)


def _chordpro(line: str) -> tuple[str, list[Token]] | None:
    """Chords inside the lyrics: '[Am]Some [F]words' -> ('Some words', [Am@0, F@5])."""
    matches = list(_CHORDPRO_RE.finditer(line))
    if not matches:
        return None
    tokens: list[Token] = []
    lyrics = []
    last = 0
    for m in matches:
        inner = m.group(1).strip()
        kind = classify_token(inner)
        if kind not in ("chord", "nc"):
            return None
        lyrics.append(line[last : m.start()])
        tokens.append(Token(text=inner, pos=len("".join(lyrics)), kind=kind))
        last = m.end()
    lyrics.append(line[last:])
    return "".join(lyrics).rstrip(), tokens


def _label(line: str) -> tuple[str, SectionKind, int | None, str] | None:
    """A section label, with its kind, repeat count and any text after it on the line."""
    m = _BRACKET_LABEL_RE.match(line)
    if m:
        inner, rest = m.group(1).strip(), m.group(2)
        if classify_token(inner) in ("chord", "nc"):
            return None
        repeat = None
        tail = _REPEAT_TAIL_RE.search(inner)
        if tail and tail.start() > 0:
            repeat = int(tail.group(1) or tail.group(2))
            inner = inner[: tail.start()].strip()
        kind = section_kind(inner) or "other"
        rest_repeat = repeat_count(rest)
        if rest_repeat is not None:
            return inner, kind, rest_repeat, ""
        return inner, kind, repeat, rest
    m = _PAREN_LABEL_RE.match(line)
    if m and section_kind(m.group(1)):
        inner = m.group(1).strip()
        return inner, section_kind(inner) or "other", None, ""
    m = re.match(
        r"^\s*(?P<label>(?:" + _SECTION_RE.pattern + r")(?:\s*\d+|\s+[IVX]+)?)"
        r"(?P<rep>\s*\(?\s*" + _REPEAT + r"\s*\)?)?\s*(?P<colon>:)?\s*(?P<rest>.*)$",
        line,
        re.IGNORECASE,
    )
    if not m:
        return None
    rest = m.group("rest")
    rest_tokens = tokenize(rest)
    if (
        rest
        and not m.group("colon")
        and not is_chord_line(rest_tokens)
        and repeat_count(rest) is None
    ):
        return None  # "Chorus of angels..." is a lyric line
    label = m.group("label").strip()
    repeat = None
    if m.group("rep"):
        repeat = repeat_count(m.group("rep").strip())
    elif repeat_count(rest) is not None:
        repeat, rest = repeat_count(rest), ""
    return label, section_kind(label) or "other", repeat, rest


def _capo(value: str) -> int:
    v = value.strip().lower()
    if re.match(r"^(?:no|none|нет|без)\b", v) or not v:
        return 0
    m = re.search(r"(\d+)", v)
    if m:
        return int(m.group(1))
    m = re.search(r"\b([ivx]+)\b", v)
    return _ROMAN.get(m.group(1), 0) if m else 0


_STANDARD = ["E", "A", "D", "G", "B", "E"]


def tuning_offset(value: str) -> int:
    """Half steps a tuning sounds above standard: 'half step down' and 'Eb' are -1."""
    v = value.strip().lower().replace("½", "1/2")
    if not v or re.match(r"^(?:standard|стандарт|e\s*a\s*d\s*g\s*b\s*e|drop\s*d)\b", v):
        return 0
    half = (
        re.search(r"(?:half|1/2|пол)\s*-?\s*(?:a\s+)?(?:step|tone|тона|тон)", v) or "полтона" in v
    )
    whole = re.search(r"(?:whole|full|1)\s*-?\s*(?:step|tone|тон)", v) or "тон " in v
    down = re.search(r"\b(?:down|lower|ниже|вниз)\b", v)
    up = re.search(r"\b(?:up|higher|выше|вверх)\b", v)
    if half or whole:
        n = 1 if half else 2
        return n if up and not down else -n
    m = re.match(r"^([a-g])\s*(#|b|♯|♭)?\s*(?:standard)?\b", v)
    if m and not re.match(r"^drop", v):
        letter, acc = m.group(1).upper(), m.group(2) or ""
        if letter == "D" and not acc:
            return -2
        if letter == "E":
            return {"b": -1, "♭": -1, "#": 1, "♯": 1}.get(acc, 0)
    return 0


def _split_title(text: str) -> tuple[str | None, str | None]:
    """'Perfect chords by Ed Sheeran' -> title, artist; 'Кино - Группа крови' -> artist - title."""
    text = text.strip()
    m = re.match(r"^(.*?)\s+(?:chords\s+|аккорды\s+)?(?:by|от)\s+(.+)$", text, re.IGNORECASE)
    if m:
        return _TITLE_NOISE_RE.sub("", m.group(1)).strip() or None, m.group(2).strip()
    for dash in (" - ", " – ", " — "):
        if dash in text:
            artist, title = text.split(dash, 1)
            return _TITLE_NOISE_RE.sub("", title).strip() or None, artist.strip() or None
    return _TITLE_NOISE_RE.sub("", text).strip() or None, None


def _directive(line: str, meta: SheetMeta) -> tuple[str, str | None] | None:
    m = _DIRECTIVE_RE.match(line)
    if not m:
        return None
    return m.group(1).lower(), m.group(2)


_DIRECTIVE_SECTIONS = {
    "start_of_chorus": "chorus",
    "soc": "chorus",
    "start_of_verse": "verse",
    "sov": "verse",
    "start_of_bridge": "bridge",
    "sob": "bridge",
}


def sort_lines(sheet: SheetText) -> SortedSheet:
    meta = SheetMeta()
    out: list[SortedLine] = []
    in_tab = False
    for index, tl in enumerate(sheet.lines):
        raw = _UG_TAGS_RE.sub("", tl.text)
        line = raw.rstrip()
        common = {"text": line, "index": index, "source": tl.source}
        if not line.strip():
            out.append(SortedLine(kind="blank", **common))
            continue

        directive = _directive(line, meta)
        if directive:
            name, value = directive
            value = (value or "").strip()
            if name in ("start_of_tab", "sot"):
                in_tab = True
            elif name in ("end_of_tab", "eot"):
                in_tab = False
            elif name in ("title", "t"):
                meta.title = value or meta.title
            elif name in ("subtitle", "st", "artist"):
                meta.artist = value or meta.artist
            elif name == "key":
                meta.stated_key = value or None
            elif name == "capo":
                meta.capo = _capo(value)
            elif name == "tempo" and re.match(r"^\d+(\.\d+)?$", value):
                meta.tempo = float(value)
            elif name == "time":
                meta.time_signature = value or None
            elif name in _DIRECTIVE_SECTIONS:
                kind = _DIRECTIVE_SECTIONS[name]
                out.append(SortedLine(kind="section", section=kind, label=value or None, **common))
                continue
            elif name in ("comment", "c", "ci", "cb", "comment_italic", "comment_box"):
                kind = section_kind(value)
                if kind:
                    out.append(SortedLine(kind="section", section=kind, label=value, **common))
                    continue
            out.append(SortedLine(kind="meta", **common))
            continue
        if in_tab:
            out.append(SortedLine(kind="tab", **common))
            continue

        meta_kind = _meta_line(line, meta)
        if meta_kind:
            out.append(SortedLine(kind="meta", **common))
            continue

        tokens = tokenize(line)
        if any(_DIAGRAM_RE.match(t.text) for t in tokens):
            out.append(SortedLine(kind="diagram", **common))
            continue
        if line.count("-") >= 4 and _TAB_RE.match(line):
            out.append(SortedLine(kind="tab", **common))
            continue

        label = _label(line)
        if label:
            text, kind, repeat, rest = label
            rest_tokens = []
            if rest.strip():
                offset = len(line) - len(rest)
                rest_tokens = [t.model_copy(update={"pos": t.pos + offset}) for t in tokenize(rest)]
                if not is_chord_line(rest_tokens):
                    rest_tokens = []
            out.append(
                SortedLine(
                    kind="section",
                    section=kind,
                    label=text,
                    repeat=repeat,
                    tokens=rest_tokens,
                    **common,
                )
            )
            continue

        if is_chord_line(tokens):
            repeat = next((repeat_count(t.text) for t in tokens if t.kind == "repeat"), None)
            out.append(SortedLine(kind="chords", tokens=tokens, repeat=repeat, **common))
            continue

        chordpro = _chordpro(line)
        if chordpro:
            lyrics, cp_tokens = chordpro
            lyrics, repeat = _strip_repeat(lyrics)
            out.append(
                SortedLine(kind="lyrics", lyrics=lyrics, tokens=cp_tokens, repeat=repeat, **common)
            )
            continue

        lyrics, repeat = _strip_repeat(line)
        out.append(SortedLine(kind="lyrics", lyrics=lyrics, repeat=repeat, **common))

    _mark_header(out, meta)
    uses_h = any(
        t.kind == "chord" and clean_chord_text(t.text)[:1] in ("H", "Н")
        for line in out
        if line.kind in ("chords", "section", "lyrics")
        for t in line.tokens
    )
    return SortedSheet(lines=out, meta=meta, uses_h=uses_h)


def _strip_repeat(text: str) -> tuple[str, int | None]:
    m = _REPEAT_TAIL_RE.search(text)
    if m and m.start() > 0 and text[: m.start()].strip():
        return text[: m.start()].rstrip(), int(m.group(1) or m.group(2))
    return text, None


def _meta_line(line: str, meta: SheetMeta) -> str | None:
    for name, pattern in _META_PATTERNS:
        m = pattern.match(line)
        if not m:
            continue
        value = m.group(1).strip() if m.groups() else ""
        if name == "capo":
            meta.capo = _capo(value)
        elif name == "tuning":
            meta.tuning = tuning_offset(value)
            meta.tuning_text = value or None
        elif name == "key":
            meta.stated_key = value.split()[0] if value else None
        elif name == "tempo":
            meta.tempo = float(value)
        elif name == "time":
            meta.time_signature = re.sub(r"\s+", "", value)
        elif name == "title":
            meta.title = value
        elif name == "artist":
            meta.artist = value
        return name
    return None


def _mark_header(lines: list[SortedLine], meta: SheetMeta) -> None:
    """Short lines before the music starts are the title and artist."""
    first_music = next(
        (
            i
            for i, line in enumerate(lines)
            if line.kind in ("chords", "section", "tab", "diagram") or line.tokens
        ),
        len(lines),
    )
    candidates = [i for i in range(first_music) if lines[i].kind == "lyrics"]
    if not candidates or len(candidates) > 3:
        return
    # Lyrics running straight into a chord line are the song's opening, not a header; a blank
    # line, a capo note or a section label in between marks the end of the header.
    runs_into_chords = (
        first_music < len(lines)
        and candidates[-1] == first_music - 1
        and lines[first_music].kind != "section"
    )
    if runs_into_chords:
        return
    texts = [lines[i].text.strip() for i in candidates]
    for i in candidates:
        lines[i] = lines[i].model_copy(update={"kind": "header", "lyrics": None, "repeat": None})
    if meta.title is None:
        title, artist = _split_title(texts[0])
        meta.title = title
        if meta.artist is None and artist:
            meta.artist = artist
    if meta.artist is None and len(texts) > 1:
        second = re.sub(r"^(?:by|artist|исполнитель|группа)\s*[:\-]?\s*", "", texts[1], flags=re.I)
        meta.artist = second.strip() or None
