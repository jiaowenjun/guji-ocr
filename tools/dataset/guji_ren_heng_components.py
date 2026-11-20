#!/usr/bin/env python3
"""Rebuild U+E709 ⿰亻亨 from complete small-font components.

Default checks the frozen recipe without writing a font. --write-recipe writes
the authoring JSON; production insertion uses guji_pua_patch.py. --preview renders
production bytes after insertion or an in-memory diagnostic font before it.
--calibrate records scan-distance controls, including the 停 (⿰亻亭) confusable
that visual models misread the woodblock form as. Neither option writes a font.
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
RECIPE = ROOT / 'tools/dataset/font-sources/e709-songti-v1.json'
SCAN = ROOT / 'tools/dataset/font-sources/e709-scan-original.png'
FIGURES = ROOT / 'docs/research/figures/e709'
# 悙 U+6059 lives in the target font itself; 𠆼 U+201BC is an external donor.
DONOR_INTERNAL = {'6059': '9121288fe52e85733bc1cf47d40fc6a19635e21280f3934dcff7fa8ea6ac0be5'}
DONOR_EXTERNAL = {'201BC': '9267eb1b2c236808074e1ba09e26ae9eca6f720cc1ed6d12faf6da7d919f61cf'}
# 悙's 亨 contours (0,1,3,4,7) leave the 忄 strokes on 2,5,6; shifting by
# (31,-5) aligns their band [-120,853] with the radical's [-125,847] and yields
# yMax 848, matching the anchor vertical origin the patch tool copies.
RIGHT_TARGET = (381, -125, 1017, 848)


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
        ('𠆼', [0], None, '左亻（𠆼的完整单人旁，撇竖连体轮廓）', '#2563a6', font2),
        ('悙', [0, 1, 3, 4, 7], RIGHT_TARGET, '右亨（悙的完整右部五轮廓）', '#258054', font0),
    ]
    for char, indices, target, role, color, donor in plan:
        source = RecordingPen()
        outlines = contours(donor, char)
        if len(outlines) != (4 if char == '𠆼' else 8):
            raise ValueError('Donor contour inventory changed')
        for i in indices:
            outlines[i].replay(source)
        transform = Transform() if target is None else in_box(source, target)
        if transform.xx * transform.yy - transform.xy * transform.yx <= 0:
            raise ValueError('Reflected source component')
        if target is not None and not all(0.98 <= v <= 1.02 for v in (transform.xx, transform.yy)):
            raise ValueError('Right component must stay near-identity in scale')
        result = moved(source, transform)
        result.replay(pen)
        src, dst = SVGPathPen(None), SVGPathPen(None)
        source.replay(src)
        result.replay(dst)
        parts.append({
            'source_char': char, 'codepoint': f'U+{ord(char):X}',
            'source_font': 'guji-plane2.ttf' if donor is font2 else 'guji-plane0.ttf',
            'contours': indices, 'role': role,
            'color': color, 'source_bounds': list(bbox(source)),
            'bounds': list(bbox(result)), 'transform': list(transform),
            'extraction': 'complete contours; one positive near-identity affine per component; no trimming, mirroring, redrawing or union',
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
        'construction': 'left-radical-of-u201bc-and-right-component-of-u6059',
        'description': 'U+E709：康熙 @471 倀条「【集韻】倀〈亻亨〉，疎率也。」；仅小字，完整构形不得用停、悙或亨整字代替。',
        'units_per_em': 1024, 'font': 'guji-plane0.ttf',
        'generator': 'tools/dataset/guji_ren_heng_components.py',
        'scan_source': 'tools/dataset/font-sources/e709-scan-original.png',
        'descriptive_ids': '⿰亻亨',
        'unicode_status': 'independent-codepoint-not-confirmed',
        'unicode_note': 'IRG WS2024 UK-30044（人部九画）证据 2025-11 受理，尚未分配标准码位；若将来编码须回迁正式 cmap。',
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
            'max_chamfer': 7.5,
            'min_component_gap_units': 16,
            'note': 'Weak regression gate only. Same-page native controls (倀 6.49, 疎 5.19, 率 7.04) show the raw site scan is anisotropically squeezed (ink aspect 0.55-0.67 vs font ~1.0), so scan distance cannot arbitrate identity on this page: the ⿰亻亭 confusable 停 scores 5.13, inside the true-identity band. Identity rests on the site paragraph 〈亻亨〉, the user transcription and stroke-level review (one horizontal plus hook below the 口, no 冖 layer). Exact donor provenance, frozen outline hash, non-overlap and small-size rendering are mandatory independent checks.',
        },
        'note': 'Two complete native components, six contours. Left 亻 keeps its native plane2 coordinates; the five 亨 contours of 悙 share one near-identity affine (scale within 0.1% of 1) fitting [381,-125,1017,848]. No standard codepoint or donor font is altered.',
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
    from scipy import ndimage
    slots = {'composition': 0xE702, 'left-only': 0x4EBA, 'right-only': 0x4EA8}
    for label, cp in slots.items():
        name = font0.getBestCmap().get(cp) or f'uni{cp:04X}'
        if label == 'composition':
            item = glyph
        elif label == 'left-only':
            pen = TTGlyphPen(font0.getGlyphSet())
            contours(font2, '𠆼')[0].replay(pen)
            item = pen.glyph()
            item.recalcBounds(font0['glyf'])
        else:
            pen = TTGlyphPen(font0.getGlyphSet())
            for index in [0, 1, 3, 4, 7]:
                contours(font0, '悙')[index].replay(pen)
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
        # Without these the compiled metric tables truncate and the appended
        # slot renders blank.
        font0['hhea'].numberOfHMetrics = len(font0['hmtx'].metrics)
        font0['vhea'].numberOfVMetrics = len(font0['vmtx'].metrics)
    blob = BytesIO()
    font0.save(blob)
    face = ImageFont.truetype(BytesIO(blob.getvalue()), 220)
    mask_path = ROOT/'tools/dataset/font-sources/e709-scan-mask.png'
    mask = norm_ink(np.asarray(Image.open(mask_path).convert('L')) < 128)
    scores = {}
    for label, cp in list(slots.items()) + [('wrong-亭-停', 0x505C), ('wrong-radical-悙', 0x6059)]:
        image = Image.new('L', (440, 440), 255)
        ImageDraw.Draw(image).text((44, 44), chr(cp), font=face, fill=0)
        scores[label] = float(chamfer(norm_ink(np.asarray(image) < 128), mask))
    # Uncontested neighbours on the same squeezed scan establish the band a
    # true identity scores in on this page; without this control the metric
    # would fake precision it does not have.
    page = Image.open('/Volumes/WD-2T/guji-ocr/raw/kangxizidian/pages/0471.jpg')
    controls = {}
    for label, y0, y1, cp in [('倀-own-scan', 608, 690, 0x5000),
                              ('疎-own-scan', 720, 792, 0x758E),
                              ('率-own-scan', 788, 858, 0x7387)]:
        raw = np.asarray(page.crop((102, y0, 151, y1)).convert('L')) < 120
        lbl, _ = ndimage.label(raw)
        counts = np.bincount(lbl.ravel())
        keep = counts >= 8
        keep[0] = False
        sm = norm_ink(keep[lbl])
        image = Image.new('L', (440, 440), 255)
        ImageDraw.Draw(image).text((44, 44), chr(cp), font=face, fill=0)
        controls[label] = float(chamfer(norm_ink(np.asarray(image) < 128), sm))
    output = ROOT/'docs/research/evidence/e709/chamfer-calibration.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
        'method': 'norm_ink128 and PIL220 at (44,44), matching patcher; temporary diagnostic slots in memory only',
        'input': str(mask_path.relative_to(ROOT)),
        'input_sha256': hashlib.sha256(mask_path.read_bytes()).hexdigest(),
        'final_weak_regression_gate': 7.5, 'scores': scores,
        'same_page_true_identity_band': controls,
        'glyph_sha256': hashlib.sha256(glyph.compile(font0['glyf'])).hexdigest(),
        'decision': 'The raw page scan is anisotropically squeezed (neighbour ink aspect 0.55-0.67 vs font ~1.0), so scan distance cannot arbitrate identity here: the composition (6.41) sits inside the true-identity band (5.19-7.04) and the ⿰亻亭 confusable 停 (5.13) also falls within it. Identity rests on the site paragraph 〈亻亨〉, the user transcription and stroke-level review (one horizontal plus hook below the 口, no 冖 layer); visual models produced three different readings of the same crop. The 7.5 gate only rejects gross geometric regression.',
    }, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({**scores, **controls}, ensure_ascii=False))


def preview(font0, glyph, parts):
    FIGURES.mkdir(parents=True, exist_ok=True)
    # Use production bytes after insertion; otherwise render an in-memory font.
    name = font0.getBestCmap().get(0xE709)
    if name is not None:
        if font0['glyf'][name].compile(font0['glyf']) != glyph.compile(font0['glyf']):
            raise ValueError('Production E709 differs from rebuilt composition')
        font_bytes = FONT0.read_bytes()
    else:
        name = 'uniE709'
        font0.setGlyphOrder(font0.getGlyphOrder() + [name])
        for table in font0['cmap'].tables:
            if table.isUnicode() and table.format in (4, 12):
                table.cmap[0xE709] = name
        font0['glyf'][name] = glyph
        font0['hmtx'][name] = (1024, glyph.xMin)
        font0['vmtx'][name] = (1024, 870 - glyph.yMax)
        font0['maxp'].numGlyphs = len(font0.glyphOrder)
        font0['hhea'].numberOfHMetrics = len(font0['hmtx'].metrics)
        font0['vhea'].numberOfVMetrics = len(font0['vmtx'].metrics)
        blob = BytesIO()
        font0.save(blob)
        font_bytes = blob.getvalue()
    face = ImageFont.truetype(BytesIO(font_bytes), 212)
    donor_face = ImageFont.truetype(str(FONT2), 212)
    image = Image.new('RGB', (1080, 340), '#f8f6f1')
    draw = ImageDraw.Draw(image)
    for i, label in enumerate(['471 页原刻', 'U+201BC（取亻）', 'U+6059（取亨）', '组合 U+E709']):
        draw.text((135+i*270, 28), label, font=label_font(19), fill='#222', anchor='mm')
    scan = Image.open(SCAN).convert('RGB')
    scan.thumbnail((242, 242))
    scan = scan.resize((242, round(scan.height*242/scan.width)))
    image.paste(scan, (14, 70+(242-scan.height)//2))
    draw.text((405, 185), '𠆼', font=donor_face, fill='#222', anchor='mm')
    draw.text((675, 185), '悙', font=face, fill='#222', anchor='mm')
    draw.text((945, 185), '\ue709', font=face, fill='#222', anchor='mm')
    image.save(FIGURES/'result-comparison.png')
    small = Image.new('RGB', (1030, 400), '#f8f6f1')
    d = ImageDraw.Draw(small)
    d.text((25, 18), 'U+E709：16 / 24 / 32 / 48 px，横排与竖排', font=label_font(22), fill='#222')
    for i, size in enumerate([16, 24, 32, 48]):
        f = ImageFont.truetype(BytesIO(font_bytes), size)
        x = 25+i*235
        d.text((x, 67), f'{size}px', font=label_font(18), fill='#555')
        d.text((x, 108), '倀\ue709，疎率也。', font=f, fill='#222')
        for j, c in enumerate('倀\ue709，疎'):
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
