"""Kangxi dictionary semantics, independent of .gj glyph layout.

The vocabulary is shared with the web semantic module; parity fixtures test both consumers.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parents[2] / 'guji-preview-grid/src/semantics/kangxi-rules.json').read_text())
IGNORED = RULES['ignored']


def _content(text: str) -> str:
    return ''.join(ch for ch in text if ch not in IGNORED and not ch.isspace())


def _han(ch: str) -> bool:
    cp = ord(ch)
    return 0x3400 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF or 0x20000 <= cp <= 0x323AF or 0xE000 <= cp <= 0xF8FF


def _line_tokens(line: str):
    """Yield (character, size, source_end, circled, book), with # scoped to this line."""
    large = book = False
    i = 0
    while i < len(line):
        ch = line[i]
        if line.startswith('//', i): break
        if ch == '#': large = True; i += 1; continue
        if ch == '【': book = True; i += 1; continue
        if ch == '】': book = False; i += 1; continue
        if large and ch in '(（':
            closed = re.match(r'([^()（）#【】\n]{1,2})[)）]', line[i+1:])
            inner = closed.group(1) if closed else (line[i+1:i+2] if line[i+1:i+2] not in ('', '#', '【', '】', '(', ')', '（', '）') else '')
            if inner:
                i += 1 + (len(closed.group(0)) if closed else len(inner))
                yield inner, large, i, True, book
                continue
        i += 1
        yield ' ' if ch in '*　' else ch, large, i, False, book


def section_heading(line: str) -> dict | None:
    tokens = list(_line_tokens(line.strip(' \t\r')))
    if not tokens or any(not large or circle or book for _, large, _, circle, book in tokens): return None
    text = ''.join(t[0] for t in tokens)
    name = text.lstrip(' ')
    indent = len(text) - len(name)
    if indent == 0 and name == RULES['bookTitle']: return {'kind': 'book', 'text': name, 'level': 1}
    if indent == 1 and len(name) == 3 and name[0] in RULES['collections'] and name[1] == '集' and name[2] in RULES['parts']:
        return {'kind': 'collection', 'text': name, 'level': 2}
    if indent == 2 and len(name) == 2 and name[0] in RULES['radicals'] and name[1] == '部':
        return {'kind': 'radical', 'text': name, 'level': 3}
    return None


def find_host_marks(raw_text: str) -> list[tuple[str, int]]:
    heads: list[tuple[str, int]] = []
    marker = ''
    variants = False
    has_current = False
    base = 0
    for raw in raw_text.splitlines(keepends=True):
        line = raw.rstrip('\r\n')
        if re.fullmatch(r'@\d+|=+', line.strip()) or section_heading(line):
            marker, variants = '', False
            has_current = False
        elif line.strip() and not line.lstrip().startswith('//'):
            tokens = list(_line_tokens(line))
            small = _content(''.join(t[0] for t in tokens if not t[1]))
            if small:
                if small == '古文' or (marker == '古' and small == '文'): marker, variants = '古文', True
                elif small == '古': marker, variants = small, False
                else: marker, variants = '', False
            glyphs = [(ch, end) for ch, large, end, circle, book in tokens if large and not circle and not book and _content(ch) and _han(ch)]
            if glyphs and not (variants and has_current):
                heads.append((glyphs[-1][0], base + glyphs[-1][1]))
                has_current = True
        base += len(raw)
    return heads


def strip_guwen_prefix(tail_raw: str) -> str:
    """Skip an explicit small guwen label and its following large variant lines."""
    prefix = re.match(r'^[\s，、,:：]*古\s*文[\s，、,:：]*', tail_raw)
    if not prefix: return tail_raw
    pos = prefix.end()
    found = False
    while pos < len(tail_raw):
        end = tail_raw.find('\n', pos)
        if end < 0: end = len(tail_raw)
        line = tail_raw[pos:end]
        if not line.strip(): pos = end + 1; continue
        if not line.lstrip(' \t').startswith('#') or section_heading(line): break
        found = True
        pos = min(end + 1, len(tail_raw))
    return tail_raw[pos:] if found else tail_raw
