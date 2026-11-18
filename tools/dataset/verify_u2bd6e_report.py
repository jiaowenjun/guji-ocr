#!/usr/bin/env python3
"""Read-only reproduction of the historical U+2BD6E outline.

Calibration must use the original font's stored 丰 bbox. Saving the patched
font recalculated that bbox, so calibrating from today's font is not identical.
No font, registry or operation log is written.
"""
import hashlib
import io
import json
from pathlib import Path
import subprocess

from fontTools.misc.transform import Transform
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import parse_path
from fontTools.ttLib import TTFont

from kangxi_font_patch import calibrate, svg_path_d

ROOT = Path(__file__).resolve().parents[2]
FONT_PATH = 'guji-preview-grid/public/fonts/guji-large.ttf'
BASELINE_REF = '80cea9a'
BASELINE_SHA = 'dfc5876c1a580922798e5da3f7b58d6bdcf419c294622d67a8a07cf3256da87f'
EVIDENCE = ROOT / 'docs/research/evidence/u2bd6e'


def main():
    baseline = subprocess.check_output(
        ['git', 'show', f'{BASELINE_REF}:{FONT_PATH}'], cwd=ROOT)
    if hashlib.sha256(baseline).hexdigest() != BASELINE_SHA:
        raise SystemExit('Historical baseline hash mismatch')
    source = EVIDENCE / '0334-04-K0000.svg'
    anchor = EVIDENCE / '0334-03-00054-4E30.svg'
    expected_sources = {
        source: '40aca218281b9efe68b7046acac6448684457cf34cf5a756d65fb857d00f13fd',
        anchor: '79391933238c65e3e99cf0f0eb07996875eb5361a16b8ee5e27ff7f5ee743a45',
    }
    for path, expected in expected_sources.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SystemExit(f'Source hash mismatch: {path.name}')
    with TTFont(io.BytesIO(baseline)) as old, TTFont(ROOT / FONT_PATH) as current:
        s, tx, ty = calibrate(old, 0x4E30, str(anchor))
        pen = TTGlyphPen(old.getGlyphSet())
        parse_path(svg_path_d(str(source)), Cu2QuPen(
            TransformPen(pen, Transform(s, 0, 0, s, tx, ty)),
            max_err=1.0, reverse_direction=True))
        glyph = pen.glyph()
        glyph.recalcBounds(old['glyf'])
        rebuilt = hashlib.sha256(glyph.compile(old['glyf'])).hexdigest()
        name = current.getBestCmap()[0x2BD6E]
        stored = hashlib.sha256(current['glyf'][name].compile(current['glyf'])).hexdigest()
        if rebuilt != stored:
            raise SystemExit('Rebuilt outline differs from current U+2BD6E')
        print(json.dumps({'baseline_ref': BASELINE_REF, 'baseline_sha256': BASELINE_SHA,
                          'transform': [s, 0, 0, s, tx, ty],
                          'compiled_sha256': rebuilt, 'exact_match': True}, indent=2))


if __name__ == '__main__':
    main()
