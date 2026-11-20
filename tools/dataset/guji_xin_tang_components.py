#!/usr/bin/env python3
"""Rebuild U+E713 ⿰忄棠 from complete small-font components.

Default checks the frozen recipe without writing a font. --write-recipe writes
the authoring JSON; production insertion uses guji_pua_patch.py. --preview renders
production bytes after insertion or an in-memory diagnostic font before it.
--calibrate records scan-distance controls, including the sibling 惝 (⿰忄尚)
whose native plane0 glyph doubles as the wrong-right confusable. Neither option
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
RECIPE = ROOT / 'tools/dataset/font-sources/e713-songti-v1.json'
SCAN = ROOT / 'tools/dataset/font-sources/e713-scan-original.png'
FIGURES = ROOT / 'docs/research/figures/e713'
# Both donors live in the target font: 忄 from 惝, the 棠 component from 㒉.
DONOR_INTERNAL = {
    '60DD': '6a138848d3cf3c872d21eeb14e796d914f4b650fda5bbc98a2c3c10c97e10c48',
    '3489': '22a946df86334b1629f5704e755d49fdd6dadbf27ccca836d76c897822829383',
}
# The 棠 component keeps its band compressed to the family right-half width;
# its y span lands on [-127, 848], which supplies the anchor vertical origin
# without any global shift (the native 忄 tops out at 840).
RIGHT_TARGET = (406.0, -127.0, 1010.0, 848.0)


def verify_donors(font0):
    if font0['head'].unitsPerEm != 1024:
        raise ValueError('Expected 1024-unit Songti fonts')
    cmap = font0.getBestCmap()
    for cp, expected in DONOR_INTERNAL.items():
        name = cmap[int(cp, 16)]
        if hashlib.sha256(font0['glyf'][name].compile(font0['glyf'])).hexdigest() != expected:
            raise ValueError(f'Donor U+{cp} changed; review the source contours')


def build(font0):
    verify_donors(font0)
    parts, pen = [], TTGlyphPen(font0.getGlyphSet())
    plan = [
        ('惝', [2, 6, 7], None, '左忄（惝的完整竖心旁：竖＋左右点）', '#2563a6'),
        ('㒉', [0, 1, 3, 4, 5], RIGHT_TARGET, '右棠（㒉的完整右部五轮廓：尚框＋口＋木）', '#258054'),
    ]
    for char, indices, target, role, color in plan:
        source = RecordingPen()
        outlines = contours(font0, char)
        if len(outlines) != (8 if char == '惝' else 6):
            raise ValueError('Donor contour inventory changed')
        for i in indices:
            outlines[i].replay(source)
        transform = Transform() if target is None else in_box(source, target)
        if transform.xx * transform.yy - transform.xy * transform.yx <= 0:
            raise ValueError('Reflected source component')
        result = moved(source, transform)
        result.replay(pen)
        src, dst = SVGPathPen(None), SVGPathPen(None)
        source.replay(src)
        result.replay(dst)
        parts.append({
            'source_char': char, 'codepoint': f'U+{ord(char):X}',
            'source_font': 'guji-plane0.ttf', 'contours': indices, 'role': role,
            'color': color, 'source_bounds': list(bbox(source)),
            'bounds': list(bbox(result)), 'transform': list(transform),
            'extraction': 'complete contours; one positive affine per component (right keeps y band, x compressed to the family width); no trimming, mirroring, redrawing or union',
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


def make_recipe(font0):
    glyph, parts = build(font0)
    return {
        'schema': 2, 'scheme': 'compose',
        'construction': 'left-component-of-u60dd-and-right-component-of-u3489',
        'description': 'U+E713：康熙 @519 㒉条「同惝。或作〈忄棠〉。」；仅小字，完整构形不得用惝、㒉或棠整字代替。',
        'units_per_em': 1024, 'font': 'guji-plane0.ttf',
        'generator': 'tools/dataset/guji_xin_tang_components.py',
        'scan_source': 'tools/dataset/font-sources/e713-scan-original.png',
        'descriptive_ids': '⿰忄棠',
        'unicode_status': 'independent-codepoint-not-confirmed',
        'unicode_note': 'CHISE 无 ⿰忄棠 已编码字；惝 U+60DD 是 ⿰忄尚、㒉 U+3489 是 ⿰亻棠，右部互不相同。站方与金标均以真实字符〈忄棠〉描述式转写。',
        'donor_glyph_sha256': dict(DONOR_INTERNAL),
        'external_donors': [],
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
            'max_chamfer': 2.7,
            'min_component_gap_units': 16,
            'note': 'Crisp screenshot makes the metric discriminative like E710: composition 2.516 clearly beats the wrong-right sibling 惝 (⿰忄尚, 2.864), standalone 棠 (3.130), right-only (3.334) and left-only (9.187). Gate 2.7 sits between the composition and the closest confusable. Exact donor provenance, frozen outline hash, non-overlap and small-size rendering remain mandatory independent checks.',
        },
        'note': 'Two complete native components, eight contours, both from plane0 donors. 忄 keeps native coordinates; the five 棠 contours of 㒉 share one affine into the family right half, supplying yMax 848 without a global shift. No standard codepoint or donor font is altered.',
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


def calibrate(font0, glyph):
    """Record the scan metric's limits without changing production fonts."""
    from guji_pua_patch import norm_ink, chamfer
    left_pen, right_pen = TTGlyphPen(font0.getGlyphSet()), TTGlyphPen(font0.getGlyphSet())
    for i in [2, 6, 7]:
        contours(font0, '惝')[i].replay(left_pen)
    for i in [0, 1, 3, 4, 5]:
        contours(font0, '㒉')[i].replay(right_pen)
    left_item, right_item = left_pen.glyph(), right_pen.glyph()
    for it in (left_item, right_item):
        it.recalcBounds(font0['glyf'])
    _hijack(font0, 0xE702, glyph)
    _hijack(font0, 0x5FC4, left_item)
    _hijack(font0, 0x4E00, right_item)
    blob = BytesIO()
    font0.save(blob)
    face = ImageFont.truetype(BytesIO(blob.getvalue()), 220)
    mask_path = ROOT/'tools/dataset/font-sources/e713-scan-mask.png'
    mask = norm_ink(np.asarray(Image.open(mask_path).convert('L')) < 128)
    scores = {}
    for label, cp in [('composition', 0xE702), ('left-only', 0x5FC4), ('right-only', 0x4E00),
                      ('wrong-尚-惝', 0x60DD), ('tang-standalone', 0x68E0)]:
        image = Image.new('L', (440, 440), 255)
        ImageDraw.Draw(image).text((44, 44), chr(cp), font=face, fill=0)
        scores[label] = float(chamfer(norm_ink(np.asarray(image) < 128), mask))
    output = ROOT/'docs/research/evidence/e713/chamfer-calibration.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
        'method': 'norm_ink128 and PIL220 at (44,44), matching patcher; temporary diagnostic slots in memory only',
        'input': str(mask_path.relative_to(ROOT)),
        'input_sha256': hashlib.sha256(mask_path.read_bytes()).hexdigest(),
        'provisional_gate': 4.0, 'scores': scores,
        'glyph_sha256': hashlib.sha256(glyph.compile(font0['glyf'])).hexdigest(),
        'decision': 'Crisp screenshot: the composition should beat the wrong-right sibling 惝 (⿰忄尚) and the standalone 棠. Identity rests on the site paragraph 〈忄棠〉 (real-component transcription), the user transcription and complete-component provenance.',
    }, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(scores, ensure_ascii=False))


def preview(font0, glyph, parts):
    FIGURES.mkdir(parents=True, exist_ok=True)
    name = font0.getBestCmap().get(0xE713)
    if name is not None:
        if font0['glyf'][name].compile(font0['glyf']) != glyph.compile(font0['glyf']):
            raise ValueError('Production E713 differs from rebuilt composition')
        font_bytes = FONT0.read_bytes()
    else:
        name = 'uniE713'
        _hijack(font0, 0xE713, glyph)
        blob = BytesIO()
        font0.save(blob)
        font_bytes = blob.getvalue()
    face = ImageFont.truetype(BytesIO(font_bytes), 212)
    image = Image.new('RGB', (1080, 340), '#f8f6f1')
    draw = ImageDraw.Draw(image)
    for i, label in enumerate(['519 页原刻', 'U+60DD（取忄）', 'U+3489（取棠部）', '组合 U+E713']):
        draw.text((135+i*270, 28), label, font=label_font(19), fill='#222', anchor='mm')
    scan = Image.open(SCAN).convert('RGB')
    scan.thumbnail((242, 242))
    scan = scan.resize((242, round(scan.height*242/scan.width)))
    image.paste(scan, (14, 70+(242-scan.height)//2))
    draw.text((405, 185), '惝', font=face, fill='#222', anchor='mm')
    draw.text((675, 185), '㒉', font=face, fill='#222', anchor='mm')
    draw.text((945, 185), '\ue713', font=face, fill='#222', anchor='mm')
    image.save(FIGURES/'result-comparison.png')
    small = Image.new('RGB', (1030, 400), '#f8f6f1')
    d = ImageDraw.Draw(small)
    d.text((25, 18), 'U+E713：16 / 24 / 32 / 48 px，横排与竖排', font=label_font(22), fill='#222')
    for i, size in enumerate([16, 24, 32, 48]):
        f = ImageFont.truetype(BytesIO(font_bytes), size)
        x = 25+i*235
        d.text((x, 67), f'{size}px', font=label_font(18), fill='#555')
        d.text((x, 108), '作\ue713。', font=f, fill='#222')
        for j, c in enumerate('作\ue713。'):
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
    with TTFont(FONT0, recalcTimestamp=False) as font0:
        recipe = make_recipe(font0)
        if args.write_recipe:
            RECIPE.write_text(json.dumps(recipe, ensure_ascii=False, indent=2)+'\n')
        elif json.loads(RECIPE.read_text()) != recipe:
            raise SystemExit('Rebuilt recipe differs from frozen data')
        glyph, parts = build(font0)
        print(json.dumps({'digest': recipe['approved_glyph']['compiled_sha256'],
                          'contours': glyph.numberOfContours, 'points': len(glyph.coordinates),
                          'metrics': recipe['metrics'], 'components': [
                              {k: p[k] for k in ('contours', 'source_bounds', 'bounds', 'transform')}
                              for p in parts]}, ensure_ascii=False))
        if args.preview:
            preview(font0, glyph, parts)
        if args.calibrate:
            calibrate(font0, glyph)


if __name__ == '__main__':
    main()
