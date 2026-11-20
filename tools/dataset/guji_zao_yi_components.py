#!/usr/bin/env python3
"""Rebuild U+E710 ⿰𠦝一 from complete small-font components.

Default checks the frozen recipe without writing a font. --write-recipe writes
the authoring JSON; production insertion uses guji_pua_patch.py. --preview renders
production bytes after insertion or an in-memory diagnostic font before it.
--calibrate records scan-distance controls, including the sibling 倝 (⿰𠦝人)
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
RECIPE = ROOT / 'tools/dataset/font-sources/e710-songti-v1.json'
SCAN = ROOT / 'tools/dataset/font-sources/e710-scan-original.png'
FIGURES = ROOT / 'docs/research/figures/e710'
# Both donors live in the target font itself: no external donors this time.
DONOR_INTERNAL = {
    '671D': '7439a3f87d351ca031f70adb39bd0a49d52692f9b49e6ea9baf163501563abec',
    '793A': 'dbaa90466c9630cb2a86fb99237e40922228e972846c6d08bcc9cc09cfbc5674',
}
# The woodblock form starts its 一 where the 十字臂 tips end (plus the
# standard 16-unit gate) and keeps the bar at the 日's upper inner-bar height.
# A global -2 y shift (E708 convention) lands yMax on 848 so the insert
# inherits the anchor vertical origin.
BAR_TARGET = (596.0, 460.5, 1001.0, 539.5)
GLOBAL_SHIFT_Y = -2.0


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
        ('朝', [1, 4, 5], None, '左𠦝（朝的完整左半：连体框＋日内两横）', '#2563a6'),
        ('示', [3], BAR_TARGET, '右一（示的顶部短横）', '#258054'),
    ]
    for char, indices, target, role, color in plan:
        source = RecordingPen()
        outlines = contours(font0, char)
        if len(outlines) != (6 if char == '朝' else 4):
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
            'source_font': 'guji-plane0.ttf', 'contours': indices, 'role': role,
            'color': color, 'source_bounds': list(bbox(source)),
            'bounds': list(bbox(result)), 'transform': list(transform),
            'extraction': 'complete contours; one positive affine per component (bar is x-scaled to the woodblock proportion, y kept; whole composition shifted -2 y to the anchor origin); no trimming, mirroring, redrawing or union',
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
        'construction': 'left-component-of-u671d-and-top-stroke-of-u793a',
        'description': 'U+E710：康熙 @478 倝条「本作〈𠦝一〉」；仅小字，完整构形不得用倝、朝或𠦝代替。',
        'units_per_em': 1024, 'font': 'guji-plane0.ttf',
        'generator': 'tools/dataset/guji_zao_yi_components.py',
        'scan_source': 'tools/dataset/font-sources/e710-scan-original.png',
        'descriptive_ids': '⿰𠦝一',
        'unicode_status': 'independent-codepoint-not-confirmed',
        'unicode_note': 'CHISE 无 ⿰𠦝一 已编码字；倝 U+501D 本身是 ⿰𠦝人，本作形以一代人。站方以〈E854一〉两字符转写（E854=𠦝单字槽），整字亦无码位。',
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
            'max_chamfer': 4.6,
            'min_component_gap_units': 16,
            'note': 'The user screenshot is a crisp site-zoom crop (aspect 0.94 vs composition 0.98), unlike the squeezed raw page of E709, so the metric discriminates: composition 4.09 clearly beats the sibling 倝 ⿰𠦝人 (5.50), 朝 (5.76), left-only 𠦝 (6.16) and right-only 一 (12.84). Gate 4.6 sits between the composition and the closest confusable. Exact donor provenance, frozen outline hash, non-overlap and small-size rendering remain mandatory independent checks.',
        },
        'note': 'Two complete native components, four contours. 𠦝 keeps native plane0 coordinates of 朝 except the global -2 y shift; the 示 top bar is x-scaled to 0.637 (woodblock proportion ~0.71-0.75 of the 𠦝 width) with y preserved, starting 16 units past the 十字臂 tip exactly as the woodblock layout rule. No standard codepoint or donor font is altered.',
    }


def label_font(size):
    for path in ('/System/Library/Fonts/PingFang.ttc',
                 '/System/Library/Fonts/Supplemental/Arial Unicode.ttf'):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def calibrate(font0, glyph):
    """Record the scan metric's limits without changing production fonts."""
    from guji_pua_patch import norm_ink, chamfer
    slots = {'composition': 0xE702, 'left-only': 0x4EBA, 'right-only': 0x4E00}
    for label, cp in slots.items():
        name = font0.getBestCmap().get(cp) or f'uni{cp:04X}'
        if label == 'composition':
            item = glyph
        elif label == 'left-only':
            pen = TTGlyphPen(font0.getGlyphSet())
            for index in [1, 4, 5]:
                contours(font0, '朝')[index].replay(pen)
            item = pen.glyph()
            item.recalcBounds(font0['glyf'])
        else:
            pen = TTGlyphPen(font0.getGlyphSet())
            contours(font0, '示')[3].replay(pen)
            item = pen.glyph()
            item.recalcBounds(font0['glyf'])
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
    blob = BytesIO()
    font0.save(blob)
    face = ImageFont.truetype(BytesIO(blob.getvalue()), 220)
    mask_path = ROOT/'tools/dataset/font-sources/e710-scan-mask.png'
    mask = norm_ink(np.asarray(Image.open(mask_path).convert('L')) < 128)
    scores = {}
    for label, cp in list(slots.items()) + [('wrong-人-倝', 0x501D), ('wrong-月-朝', 0x671D)]:
        image = Image.new('L', (440, 440), 255)
        ImageDraw.Draw(image).text((44, 44), chr(cp), font=face, fill=0)
        scores[label] = float(chamfer(norm_ink(np.asarray(image) < 128), mask))
    output = ROOT/'docs/research/evidence/e710/chamfer-calibration.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
        'method': 'norm_ink128 and PIL220 at (44,44), matching patcher; temporary diagnostic slots in memory only',
        'input': str(mask_path.relative_to(ROOT)),
        'input_sha256': hashlib.sha256(mask_path.read_bytes()).hexdigest(),
        'provisional_gate': 3.5, 'scores': scores,
        'glyph_sha256': hashlib.sha256(glyph.compile(font0['glyf'])).hexdigest(),
        'decision': 'The mask is a crisp site-zoom screenshot (ink aspect 0.94 vs composition 0.98), so unlike E709 the scan distance should discriminate: the composition must clearly beat the wrong-right siblings 倝/朝. Identity still rests on the site paragraph 〈E854一〉, the user transcription and stroke-level review.',
    }, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(scores, ensure_ascii=False))


def preview(font0, glyph, parts):
    FIGURES.mkdir(parents=True, exist_ok=True)
    name = font0.getBestCmap().get(0xE710)
    if name is not None:
        if font0['glyf'][name].compile(font0['glyf']) != glyph.compile(font0['glyf']):
            raise ValueError('Production E710 differs from rebuilt composition')
        font_bytes = FONT0.read_bytes()
    else:
        name = 'uniE710'
        font0.setGlyphOrder(font0.getGlyphOrder() + [name])
        for table in font0['cmap'].tables:
            if table.isUnicode() and table.format in (4, 12):
                table.cmap[0xE710] = name
        font0['glyf'][name] = glyph
        font0['hmtx'][name] = (1024, glyph.xMin)
        font0['vmtx'][name] = (1024, 870 - glyph.yMax)
        font0['maxp'].numGlyphs = len(font0.getGlyphOrder())
        font0['hhea'].numberOfHMetrics = len(font0['hmtx'].metrics)
        font0['vhea'].numberOfVMetrics = len(font0['vmtx'].metrics)
        blob = BytesIO()
        font0.save(blob)
        font_bytes = blob.getvalue()
    face = ImageFont.truetype(BytesIO(font_bytes), 212)
    image = Image.new('RGB', (1080, 340), '#f8f6f1')
    draw = ImageDraw.Draw(image)
    for i, label in enumerate(['478 页原刻', 'U+671D（取𠦝）', 'U+793A（取顶横）', '组合 U+E710']):
        draw.text((135+i*270, 28), label, font=label_font(19), fill='#222', anchor='mm')
    scan = Image.open(SCAN).convert('RGB')
    scan.thumbnail((242, 242))
    scan = scan.resize((242, round(scan.height*242/scan.width)))
    image.paste(scan, (14, 70+(242-scan.height)//2))
    draw.text((405, 185), '朝', font=face, fill='#222', anchor='mm')
    draw.text((675, 185), '示', font=face, fill='#222', anchor='mm')
    draw.text((945, 185), '\ue710', font=face, fill='#222', anchor='mm')
    image.save(FIGURES/'result-comparison.png')
    small = Image.new('RGB', (1030, 400), '#f8f6f1')
    d = ImageDraw.Draw(small)
    d.text((25, 18), 'U+E710：16 / 24 / 32 / 48 px，横排与竖排', font=label_font(22), fill='#222')
    for i, size in enumerate([16, 24, 32, 48]):
        f = ImageFont.truetype(BytesIO(font_bytes), size)
        x = 25+i*235
        d.text((x, 67), f'{size}px', font=label_font(18), fill='#555')
        d.text((x, 108), '本作\ue710，俗', font=f, fill='#222')
        for j, c in enumerate('本作\ue710，'):
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
