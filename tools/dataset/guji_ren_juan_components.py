#!/usr/bin/env python3
"""Rebuild U+E711 ⿰亻𠨟 from complete small-font components.

Default checks the frozen recipe without writing a font. --write-recipe writes
the authoring JSON; production insertion uses guji_pua_patch.py. --preview renders
production bytes after insertion or an in-memory diagnostic font before it.
--calibrate records scan-distance controls, including the sibling 倦 (⿰亻卷)
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
FONT2 = ROOT / 'guji-preview-grid/public/fonts/guji-plane2.ttf'
RECIPE = ROOT / 'tools/dataset/font-sources/e711-songti-v1.json'
SCAN = ROOT / 'tools/dataset/font-sources/e711-scan-original.png'
FIGURES = ROOT / 'docs/research/figures/e711'
# Left donor lives in the target font; right donor is external (plane2).
DONOR_INTERNAL = {'5026': 'e50d5b46e4175f548f6df8547de301d7c13902978d12c5f33730ec0f8bd2ec0c'}
DONOR_EXTERNAL = {'20A1F': '631d831305289c7e4892340722f35def246cf23f15016fc53cbdf13bffcce049'}
# The 𠨟 component keeps its native band alignment (bottom -127, top 848 like
# the 倦 radical) while compressing to the family's right-half width; the box
# starts 17 units past the radical's arm tip and ends at the 倦-family extent.
RIGHT_TARGET = (360, -127, 1007, 848)


def verify_donors(font0, font2):
    if font0['head'].unitsPerEm != 1024 or font2['head'].unitsPerEm != 1024:
        raise ValueError('Expected 1024-unit Songti fonts')
    for font, hashes in ((font0, DONOR_INTERNAL), (font2, DONOR_EXTERNAL)):
        cmap = font.getBestCmap()
        for cp, expected in hashes.items():
            name = cmap[int(cp, 16)]
            if hashlib.sha256(font['glyf'][name].compile(font['glyf'])).hexdigest() != expected:
                raise ValueError(f'Donor U+{cp} changed; review the source contours')


def build(font0, font2):
    verify_donors(font0, font2)
    parts, pen = [], TTGlyphPen(font0.getGlyphSet())
    plan = [
        ('倦', [1], None, '左亻（倦的完整单人旁，撇竖连体单轮廓）', '#2563a6', font0),
        ('𠨟', [0, 1, 2], RIGHT_TARGET, '右𠨟（整字三轮廓：龹部框、下框、内点）', '#258054', font2),
    ]
    for char, indices, target, role, color, donor in plan:
        source = RecordingPen()
        outlines = contours(donor, char)
        if len(outlines) != (4 if char == '倦' else 3):
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
            'source_font': 'guji-plane0.ttf' if donor is font0 else 'guji-plane2.ttf',
            'contours': indices, 'role': role,
            'color': color, 'source_bounds': list(bbox(source)),
            'bounds': list(bbox(result)), 'transform': list(transform),
            'extraction': 'complete contours; one positive affine per component; no trimming, mirroring, redrawing or union',
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
        'construction': 'left-radical-of-u5026-and-whole-u20a1f',
        'description': 'U+E711：康熙 @480 倦条按语「人部作〈亻𠨟〉」的說文人部形；仅小字，完整构形不得用倦或𠨟代替。',
        'units_per_em': 1024, 'font': 'guji-plane0.ttf',
        'generator': 'tools/dataset/guji_ren_juan_components.py',
        'scan_source': 'tools/dataset/font-sources/e711-scan-original.png',
        'descriptive_ids': '⿰亻𠨟',
        'unicode_status': 'independent-codepoint-not-confirmed',
        'unicode_note': 'CHISE 无 ⿰亻𠨟 已编码字；𠨟 U+20A1F 自身 IDS 为 ⿵⿱釆大㔾（编码部件）。同条力部形 𠢏 U+2088F 亦在 plane2 在库。',
        'donor_glyph_sha256': dict(DONOR_INTERNAL),
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
            'max_chamfer': 4.0,
            'min_component_gap_units': 16,
            'note': 'Weak regression gate. The woodblock form draws a SHORT 亻 (head ~27% down) while the 倦 donor radical is full-height; the composition keeps the donor as-is per the user instruction, so the metric is dominated by that documented stylistic gap: composition 3.377 vs bare 𠨟 2.321 and wrong-right 倦 (⿰亻卷) 3.311 — none discriminates identity here. The gate only rejects gross breakage (left-only scores 9.763). Identity rests on the site paragraph 〈亻𠨟〉, the user transcription and complete-component provenance. Exact donor provenance, frozen outline hash, non-overlap and small-size rendering are mandatory independent checks.',
        },
        'note': 'Two complete native components, four contours. Left 亻 keeps native plane0 coordinates; the three 𠨟 contours of plane2 share one affine compressing to the family right-half width. No standard codepoint or donor font is altered.',
    }


def label_font(size):
    for path in ('/System/Library/Fonts/PingFang.ttc',
                 '/System/Library/Fonts/Supplemental/Arial Unicode.ttf'):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def calibrate(font0, font2, glyph):
    """Record the scan metric's limits without changing production fonts."""
    from guji_pua_patch import norm_ink, chamfer
    slots = {'composition': 0xE702, 'left-only': 0x4EBA, 'right-only': 0x4E00}
    for label, cp in slots.items():
        name = font0.getBestCmap().get(cp) or f'uni{cp:04X}'
        if label == 'composition':
            item = glyph
        elif label == 'left-only':
            pen = TTGlyphPen(font0.getGlyphSet())
            contours(font0, '倦')[1].replay(pen)
            item = pen.glyph()
            item.recalcBounds(font0['glyf'])
        else:
            pen = TTGlyphPen(font0.getGlyphSet())
            for index in [0, 1, 2]:
                contours(font2, '𠨟')[index].replay(pen)
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
    donor_face = ImageFont.truetype(str(FONT2), 220)
    mask_path = ROOT/'tools/dataset/font-sources/e711-scan-mask.png'
    mask = norm_ink(np.asarray(Image.open(mask_path).convert('L')) < 128)
    scores = {}
    for label, cp, f in ([(k, v, face) for k, v in slots.items()]
                         + [('wrong-卷-倦', 0x5026, face), ('zao-alone-plane2', 0x20A1F, donor_face)]):
        image = Image.new('L', (440, 440), 255)
        ImageDraw.Draw(image).text((44, 44), chr(cp), font=f, fill=0)
        scores[label] = float(chamfer(norm_ink(np.asarray(image) < 128), mask))
    output = ROOT/'docs/research/evidence/e711/chamfer-calibration.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
        'method': 'norm_ink128 and PIL220 at (44,44), matching patcher; temporary diagnostic slots in memory only',
        'input': str(mask_path.relative_to(ROOT)),
        'input_sha256': hashlib.sha256(mask_path.read_bytes()).hexdigest(),
        'provisional_gate': 5.5, 'scores': scores,
        'glyph_sha256': hashlib.sha256(glyph.compile(font0['glyf'])).hexdigest(),
        'decision': 'The woodblock form draws a short 亻 (head ~27% down); the composition keeps the full-height 倦 donor radical per the user instruction, so the composition score carries that documented stylistic gap and is not expected to reach E710-class margins. Identity rests on the site paragraph 〈亻𠨟〉, the user transcription and the complete-component provenance.',
    }, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(scores, ensure_ascii=False))


def preview(font0, glyph, parts):
    FIGURES.mkdir(parents=True, exist_ok=True)
    name = font0.getBestCmap().get(0xE711)
    if name is not None:
        if font0['glyf'][name].compile(font0['glyf']) != glyph.compile(font0['glyf']):
            raise ValueError('Production E711 differs from rebuilt composition')
        font_bytes = FONT0.read_bytes()
    else:
        name = 'uniE711'
        font0.setGlyphOrder(font0.getGlyphOrder() + [name])
        for table in font0['cmap'].tables:
            if table.isUnicode() and table.format in (4, 12):
                table.cmap[0xE711] = name
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
    donor_face = ImageFont.truetype(str(FONT2), 212)
    image = Image.new('RGB', (1080, 340), '#f8f6f1')
    draw = ImageDraw.Draw(image)
    for i, label in enumerate(['480 页原刻', 'U+5026（取亻）', 'U+20A1F（取整字）', '组合 U+E711']):
        draw.text((135+i*270, 28), label, font=label_font(19), fill='#222', anchor='mm')
    scan = Image.open(SCAN).convert('RGB')
    scan.thumbnail((242, 242))
    scan = scan.resize((242, round(scan.height*242/scan.width)))
    image.paste(scan, (14, 70+(242-scan.height)//2))
    draw.text((405, 185), '倦', font=face, fill='#222', anchor='mm')
    draw.text((675, 185), '𠨟', font=donor_face, fill='#222', anchor='mm')
    draw.text((945, 185), '\ue711', font=face, fill='#222', anchor='mm')
    image.save(FIGURES/'result-comparison.png')
    small = Image.new('RGB', (1030, 400), '#f8f6f1')
    d = ImageDraw.Draw(small)
    d.text((25, 18), 'U+E711：16 / 24 / 32 / 48 px，横排与竖排', font=label_font(22), fill='#222')
    for i, size in enumerate([16, 24, 32, 48]):
        f = ImageFont.truetype(BytesIO(font_bytes), size)
        x = 25+i*235
        d.text((x, 67), f'{size}px', font=label_font(18), fill='#555')
        d.text((x, 108), '作\ue711，音', font=f, fill='#222')
        for j, c in enumerate('作\ue711，'):
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
