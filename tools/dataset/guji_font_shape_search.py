#!/usr/bin/env python3
"""Rank font glyphs against a scan; candidates require human/source verification.

This reproduces the 2026-11-18 @373 audit's 64px distance-transform search.
It does not identify characters or prove that a form is absent from Unicode.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[2]


def normalized(mask):
    y, x = np.nonzero(mask)
    if not len(y):
        return None
    sub = mask[y.min():y.max()+1, x.min():x.max()+1]
    h, w = sub.shape
    scale = 58 / max(h, w)
    nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
    resized = np.asarray(Image.fromarray(sub.astype('uint8') * 255).resize(
        (nw, nh), Image.Resampling.BILINEAR)) > 96
    out = np.zeros((64, 64), bool)
    oy, ox = (64-nh)//2, (64-nw)//2
    out[oy:oy+nh, ox:ox+nw] = resized
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--threshold', type=int, default=120)
    parser.add_argument('--font', action='append', type=Path)
    args = parser.parse_args()
    target = normalized(np.asarray(Image.open(args.image).convert('L')) < args.threshold)
    if target is None:
        parser.error('target contains no foreground')
    target_distance = ndimage.distance_transform_edt(~target)
    fonts = args.font or [ROOT / 'guji-preview-grid/public/fonts' / name
                        for name in ['guji-plane0.ttf', 'guji-plane2.ttf', 'guji-planef.ttf']]
    result = {}
    for path in fonts:
        with TTFont(path) as ft:
            cmap = ft.getBestCmap()
        font = ImageFont.truetype(str(path), 96)
        rows = []
        for cp, name in cmap.items():
            if cp < 0x2E80:
                continue
            image = Image.new('L', (128, 128), 255)
            ImageDraw.Draw(image).text((64, 64), chr(cp), font=font, fill=0, anchor='mm')
            ink = normalized(np.asarray(image) < 128)
            if ink is None:
                continue
            score = float(.5 * (target_distance[ink].mean()
                               + ndimage.distance_transform_edt(~ink)[target].mean()))
            rows.append({'cp': f'{cp:X}', 'char': chr(cp), 'glyph': name, 'score': score})
        rows.sort(key=lambda row: row['score'])
        result[path.name] = {'count': len(rows), 'top100': rows[:100]}
        print(path.name, len(rows), 'glyphs; first candidate', rows[0]['cp'], flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
