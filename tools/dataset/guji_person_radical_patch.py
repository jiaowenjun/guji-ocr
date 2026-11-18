#!/usr/bin/env python3
"""Reproduce @398's scan-derived U+2E85 outline; dry-run unless --apply.

The SVG stays in screenshot coordinates. Fit its height to 人, preserve its
aspect ratio, and center the ink in a 1024-unit advance. Never update system
fonts or the small-font family. See docs/research/2026-11-18-U+2E85补录报告.md.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
from fontTools.misc.transform import Transform
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import parse_path
from fontTools.ttLib import TTFont

from guji_pua_patch import patch_font, verify_addition, sha256
from kangxi_font_patch import chamfer, norm_ink, path_bounds, svg_path_d

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'tools/dataset/font-sources/0398-person-radical'
EVIDENCE = ROOT / 'docs/research/evidence/0398-person-radical'
FIGURES = ROOT / 'docs/research/figures/0398-person-radical'
FONT = ROOT / 'guji-preview-grid/public/fonts/guji-large.ttf'
CP = 0x2E85
BASELINE = '99be6a77b93afa746b2d29e37d6014cab9f9c21471f685a2392426760a17dabf'
CACHE_VERSION = '001016-2bd6e-2e85'


def simplify(points, tolerance=.65):
    """Ramer–Douglas–Peucker on one open half of the closed contour."""
    if len(points) <= 2:
        return points
    p = np.asarray(points, dtype=float)
    vector = p[-1] - p[0]
    length2 = np.dot(vector, vector)
    t = np.clip((p - p[0]) @ vector / length2, 0, 1) if length2 else np.zeros(len(p))
    distances = np.linalg.norm(p - (p[0] + t[:, None] * vector), axis=1)
    split = int(distances.argmax())
    if distances[split] <= tolerance:
        return [points[0], points[-1]]
    return simplify(points[:split + 1], tolerance)[:-1] + simplify(points[split:], tolerance)


def trace():
    """Trace the single connected ink silhouette, excluding paper texture."""
    image = Image.open(SOURCE / 'source.png').convert('L')
    raw = np.asarray(image) < 120
    labels, _ = ndimage.label(raw)
    counts = np.bincount(labels.ravel())
    counts[0] = 0
    mask = ndimage.binary_fill_holes(labels == counts.argmax())
    Image.fromarray(np.where(mask, 0, 255).astype('uint8')).save(SOURCE / 'mask.png')
    # Directed exposed pixel edges, clockwise in screenshot coordinates.
    edges = {}
    height, width = mask.shape
    for y, x in zip(*np.nonzero(mask)):
        for outside, start, end in [
            (y == 0 or not mask[y-1, x], (x, y), (x+1, y)),
            (x == width-1 or not mask[y, x+1], (x+1, y), (x+1, y+1)),
            (y == height-1 or not mask[y+1, x], (x+1, y+1), (x, y+1)),
            (x == 0 or not mask[y, x-1], (x, y+1), (x, y)),
        ]:
            if outside:
                if start in edges:
                    raise ValueError('Ambiguous boundary; inspect the scan before tracing')
                edges[start] = end
    start = min(edges, key=lambda point: (point[1], point[0]))
    points, current = [start], edges[start]
    while current != start:
        points.append(current)
        current = edges[current]
    if len(points) != len(edges):
        raise ValueError('Expected one outer contour without holes')
    farthest = max(range(len(points)), key=lambda i: np.linalg.norm(np.array(points[i])-start))
    polygon = (simplify(points[:farthest+1])[:-1]
               + simplify(points[farthest:] + [start])[:-1])
    mids = [((p[0]+polygon[(i+1) % len(polygon)][0])/2,
             (p[1]+polygon[(i+1) % len(polygon)][1])/2) for i, p in enumerate(polygon)]
    path = f'M {mids[-1][0]:g},{mids[-1][1]:g} ' + ' '.join(
        f'Q {p[0]:g},{p[1]:g} {mid[0]:g},{mid[1]:g}' for p, mid in zip(polygon, mids)) + ' Z'
    (SOURCE / 'outline.svg').write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">\n'
        '  <title>Page 398 person radical, traced from the supplied scan</title>\n'
        f'  <path fill="#000" d="{path}"/>\n</svg>\n')
    return {'threshold': 120, 'raw_ink_pixels': int(raw.sum()),
            'clean_ink_pixels': int(mask.sum()), 'pixel_boundary_edges': len(edges),
            'quadratic_segments': len(polygon), 'rdp_tolerance_px': .65}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', action='store_true', help='Regenerate SVG and cleaned mask')
    parser.add_argument('--apply', action='store_true', help='Back up and replace repository font')
    parser.add_argument('--font', type=Path, default=FONT, help='Baseline font, useful for replay')
    args = parser.parse_args()
    if args.apply and args.font.resolve() != FONT:
        parser.error('--apply only targets the repository large font')
    trace_stats = trace() if args.trace else None
    before_hash = sha256(args.font)
    if before_hash != BASELINE:
        raise ValueError('Unexpected baseline; refusing to overwrite or rebase the font')
    scratch = ROOT / 'var/font-audit/0398'
    scratch.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    output = scratch / 'guji-large-2e85.ttf'
    with TTFont(args.font, recalcTimestamp=False) as before:
        if CP in before.getBestCmap():
            raise ValueError('Target codepoint already exists')
        anchor = before['glyf'][before.getBestCmap()[0x4EBA]]
        d = svg_path_d(str(SOURCE / 'outline.svg'))
        bounds = path_bounds(d)
        scale = (anchor.yMax-anchor.yMin) / (bounds[3]-bounds[1])
        advance = before['hmtx'][before.getBestCmap()[0x4EBA]][0]
        tx = advance/2 - scale*(bounds[0]+bounds[2])/2
        ty = anchor.yMax + scale*bounds[1]
        pen = TTGlyphPen(before.getGlyphSet())
        parse_path(d, TransformPen(Cu2QuPen(pen, max_err=1),
                                   Transform(scale, 0, 0, -scale, tx, ty)))
        glyph = pen.glyph()
        patch_font(str(args.font), CP, glyph, advance, False, str(output))
        print('Candidate built; checking all existing outlines and metrics.', flush=True)
        with TTFont(output, recalcTimestamp=False) as after:
            verify_addition(before, after, CP)
            for old, new in zip(before['cmap'].tables, after['cmap'].tables):
                expected = dict(old.cmap)
                if old.isUnicode() and old.format in (4, 12):
                    expected[CP] = after.getBestCmap()[CP]
                if new.cmap != expected:
                    raise ValueError('Unexpected cmap subtable changes')
            added = after['glyf'][after.getBestCmap()[CP]]
            facts = {'codepoint': 'U+2E85', 'glyph': after.getBestCmap()[CP],
                     'cmap_before': len(before.getBestCmap()), 'cmap_after': len(after.getBestCmap()),
                     'unchanged_existing_glyphs': len(before.getGlyphOrder()),
                     'bbox': [added.xMin, added.yMin, added.xMax, added.yMax],
                     'advance': advance, 'contours': added.numberOfContours,
                     'points': len(added.coordinates), 'transform': [scale, 0, 0, -scale, tx, ty],
                     'glyph_sha256': hashlib.sha256(added.compile(after['glyf'])).hexdigest()}
    font = ImageFont.truetype(str(output), 240)
    rendered = Image.new('L', (320, 320), 255)
    ImageDraw.Draw(rendered).text((160, 160), chr(CP), font=font, fill=0, anchor='mm')
    rendered.save(FIGURES / 'font-render.png')
    # Only set width: setting both dimensions stretches a non-square SVG.
    svg_raster = scratch / 'svg-reference.png'
    subprocess.run(['rsvg-convert', '-w', '512', '--background-color=white',
                    str(SOURCE / 'outline.svg'), '-o', str(svg_raster)], check=True)
    svg_image = Image.open(svg_raster).convert('L')
    mask = Image.open(SOURCE / 'mask.png')
    scores = {'svg_to_font': chamfer(norm_ink(svg_image), norm_ink(rendered)),
              'scan_to_font': chamfer(norm_ink(mask), norm_ink(rendered))}
    if scores['svg_to_font'] >= .15 or scores['scan_to_font'] >= .5:
        raise ValueError(f'Render validation failed: {scores}')
    comparison = Image.new('RGB', (960, 370), 'white')
    draw = ImageDraw.Draw(comparison)
    for i, (label, im) in enumerate([('Supplied scan', Image.open(SOURCE / 'source.png')),
                                    ('Traced SVG', svg_image), ('U+2E85 / guji-large', rendered)]):
        im = im.convert('RGB')
        im.thumbnail((290, 310))
        comparison.paste(im, (i*320+(320-im.width)//2, 40+(310-im.height)//2))
        draw.text((i*320+25, 16), label, fill='black')
    comparison.save(FIGURES / 'comparison.png')
    record = {'at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
              'operation': 'add-standard-radical', 'applied': args.apply,
              'font': str(FONT.relative_to(ROOT)), 'sha256_before': before_hash,
              'sha256_after': sha256(output), 'bytes_before': args.font.stat().st_size,
              'bytes_after': output.stat().st_size, 'source_sha256': sha256(SOURCE / 'source.png'),
              'svg_sha256': sha256(SOURCE / 'outline.svg'), 'cache_version': CACHE_VERSION,
              'trace': trace_stats, 'validation': scores, **facts}
    if args.apply:
        if sha256(FONT) != before_hash:
            raise ValueError('Font changed during verification')
        backup = ROOT / f'var/unencoded/kangxi-unencoded/font-backups/guji-large.ttf.{before_hash}.ttf'
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists() and sha256(backup) != before_hash:
            raise ValueError('Existing backup is corrupt')
        if not backup.exists():
            shutil.copy2(FONT, backup)
        record['backup'] = str(backup.relative_to(ROOT))
        os.replace(output, FONT)
        log = ROOT / 'var/unencoded/kangxi-unencoded/font-patches.jsonl'
        with log.open('a') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    destination = EVIDENCE / 'patch-verification.json' if args.apply else scratch / 'dry-run.json'
    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
