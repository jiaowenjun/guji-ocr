#!/usr/bin/env python3
"""Rebuild U+E708 ⿰彳𢾕 from complete small-font components.

Default checks the frozen recipe without writing a font. --write-recipe writes
the authoring JSON; production insertion uses guji_pua_patch.py. --preview renders
production bytes after insertion or an in-memory diagnostic font before it.
--calibrate records scan-distance controls. Neither option writes a font file.
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
RECIPE = ROOT / 'tools/dataset/font-sources/e708-songti-v1.json'
SCAN = ROOT / 'tools/dataset/font-sources/e708-scan-original.png'
FIGURES = ROOT / 'docs/research/figures/e708'
DONOR_HASHES = {
    '2255F': '72a8fb9579a67b1f3327adac28289931acc759aa65b553f087d089b3b5b24b19',
    '22F95': 'd4306ed8420e81e7ebe497f404b7771acc6db7d4f93f9133d867c67705d31ac5',
}


def build(font, donor):
    if font['head'].unitsPerEm != 1024 or donor['head'].unitsPerEm != 1024:
        raise ValueError('Expected 1024-unit Songti fonts')
    for cp, expected in DONOR_HASHES.items():
        name = donor.getBestCmap()[int(cp, 16)]
        if hashlib.sha256(donor['glyf'][name].compile(donor['glyf'])).hexdigest() != expected:
            raise ValueError(f'Donor U+{cp} changed; review the source contours')
    parts, pen = [], TTGlyphPen(font.getGlyphSet())
    for char, indices, target, role, color in [
        ('𢕟', [2, 4], None, '左彳（𢕟的完整双人旁）', '#2563a6'),
        ('𢾕', [0, 1, 2, 3], (304, -125, 1010, 848), '右𢾕（整字四轮廓）', '#258054'),
    ]:
        source = RecordingPen()
        outlines = contours(donor, char)
        if len(outlines) != (5 if char == '𢕟' else 4):
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
            'source_font': 'guji-plane2.ttf', 'contours': indices, 'role': role,
            'color': color, 'source_bounds': list(bbox(source)),
            'bounds': list(bbox(result)), 'transform': list(transform),
            'extraction': 'complete contours; one positive affine transform per component; no trimming, mirroring, redrawing or union',
            'source_path': src.getCommands(), 'path': dst.getCommands(),
        })
    gap = parts[1]['bounds'][0] - parts[0]['bounds'][2]
    if gap < 16:
        raise ValueError('Insufficient component separation')
    glyph = pen.glyph()
    glyph.recalcBounds(font['glyf'])
    return glyph, parts


def make_recipe(font, donor):
    glyph, parts = build(font, donor)
    return {
        'schema': 2, 'scheme': 'compose',
        'construction': 'left-component-of-u2255f-and-whole-u22f95',
        'description': 'U+E708：康熙 @504 傲条「本作〈彳𢾕〉」；仅小字，完整构形不得用𢾕或𢕟代替。',
        'units_per_em': 1024, 'font': 'guji-plane0.ttf',
        'generator': 'tools/dataset/guji_chi_22f95_components.py',
        'scan_source': 'tools/dataset/font-sources/e708-scan-original.png',
        'descriptive_ids': '⿰彳𢾕',
        'unicode_status': 'independent-codepoint-not-confirmed',
        'donor_glyph_sha256': {},
        'external_donors': [{
            'font': 'guji-preview-grid/public/fonts/guji-plane2.ttf',
            'font_sha256': hashlib.sha256(FONT2.read_bytes()).hexdigest(),
            'glyph_sha256': DONOR_HASHES,
        }],
        'components': parts,
        'approved_glyph': {
            'number_of_contours': glyph.numberOfContours,
            'coordinates': [list(p) for p in glyph.coordinates],
            'end_points': list(glyph.endPtsOfContours), 'flags': list(glyph.flags),
            'instructions': list(glyph.program.getBytecode()),
            'compiled_sha256': hashlib.sha256(glyph.compile(font['glyf'])).hexdigest(),
        },
        'metrics': {'hmtx': [1024, glyph.xMin], 'vmtx': [1024, 870 - glyph.yMax]},
        'verification': {
            'max_chamfer': 3.8,
            'min_component_gap_units': 16,
            'note': 'Initial provisional gate 3.0 rejected this native Songti composition. Calibration records wrong-right-敖 also scoring better than the target, so 3.8 is only a weak scan regression guard. Exact donor provenance, frozen outline hash, non-overlap and small-size rendering are mandatory independent checks.',
        },
        'note': 'Two complete native components, six contours. Left 彳 retains its native coordinates; all four contours of 𢾕 share one affine transform. No standard codepoint or donor font is altered.',
    }


def label_font(size):
    for path in ('/System/Library/Fonts/PingFang.ttc',
                 '/System/Library/Fonts/Supplemental/Arial Unicode.ttf'):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def calibrate(font, donor, glyph):
    """Record the scan metric's limits without changing production fonts."""
    from guji_pua_patch import norm_ink, chamfer
    slots = {'composition': 0x50B2, 'left-only': 0x4EBA, 'right-only': 0x4E01}
    for label, cp in slots.items():
        name = font.getBestCmap()[cp]
        if label == 'composition':
            item = glyph
        elif label == 'right-only':
            item = donor['glyf'][donor.getBestCmap()[0x22F95]]
        else:
            pen = TTGlyphPen(font.getGlyphSet())
            for index in [2, 4]:
                contours(donor, '𢕟')[index].replay(pen)
            item = pen.glyph()
            item.recalcBounds(font['glyf'])
        font['glyf'][name] = item
        font['hmtx'][name] = (1024, item.xMin)
    blob = BytesIO()
    font.save(blob)
    face = ImageFont.truetype(BytesIO(blob.getvalue()), 220)
    donor_face = ImageFont.truetype(str(FONT2), 220)
    mask_path = ROOT/'tools/dataset/font-sources/e708-scan-mask.png'
    mask = norm_ink(np.asarray(Image.open(mask_path).convert('L')) < 128)
    scores = {}
    for label, cp, f in [(k, v, face) for k, v in slots.items()] + [('wrong-right-敖', 0x2255F, donor_face)]:
        image = Image.new('L', (440, 440), 255)
        ImageDraw.Draw(image).text((44, 44), chr(cp), font=f, fill=0)
        scores[label] = float(chamfer(norm_ink(np.asarray(image) < 128), mask))
    output = ROOT/'docs/research/evidence/e708/chamfer-calibration.json'
    output.write_text(json.dumps({
        'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
        'method': 'norm_ink128 and PIL220 at (44,44), matching patcher; temporary diagnostic slots in memory only',
        'input': str(mask_path.relative_to(ROOT)),
        'input_sha256': hashlib.sha256(mask_path.read_bytes()).hexdigest(),
        'initial_gate': 3.0, 'final_weak_regression_gate': 3.8, 'scores': scores,
        'glyph_sha256': hashlib.sha256(glyph.compile(font['glyf'])).hexdigest(),
        'decision': 'The wrong-right-敖 control also passes, so this metric cannot identify the character. Complete donor contours and byte-exact recipe reconstruction provide the structural gate; no outline was distorted to optimize the scan score.',
    }, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(scores, ensure_ascii=False))


def preview(font, glyph, parts):
    FIGURES.mkdir(parents=True, exist_ok=True)
    # Use production bytes after insertion; otherwise render an in-memory font.
    name = font.getBestCmap().get(0xE708)
    if name is not None:
        if font['glyf'][name].compile(font['glyf']) != glyph.compile(font['glyf']):
            raise ValueError('Production E708 differs from rebuilt composition')
        font_bytes = FONT0.read_bytes()
    else:
        name = 'uniE708'
        font.setGlyphOrder(font.getGlyphOrder() + [name])
        for table in font['cmap'].tables:
            if table.isUnicode() and table.format in (4, 12):
                table.cmap[0xE708] = name
        font['glyf'][name] = glyph
        font['hmtx'][name] = (1024, glyph.xMin)
        font['vmtx'][name] = (1024, 870 - glyph.yMax)
        blob = BytesIO()
        font.save(blob)
        font_bytes = blob.getvalue()
    face = ImageFont.truetype(BytesIO(font_bytes), 212)
    donor_face = ImageFont.truetype(str(FONT2), 212)
    image = Image.new('RGB', (1080, 340), '#f8f6f1')
    draw = ImageDraw.Draw(image)
    for i, label in enumerate(['504 页原刻', 'U+2255F（取彳）', 'U+22F95（取整字）', '组合 U+E708']):
        draw.text((135+i*270, 28), label, font=label_font(19), fill='#222', anchor='mm')
    scan = Image.open(SCAN).convert('RGB')
    scan.thumbnail((242, 242))
    scan = scan.resize((242, round(scan.height*242/scan.width)))
    image.paste(scan, (14, 70+(242-scan.height)//2))
    for i, c in [(1, '𢕟'), (2, '𢾕')]:
        draw.text((135+i*270, 185), c, font=donor_face, fill='#222', anchor='mm')
    draw.text((945, 185), '\ue708', font=face, fill='#222', anchor='mm')
    image.save(FIGURES/'result-comparison.png')
    small = Image.new('RGB', (1030, 400), '#f8f6f1')
    d = ImageDraw.Draw(small)
    d.text((25, 18), 'U+E708：16 / 24 / 32 / 48 px，横排与竖排', font=label_font(22), fill='#222')
    for i, size in enumerate([16, 24, 32, 48]):
        f = ImageFont.truetype(BytesIO(font_bytes), size)
        x = 25+i*235
        d.text((x, 67), f'{size}px', font=label_font(18), fill='#555')
        d.text((x, 108), '本作\ue708。', font=f, fill='#222')
        for j, c in enumerate('本作\ue708。'):
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
    with TTFont(FONT0, recalcTimestamp=False) as font, TTFont(FONT2, recalcTimestamp=False) as donor:
        recipe = make_recipe(font, donor)
        if args.write_recipe:
            RECIPE.write_text(json.dumps(recipe, ensure_ascii=False, indent=2)+'\n')
        elif json.loads(RECIPE.read_text()) != recipe:
            raise SystemExit('Rebuilt recipe differs from frozen data')
        glyph, parts = build(font, donor)
        print(json.dumps({'digest': recipe['approved_glyph']['compiled_sha256'],
                          'contours': glyph.numberOfContours, 'points': len(glyph.coordinates),
                          'metrics': recipe['metrics'], 'components': [
                              {k: p[k] for k in ('contours', 'source_bounds', 'bounds', 'transform')}
                              for p in parts]}, ensure_ascii=False))
        if args.preview:
            preview(font, glyph, parts)
        if args.calibrate:
            calibrate(font, donor, glyph)


if __name__ == '__main__':
    main()
