#!/usr/bin/env python3
"""Build small-font U+E706, the three-side-person variant of U+343A.

Default rebuilds and checks the frozen recipe in memory. --write-recipe writes
only the authoring JSON; production font changes use guji_pua_patch.py.
"""
import argparse
import hashlib
import json
from pathlib import Path

from fontTools.misc.transform import Transform
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from guji_songti_components import bbox, contours, moved

ROOT = Path(__file__).resolve().parents[2]
FONT = ROOT / 'guji-preview-grid/public/fonts/guji-plane0.ttf'
RECIPE = ROOT / 'tools/dataset/font-sources/e706-songti-v1.json'


def glyph_hash(font, char):
    name = font.getBestCmap()[ord(char)]
    return hashlib.sha256(font['glyf'][name].compile(font['glyf'])).hexdigest()


def build(font):
    """Keep 㐺's two native 亻 contours and repeat the second at right."""
    source = contours(font, '㐺')
    if len(source) != 3:
        raise ValueError('U+343A contour inventory changed')
    definitions = [
        (1, Transform(1, 0, 0, 1, 65, 0), '左亻'),
        (2, Transform(1, 0, 0, 1, 75, 0), '中亻'),
        (2, Transform(1, 0, 0, 1, 370, 0), '右亻'),
    ]
    parts, pen = [], TTGlyphPen(font.getGlyphSet())
    for index, transform, role in definitions:
        rec = source[index]
        if transform.xx * transform.yy - transform.xy * transform.yx <= 0:
            raise ValueError('Reflected source component')
        result = moved(rec, transform)
        result.replay(pen)
        src_path, dst_path = SVGPathPen(None), SVGPathPen(None)
        rec.replay(src_path)
        result.replay(dst_path)
        parts.append({
            'source_char': '㐺', 'codepoint': 'U+343A',
            'source_font': 'guji-plane0.ttf', 'contour': index,
            'role': role,
            'extraction': 'complete native contour; translation only; no trimming, scaling or redrawing',
            'source_bounds': list(bbox(rec)), 'bounds': list(bbox(result)),
            'transform': list(transform), 'source_path': src_path.getCommands(),
            'path': dst_path.getCommands(),
        })
    glyph = pen.glyph()
    glyph.recalcBounds(font['glyf'])
    return glyph, parts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-recipe', action='store_true')
    args = parser.parse_args()
    with TTFont(FONT, recalcTimestamp=False) as font:
        glyph, parts = build(font)
        digest = hashlib.sha256(glyph.compile(font['glyf'])).hexdigest()
        recipe = {
            'schema': 2, 'scheme': 'compose',
            'construction': 'three-side-person-variant-of-u343a',
            'description': 'U+E706：康熙 @421 㐺条「亦作〈亻亻亻〉」的字形异体，仅小字。',
            'units_per_em': 1024, 'font': 'guji-plane0.ttf',
            'generator': 'tools/dataset/guji_three_person_variant_components.py',
            'scan_source': 'tools/dataset/font-sources/e706-scan-original.png',
            'descriptive_ids': '⿲亻亻亻',
            'encoded_identity': {'char': '㐺', 'codepoint': 'U+343A'},
            'donor_glyph_sha256': {'343A': glyph_hash(font, '㐺')},
            'components': parts,
            'approved_glyph': {
                'number_of_contours': glyph.numberOfContours,
                'coordinates': [list(point) for point in glyph.coordinates],
                'end_points': list(glyph.endPtsOfContours),
                'flags': list(glyph.flags),
                'instructions': list(glyph.program.getBytecode()),
                'compiled_sha256': digest,
            },
            'metrics': {
                'hmtx': [1024, glyph.xMin],
                'vmtx': [1024, 870 - glyph.yMax],
            },
            'verification': {
                'max_chamfer': 0.85,
                'note': 'Threshold-80 scan mask is a regression guard. Character identity follows the 㐺 entry; exact structure and native contour provenance are reviewed separately.',
            },
            'note': 'Three complete native Songti contours. The first two are U+343A contours 1 and 2; the right 亻 repeats contour 2. All transforms are translations.',
        }
        if args.write_recipe:
            RECIPE.write_text(json.dumps(recipe, ensure_ascii=False, indent=2) + '\n')
            print('Wrote recipe; production font unchanged.')
        else:
            frozen = json.loads(RECIPE.read_text())
            if frozen != recipe:
                raise SystemExit('Rebuilt recipe differs from frozen data; review before updating.')
            print('Native components reproduce the frozen U+E706 exactly.')
        print(digest, glyph.numberOfContours, len(glyph.coordinates), recipe['metrics'])


if __name__ == '__main__':
    main()
