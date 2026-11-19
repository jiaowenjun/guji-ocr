#!/usr/bin/env python3
"""Build small-font U+E707, the 〈貝司〉 glyph variant of U+4F3A.

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
RECIPE = ROOT / 'tools/dataset/font-sources/e707-songti-v2.json'


def glyph_hash(font, char):
    name = font.getBestCmap()[ord(char)]
    return hashlib.sha256(font['glyf'][name].compile(font['glyf'])).hexdigest()


def build(font):
    """Join the native left 貝 component of 䝭 and right 司 component of 伺."""
    definitions = [
        ('䝭', [0, 4, 5, 6, 7, 8], '左貝旁（完整偏旁）'),
        ('伺', [0, 1, 3, 4], '右司旁（完整偏旁）'),
    ]
    parts, pen = [], TTGlyphPen(font.getGlyphSet())
    for char, indices, role in definitions:
        source = RecordingPen()
        source_contours = contours(font, char)
        for index in indices:
            source_contours[index].replay(source)
        transform = Transform()
        if transform.xx * transform.yy - transform.xy * transform.yx <= 0:
            raise ValueError('Reflected source component')
        result = moved(source, transform)
        result.replay(pen)
        src_path, dst_path = SVGPathPen(None), SVGPathPen(None)
        source.replay(src_path)
        result.replay(dst_path)
        parts.append({
            'source_char': char,
            'codepoint': f'U+{ord(char):04X}',
            'source_font': 'guji-plane0.ttf',
            'contours': indices,
            'role': role,
            'extraction': 'complete native side component; identity transform; no trimming, scaling, mirroring or redrawing',
            'source_bounds': list(bbox(source)),
            'bounds': list(bbox(result)),
            'transform': list(transform),
            'source_path': src_path.getCommands(),
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
            'schema': 2,
            'scheme': 'compose',
            'construction': 'left-component-of-u476d-right-component-of-u4f3a',
            'description': 'U+E707：康熙 @427 伺条「別作〈貝司〉」的字形异体，仅小字。',
            'units_per_em': 1024,
            'font': 'guji-plane0.ttf',
            'generator': 'tools/dataset/guji_beisi_components.py',
            'scan_source': 'tools/dataset/font-sources/e707-scan-original.png',
            'descriptive_ids': '⿰貝司',
            'encoded_identity': {'char': '伺', 'codepoint': 'U+4F3A'},
            'donor_glyph_sha256': {
                '476D': glyph_hash(font, '䝭'),
                '4F3A': glyph_hash(font, '伺'),
            },
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
                'max_chamfer': 2.1,
                'note': 'Threshold-100 scan mask is a regression guard. Character identity follows the 伺 entry; exact structure and complete native contour provenance are reviewed separately.',
            },
            'note': 'Ten complete native Songti contours: the six-contour left 貝 component of 䝭 and the four-contour right 司 component of 伺. Both retain their compound-character coordinates with identity transforms.',
        }
        if args.write_recipe:
            RECIPE.write_text(json.dumps(recipe, ensure_ascii=False, indent=2) + '\n')
            print('Wrote recipe; production font unchanged.')
        else:
            frozen = json.loads(RECIPE.read_text())
            if frozen != recipe:
                raise SystemExit('Rebuilt recipe differs from frozen data; review before updating.')
            print('Native components reproduce the frozen U+E707 exactly.')
        print(digest, glyph.numberOfContours, len(glyph.coordinates), recipe['metrics'])


if __name__ == '__main__':
    main()
