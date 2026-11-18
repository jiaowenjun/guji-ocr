#!/usr/bin/env python3
"""Reproduce the small-font U+E704 〈二心支〉 from native Songti contours.

Default: rebuild in memory and verify the frozen recipe. --write-recipe writes
the authoring recipe and component SVGs, never a production font. Requires
fontTools and skia-pathops (the latter only for the contour union).
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
from fontTools.ttLib.removeOverlaps import removeOverlaps

from guji_songti_components import bbox, contours, in_box, moved

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / 'tools/dataset/font-sources/e704-songti-v1.json'
FONT0 = ROOT / 'guji-preview-grid/public/fonts/guji-plane0.ttf'
FONT2 = ROOT / 'guji-preview-grid/public/fonts/guji-plane2.ttf'


def glyph_hash(font, char):
    name = font.getBestCmap()[ord(char)]
    return hashlib.sha256(font['glyf'][name].compile(font['glyf'])).hexdigest()


def build(font, plane2):
    parts = []

    def add(char, donor, indices, role, color, transform=None, target=None,
            trim_join_serif=False):
        source = RecordingPen()
        outlines = contours(donor, char)
        for index in indices:
            outlines[index].replay(source)
        extraction = 'complete contours; one positive affine transform'
        if trim_join_serif:
            # At a joined stroke the freestanding stem's entry serif would
            # become a false diagonal spur. Keep the existing straight sides,
            # extend them to the original top, and close them inside the bar.
            assert source.value[:3] == [
                ('moveTo', ((48, 649),)), ('lineTo', ((478, 649),)),
                ('lineTo', ((478, 799),))]
            assert source.value[8] == ('lineTo', ((524, 649),))
            source.value = source.value[:2] + [
                ('lineTo', ((478, 852),)), ('lineTo', ((524, 852),))
            ] + source.value[8:]
            extraction = 'whole 支 with freestanding top serif removed at bar junction; straight stem sides extended to original y=852; counter preserved'
        transform = transform or in_box(source, target)
        assert transform.xx * transform.yy - transform.xy * transform.yx > 0
        result = moved(source, transform)
        src_pen, dst_pen = SVGPathPen(None), SVGPathPen(None)
        source.replay(src_pen)
        result.replay(dst_pen)
        parts.append({
            'source_char': char, 'codepoint': f'U+{ord(char):X}',
            'source_font': 'guji-plane2.ttf' if donor is plane2 else 'guji-plane0.ttf',
            'contours': indices, 'role': role, 'color': color,
            'extraction': extraction,
            'source_bounds': list(bbox(source)), 'bounds': list(bbox(result)),
            'transform': list(transform), 'source_path': src_pen.getCommands(),
            'path': dst_pen.getCommands(), 'recording': result,
        })

    # The parent headword supplies the two enclosing horizontal strokes.
    # Raise both by 23 units to use the plane0 vertical origin (870) with a
    # top side bearing of 22. The top remains joined to the 支 stem after union.
    add('𠄹', plane2, [3], '上横', '#2563a6', Transform(1, 0, 0, 1, 0, 23))
    add('𠄹', plane2, [4], '下横', '#2563a6', Transform(1, 0, 0, 1, 0, 23))
    # Preserve all four strokes of 心, including the hook; 忄 is not equivalent.
    add('心', font, [0, 1, 2, 3], '左侧心（完整四笔）', '#258054',
        target=(44, 138, 559, 664))
    # Both contours are needed: the second is the counter inside 又.
    add('支', font, [0, 1], '右侧支（十与又整体，接横处去衬线）', '#b5463e',
        target=(390, 10, 984, 789), trim_join_serif=True)

    pen = TTGlyphPen(font.getGlyphSet())
    for item in parts:
        item['recording'].replay(pen)
    name = 'e704.authoring'
    font['glyf'][name] = pen.glyph()
    font['hmtx'][name] = (1024, 25)
    font['vmtx'][name] = (1024, 22)
    font.setGlyphOrder(font.getGlyphOrder() + [name])
    removeOverlaps(font, glyphNames=[name])
    glyph = font['glyf'][name]
    glyph.recalcBounds(font['glyf'])
    return glyph, [{k: v for k, v in p.items() if k != 'recording'} for p in parts]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-recipe', action='store_true')
    parser.add_argument('--figures', type=Path,
                        default=ROOT / 'var/font-audit/0373/composition')
    args = parser.parse_args()
    font, plane2 = TTFont(FONT0, recalcTimestamp=False), TTFont(FONT2, recalcTimestamp=False)
    donor_hashes = {f'{ord(c):X}': glyph_hash(font, c) for c in '心支'}
    external_hash = glyph_hash(plane2, '𠄹')
    glyph, parts = build(font, plane2)
    compiled = hashlib.sha256(glyph.compile(font['glyf'])).hexdigest()
    recipe = {
        'schema': 2, 'scheme': 'compose', 'construction': 'two-bars-heart-zhi',
        'description': 'U+E704：康熙 @373 𠄹条引《風雅廣逸》〈二心支〉，仅小字。',
        'units_per_em': 1024, 'font': 'guji-plane0.ttf',
        'generator': 'tools/dataset/guji_erxin_zhi_components.py',
        'scan_source': 'tools/dataset/font-sources/e704-scan-original.png',
        'descriptive_ids': '⿳一⿰心支一',
        'donor_glyph_sha256': donor_hashes,
        'external_donors': [{
            'font': 'guji-preview-grid/public/fonts/guji-plane2.ttf',
            'font_sha256': hashlib.sha256(FONT2.read_bytes()).hexdigest(),
            'glyph_sha256': {'20139': external_hash},
        }],
        'components': parts,
        'approved_glyph': {
            'number_of_contours': glyph.numberOfContours,
            'coordinates': [list(p) for p in glyph.coordinates],
            'end_points': list(glyph.endPtsOfContours), 'flags': list(glyph.flags),
            'instructions': list(glyph.program.getBytecode()), 'compiled_sha256': compiled,
        },
        'metrics': {'hmtx': [1024, glyph.xMin], 'vmtx': [1024, 870 - glyph.yMax]},
        'verification': {
            'max_chamfer': 1.8,
            'note': '宋体构形与低分辨率刻本不是逐像素描摹；距离仅作错字/错位回归闸，须结合部件、连接、来源哈希及混排图核验。',
        },
        'note': '4 个逻辑部件，8 条原生轮廓；支含反向内轮廓。只在上横与支竖交叠处做布尔合并。',
    }
    if args.write_recipe:
        RECIPE.write_text(json.dumps(recipe, ensure_ascii=False, indent=2) + '\n')
        args.figures.mkdir(parents=True, exist_ok=True)
        for i, part in enumerate(parts):
            donor = plane2 if part['source_font'] == 'guji-plane2.ttf' else font
            gs = donor.getGlyphSet()
            whole = SVGPathPen(gs)
            gs[donor.getBestCmap()[ord(part['source_char'])]].draw(whole)
            (args.figures / f'source-{i}.svg').write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
                '<g transform="matrix(1 0 0 -1 0 870)">'
                f'<path d="{whole.getCommands()}" fill="#dad7d1"/>'
                f'<path d="{part["source_path"]}" fill="{part["color"]}"/></g></svg>')
        paths = ''.join(f'<path d="{p["path"]}" fill="{p["color"]}"/>' for p in parts)
        (args.figures / 'components.svg').write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
            '<g transform="matrix(1 0 0 -1 0 870)">' + paths + '</g></svg>')
        print('Wrote recipe and component SVGs; production fonts unchanged.')
    else:
        frozen = json.loads(RECIPE.read_text())
        assert frozen['donor_glyph_sha256'] == donor_hashes
        assert frozen['external_donors'][0]['glyph_sha256']['20139'] == external_hash
        assert frozen['approved_glyph']['compiled_sha256'] == compiled
        assert frozen['components'] == parts
        assert frozen['metrics'] == recipe['metrics']
        print('Native components reproduce the frozen U+E704 exactly.')
    print(compiled, glyph.numberOfContours, len(glyph.coordinates), recipe['metrics'])


if __name__ == '__main__':
    main()
