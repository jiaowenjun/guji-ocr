#!/usr/bin/env python3
"""Rebuild U+E712 ⿰亻𫇮 from complete small-font components.

Default checks the frozen recipe without writing a font. --write-recipe writes
the authoring JSON; production insertion uses guji_pua_patch.py. --preview renders
production bytes after insertion or an in-memory diagnostic font before it.
--calibrate records scan-distance controls, including the headword 𠌾 (⿰亻莪)
whose native plane2 glyph doubles as the wrong-right confusable. Neither option
writes a font.
"""
import argparse
import hashlib
import json
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from fontTools.misc.transform import Transform
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from guji_songti_components import bbox, contours, in_box, moved

ROOT = Path(__file__).resolve().parents[2]
FONT0 = ROOT / 'guji-preview-grid/public/fonts/guji-plane0.ttf'
FONT2 = ROOT / 'guji-preview-grid/public/fonts/guji-plane2.ttf'
RECIPE = ROOT / 'tools/dataset/font-sources/e712-songti-v1.json'
SCAN = ROOT / 'tools/dataset/font-sources/e712-scan-original.png'
FIGURES = ROOT / 'docs/research/figures/e712'
# Both donors are external (plane2), the first such case with the radical also
# coming from the donor font's headword glyph.
DONOR_EXTERNAL = {
    '2033E': 'c7784b460721df2da6577c0c9bf2b20d11593bcfe1e1ff172702ff222e28ffb5',
    '2B1EE': 'b0976dd71825c0edc4e43e4fa46d5c04f993a5ca1ad4d2818c3a756d86e48d68',
}
# The 𫇮 component keeps its native y span while compressing to the family's
# right-half width; a global +5 y shift lands the radical top on 848 so the
# insert inherits the anchor vertical origin. RIGHT_TARGET is the PRE-shift
# box — the global shift is applied on top of it.
RIGHT_TARGET = (341.0, -125.0, 1009.0, 840.0)
GLOBAL_SHIFT_Y = 5.0


def verify_donors(font2):
    if font2['head'].unitsPerEm != 1024:
        raise ValueError('Expected 1024-unit Songti fonts')
    cmap = font2.getBestCmap()
    for cp, expected in DONOR_EXTERNAL.items():
        name = cmap[int(cp, 16)]
        if hashlib.sha256(font2['glyf'][name].compile(font2['glyf'])).hexdigest() != expected:
            raise ValueError(f'Donor U+{cp} changed; review the source contours')


def build(font0, font2):
    verify_donors(font2)
    parts, pen = [], TTGlyphPen(font0.getGlyphSet())
    plan = [
        ('𠌾', [1], None, '左亻（𠌾的完整单人旁，撇竖连体单轮廓）', '#2563a6'),
        ('𫇮', [0, 1, 2, 3], RIGHT_TARGET, '右𫇮（整字四轮廓）', '#258054'),
    ]
    for char, indices, target, role, color in plan:
        source = RecordingPen()
        outlines = contours(font2, char)
        if len(outlines) != (4 if char == '𠌾' else 4):
            raise ValueError('Donor contour inventory changed')
        for i in indices:
            outlines[i].replay(source)
        transform = (Transform(1, 0, 0, 1, 0, GLOBAL_SHIFT_Y) if target is None
                     else Transform(*in_box(source, target)[:4], in_box(source, target)[4],
                                    in_box(source, target)[5] + GLOBAL_SHIFT_Y))
        if transform.xx * transform.yy - transform.xy * transform.yx <= 0:
            raise ValueError('Reflected source component')
        result = moved(source, transform)
        result.replay(pen)
        src, dst = SVGPathPen(None), SVGPathPen(None)
        source.replay(src)
        result.replay(dst)
        parts.append({
            'source_char': char, 'codepoint': f'U+{ord(char):X}',
            'source_font': 'guji-plane2.ttf', 'contours': indices, 'role': role,
            'color': color, 'source_bounds': list(bbox(source)),
            'bounds': list(bbox(result)), 'transform': list(transform),
            'extraction': 'complete contours; one positive affine per component (right x-compressed to the family width, y preserved; whole composition shifted +5 y to the anchor origin); no trimming, mirroring, redrawing or union',
            'source_path': src.getCommands(), 'path': dst.getCommands(),
        })
    gap = parts[1]['bounds'][0] - parts[0]['bounds'][2]
    if gap < 16:
        raise ValueError('Insufficient component separation')
    glyph = pen.glyph()
    glyph.recalcBounds(font0['glyf'])
    if glyph.yMax != 848:
        raise ValueError('yMax must stay 848 to inherit the anchor vertical origin')
    return glyph, parts


def make_recipe(font0, font2):
    glyph, parts = build(font0, font2)
    return {
        'schema': 2, 'scheme': 'compose',
        'construction': 'left-radical-of-u2033e-and-whole-u2b1ee',
        'description': 'U+E712：康熙 @512 𠌾条「或作〈亻𫇮〉」；仅小字，完整构形不得用𠌾或𫇮代替。',
        'units_per_em': 1024, 'font': 'guji-plane0.ttf',
        'generator': 'tools/dataset/guji_ren_yi_components.py',
        'scan_source': 'tools/dataset/font-sources/e712-scan-original.png',
        'descriptive_ids': '⿰亻𫇮',
        'unicode_status': 'independent-codepoint-not-confirmed',
        'unicode_note': 'CHISE 无 ⿰亻𫇮 已编码字；𫇮 U+2B1EE 标准编码（plane2 在库），𠌾 U+2033E 自身 IDS 为 ⿰亻莪。站方段落把「或作」后字形懒代为𠌾，金标转写与截图结构（亻+上羊下我）支持〈亻𫇮〉。',
        'donor_glyph_sha256': {},
        'external_donors': [{
            'font': 'guji-preview-grid/public/fonts/guji-plane2.ttf',
            'font_sha256': hashlib.sha256(FONT2.read_bytes()).hexdigest(),
            'glyph_sha256': dict(DONOR_EXTERNAL),
        }],
        'components': parts,
        'approved_glyph': {
            'number_of_contours': glyph.numberOfContours,
            'coordinates': [list(p) for p in glyph.coordinates],
            'end_points': list(glyph.endPtsOfContours), 'flags': list(glyph.flags),
            'instructions': list(glyph.program.getBytecode()),
            'compiled_sha256': hashlib.sha256(glyph.compile(font0['glyf'])).hexdigest(),
        },
        'metrics': {'hmtx': [1024, glyph.xMin], 'vmtx': [1024, 870 - glyph.yMax]},
        'verification': {
            'max_chamfer': 4.4,
            'min_component_gap_units': 16,
            'note': 'Weak regression gate. As in E711 the woodblock draws a short 亻 while the donor radical is full-height, so the stylistic gap dominates: composition 3.672 vs wrong-right 𠌾 (⿰亻莪) 2.969 and right-only 3.973 — the metric does not discriminate identity here (left-only 11.355 is the only rejected class). Identity rests on the user transcription, the screenshot structure and complete-component provenance; the station paragraph lazily repeats 𠌾 for the variant and cannot arbitrate. Exact donor provenance, frozen outline hash, non-overlap and small-size rendering are mandatory independent checks.',
        },
        'note': 'Two complete native components, five contours, both from plane2 (first case with the radical also external). Left 亻 keeps native coordinates plus a global +5 y shift; the four 𫇮 contours share one affine compressing to the family right-half width. No standard codepoint or donor font is altered.',
    }


def label_font(size):
    for path in ('/System/Library/Fonts/PingFang.ttc',
                 '/System/Library/Fonts/Supplemental/Arial Unicode.ttf'):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _hijack(font0, cp, item):
    name = font0.getBestCmap().get(cp) or f'uni{cp:04X}'
    font0['glyf'][name] = item
    if name not in font0.getGlyphOrder():
        font0.setGlyphOrder(font0.getGlyphOrder() + [name])
    for table in font0['cmap'].tables:
        if table.isUnicode() and table.format in (4, 12):
            table.cmap[cp] = name
    font0['maxp'].numGlyphs = len(font0.getGlyphOrder())
    font0['hmtx'][name] = (1024, item.xMin)
    font0['vmtx'][name] = (1024, 870 - item.yMax)
    font0['hhea'].numberOfHMetrics = len(font0['hmtx'].metrics)
    font0['vhea'].numberOfVMetrics = len(font0['vmtx'].metrics)


def calibrate(font0, font2, glyph):
    """Record the scan metric's limits without changing production fonts."""
    from guji_pua_patch import norm_ink, chamfer
    left = contours(font2, '𠌾')[1]
    right = contours(font2, '𫇮')
    left_pen, right_pen = TTGlyphPen(font0.getGlyphSet()), TTGlyphPen(font0.getGlyphSet())
    left.replay(left_pen)
    for i in [0, 1, 2, 3]:
        right[i].replay(right_pen)
    left_item, right_item = left_pen.glyph(), right_pen.glyph()
    for it in (left_item, right_item):
        it.recalcBounds(font0['glyf'])
    _hijack(font0, 0xE702, glyph)
    _hijack(font0, 0x4EBA, left_item)
    _hijack(font0, 0x4E00, right_item)
    blob = BytesIO()
    font0.save(blob)
    face = ImageFont.truetype(BytesIO(blob.getvalue()), 220)
    donor_face = ImageFont.truetype(str(FONT2), 220)
    mask_path = ROOT/'tools/dataset/font-sources/e712-scan-mask.png'
    mask = norm_ink(np.asarray(Image.open(mask_path).convert('L')) < 128)
    scores = {}
    for label, cp, f in [('composition', 0xE702, face), ('left-only', 0x4EBA, face),
                         ('right-only', 0x4E00, face), ('wrong-莪-𠌾', 0x2033E, donor_face),
                         ('yi-alone-plane2', 0x2B1EE, donor_face)]:
        image = Image.new('L', (440, 440), 255)
        ImageDraw.Draw(image).text((44, 44), chr(cp), font=f, fill=0)
        scores[label] = float(chamfer(norm_ink(np.asarray(image) < 128), mask))
    output = ROOT/'docs/research/evidence/e712/chamfer-calibration.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
        'method': 'norm_ink128 and PIL220 at (44,44), matching patcher; temporary diagnostic slots in memory only',
        'input': str(mask_path.relative_to(ROOT)),
        'input_sha256': hashlib.sha256(mask_path.read_bytes()).hexdigest(),
        'provisional_gate': 4.5, 'scores': scores,
        'glyph_sha256': hashlib.sha256(glyph.compile(font0['glyf'])).hexdigest(),
        'decision': 'As in E711 the woodblock draws a short 亻 while the donor radical is full-height; the composition keeps the donor as-is per the user instruction and the stylistic gap is documented, not hidden. Identity rests on the user transcription, the screenshot structure (亻 + sheep-over-我 component) and the complete-component provenance; the station paragraph lazily repeats 𠌾 for the variant and cannot arbitrate here.',
    }, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(scores, ensure_ascii=False))


def preview(font0, glyph, parts):
    FIGURES.mkdir(parents=True, exist_ok=True)
    name = font0.getBestCmap().get(0xE712)
    if name is not None:
        if font0['glyf'][name].compile(font0['glyf']) != glyph.compile(font0['glyf']):
            raise ValueError('Production E712 differs from rebuilt composition')
        font_bytes = FONT0.read_bytes()
    else:
        name = 'uniE712'
        _hijack(font0, 0xE712, glyph)
        blob = BytesIO()
        font0.save(blob)
        font_bytes = blob.getvalue()
    face = ImageFont.truetype(BytesIO(font_bytes), 212)
    donor_face = ImageFont.truetype(str(FONT2), 212)
    image = Image.new('RGB', (1080, 340), '#f8f6f1')
    draw = ImageDraw.Draw(image)
    for i, label in enumerate(['512 页原刻', 'U+2033E（取亻）', 'U+2B1EE（取整字）', '组合 U+E712']):
        draw.text((135+i*270, 28), label, font=label_font(19), fill='#222', anchor='mm')
    scan = Image.open(SCAN).convert('RGB')
    scan.thumbnail((242, 242))
    scan = scan.resize((242, round(scan.height*242/scan.width)))
    image.paste(scan, (14, 70+(242-scan.height)//2))
    draw.text((405, 185), '𠌾', font=donor_face, fill='#222', anchor='mm')
    draw.text((675, 185), '𫇮', font=donor_face, fill='#222', anchor='mm')
    draw.text((945, 185), '\ue712', font=face, fill='#222', anchor='mm')
    image.save(FIGURES/'result-comparison.png')
    small = Image.new('RGB', (1030, 400), '#f8f6f1')
    d = ImageDraw.Draw(small)
    d.text((25, 18), 'U+E712：16 / 24 / 32 / 48 px，横排与竖排', font=label_font(22), fill='#222')
    for i, size in enumerate([16, 24, 32, 48]):
        f = ImageFont.truetype(BytesIO(font_bytes), size)
        x = 25+i*235
        d.text((x, 67), f'{size}px', font=label_font(18), fill='#555')
        d.text((x, 108), '作\ue712。', font=f, fill='#222')
        for j, c in enumerate('作\ue712。'):
            d.text((x+55, 185+j*size), c, font=f, fill='#222')
    small.save(FIGURES/'small-text-context.png')
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><g transform="matrix(1 0 0 -1 0 870)">'
    svg += ''.join(f'<path d="{p["path"]}" fill="{p["color"]}"/>' for p in parts)
    (FIGURES/'components.svg').write_text(svg+'</g></svg>\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-recipe', action='store_true')
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--calibrate', action='store_true')
    args = parser.parse_args()
    with TTFont(FONT0, recalcTimestamp=False) as font0, TTFont(FONT2, recalcTimestamp=False) as font2:
        recipe = make_recipe(font0, font2)
        if args.write_recipe:
            RECIPE.write_text(json.dumps(recipe, ensure_ascii=False, indent=2)+'\n')
        elif json.loads(RECIPE.read_text()) != recipe:
            raise SystemExit('Rebuilt recipe differs from frozen data')
        glyph, parts = build(font0, font2)
        print(json.dumps({'digest': recipe['approved_glyph']['compiled_sha256'],
                          'contours': glyph.numberOfContours, 'points': len(glyph.coordinates),
                          'metrics': recipe['metrics'], 'components': [
                              {k: p[k] for k in ('contours', 'source_bounds', 'bounds', 'transform')}
                              for p in parts]}, ensure_ascii=False))
        if args.preview:
            preview(font0, glyph, parts)
        if args.calibrate:
            calibrate(font0, font2, glyph)


if __name__ == '__main__':
    main()
