#!/usr/bin/env python3
"""Build small-font U+E705 〈口𠂹〉 from two complete Songti components.

Default rebuilds and checks the frozen recipe in memory. --write-recipe writes
only authoring JSON/SVGs; production font changes use guji_pua_patch.py.
"""
import argparse
import hashlib
import json
from pathlib import Path

from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from guji_songti_components import bbox, contours, in_box, moved

ROOT = Path(__file__).resolve().parents[2]
FONT0 = ROOT / 'guji-preview-grid/public/fonts/guji-plane0.ttf'
FONT2 = ROOT / 'guji-preview-grid/public/fonts/guji-plane2.ttf'
RECIPE = ROOT / 'tools/dataset/font-sources/e705-songti-v1.json'


def glyph_hash(font, char):
    return hashlib.sha256(font['glyf'][font.getBestCmap()[ord(char)]].compile(font['glyf'])).hexdigest()


def build(font, plane2):
    if font['head'].unitsPerEm != 1024 or plane2['head'].unitsPerEm != 1024:
        raise ValueError('Expected matching 1024-unit Songti fonts')
    parts, pen = [], TTGlyphPen(font.getGlyphSet())
    for char, donor, indices, target, role, color in [
        ('吹', font, [0, 1], (30, 290, 235, 745), '左口（口旁外轮廓与内白）', '#2563a6'),
        ('𠂹', plane2, [0, 1, 2, 3, 4], (195, -146, 998, 848), '右𠂹（整字五轮廓）', '#258054'),
    ]:
        source = RecordingPen()
        outlines = contours(donor, char)
        if char == '𠂹' and len(outlines) != len(indices):
            raise ValueError('The complete 𠂹 source contour inventory changed')
        for index in indices:
            outlines[index].replay(source)
        transform = in_box(source, target)
        if transform.xx * transform.yy - transform.xy * transform.yx <= 0:
            raise ValueError('Reflected source component')
        result = moved(source, transform)
        result.replay(pen)
        src, dst = SVGPathPen(None), SVGPathPen(None)
        source.replay(src)
        result.replay(dst)
        parts.append({
            'source_char': char, 'codepoint': f'U+{ord(char):X}',
            'source_font': 'guji-plane2.ttf' if donor is plane2 else 'guji-plane0.ttf',
            'contours': indices, 'role': role, 'color': color,
            'extraction': 'complete component contours; one shared positive affine transform; no trimming or redrawing',
            'source_bounds': list(bbox(source)), 'bounds': list(bbox(result)),
            'transform': list(transform), 'source_path': src.getCommands(),
            'path': dst.getCommands(),
        })
    glyph = pen.glyph()
    glyph.recalcBounds(font['glyf'])
    return glyph, parts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-recipe', action='store_true')
    parser.add_argument('--figures', type=Path, default=ROOT/'var/font-audit/0407/composition')
    args = parser.parse_args()
    with TTFont(FONT0, recalcTimestamp=False) as font, TTFont(FONT2, recalcTimestamp=False) as plane2:
        glyph, parts = build(font, plane2)
        digest = hashlib.sha256(glyph.compile(font['glyf'])).hexdigest()
        recipe = {
            'schema': 2, 'scheme': 'compose', 'construction': 'mouth-and-whole-u200b9',
            'description': 'U+E705：康熙 @407 他条「【註】他音〈口𠂹〉」，仅小字。',
            'units_per_em': 1024, 'font': 'guji-plane0.ttf',
            'generator': 'tools/dataset/guji_kou_200b9_components.py',
            'scan_source': 'tools/dataset/font-sources/e705-scan-original.png',
            'descriptive_ids': '⿰口𠂹',
            'donor_glyph_sha256': {'5439': glyph_hash(font, '吹')},
            'external_donors': [{'font': 'guji-preview-grid/public/fonts/guji-plane2.ttf',
                'font_sha256': hashlib.sha256(FONT2.read_bytes()).hexdigest(),
                'glyph_sha256': {'200B9': glyph_hash(plane2, '𠂹')}}],
            'components': parts,
            'approved_glyph': {
                'number_of_contours': glyph.numberOfContours,
                'coordinates': [list(p) for p in glyph.coordinates],
                'end_points': list(glyph.endPtsOfContours), 'flags': list(glyph.flags),
                'instructions': list(glyph.program.getBytecode()), 'compiled_sha256': digest,
            },
            'metrics': {'hmtx': [1024, glyph.xMin], 'vmtx': [1024, 870-glyph.yMax]},
            'verification': {'max_chamfer': 3.4,
                'note': 'Whole native Songti components preserve structure, not scan proportions pixel by pixel. Chamfer is only a regression guard; exact donor/outline hashes, component separation and small-size review are required.'},
            'note': 'Two logical components, seven contours including the mouth counter; no contour cuts, per-stroke changes, Boolean union or scan tracing.',
        }
        if args.write_recipe:
            RECIPE.write_text(json.dumps(recipe, ensure_ascii=False, indent=2)+'\n')
            args.figures.mkdir(parents=True, exist_ok=True)
            for i, part in enumerate(parts):
                donor = plane2 if part['source_font'] == 'guji-plane2.ttf' else font
                gs = donor.getGlyphSet()
                whole = SVGPathPen(gs)
                gs[donor.getBestCmap()[ord(part['source_char'])]].draw(whole)
                (args.figures/f'source-{i}.svg').write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
                    '<g transform="matrix(1 0 0 -1 0 870)">'
                    f'<path d="{whole.getCommands()}" fill="#dad7d1"/>'
                    f'<path d="{part["source_path"]}" fill="{part["color"]}"/></g></svg>')
                (args.figures/f'part-{i}.svg').write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
                    '<g transform="matrix(1 0 0 -1 0 870)">'
                    f'<path d="{part["path"]}" fill="{part["color"]}"/></g></svg>')
            paths = ''.join(f'<path d="{p["path"]}" fill="{p["color"]}"/>' for p in parts)
            (args.figures/'components.svg').write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
                '<g transform="matrix(1 0 0 -1 0 870)">'+paths+'</g></svg>')
            print('Wrote recipe and component SVGs; production fonts unchanged.')
        else:
            frozen = json.loads(RECIPE.read_text())
            if frozen != recipe:
                raise SystemExit('Rebuilt recipe differs from frozen data; review before updating.')
            print('Native components reproduce the frozen U+E705 exactly.')
        print(digest, glyph.numberOfContours, len(glyph.coordinates), recipe['metrics'])


if __name__ == '__main__':
    main()
