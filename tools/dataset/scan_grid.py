#!/usr/bin/env python3
"""Preview grid geometry, read-only. stdin: {page, spans: [8 × row spans]}.

Uses the dataset report's image-grid + per-band vertical fit. Returns only the
eight full band mappings, never text regions/glyph proposals or OCR results.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

from ocr_scan import detect_grid, fit_vertical, segmentation

MANIFEST = Path(__file__).resolve().parents[2] / 'kangxi-gold' / 'manifest.json'


def scan_grid(request, manifest_path=MANIFEST):
    page = request.get('page')
    spans = request.get('spans')
    if type(page) is not int or not 1 <= page <= 7738:
        raise ValueError('原图字格页码无效')
    if not isinstance(spans, list) or len(spans) != 8:
        raise ValueError('原图字格需要八个大列的行位')
    for band in spans:
        if not isinstance(band, list) or len(band) > 48:
            raise ValueError('原图字格行位无效')
        for span in band:
            if (not isinstance(span, list) or len(span) != 2 or
                    any(type(v) is not int for v in span) or not 0 <= span[0] < span[1] <= 24):
                raise ValueError('原图字格行位必须位于 0–24 内')

    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    entry = next((e for e in manifest['pages'] if e['page'] == page), None)
    if entry is None:
        raise ValueError(f'页码不在数据集内：{page}')
    images_dir = (manifest_path.parent / manifest['images_dir']).resolve()
    image_path = (images_dir / entry['image']).resolve()
    if not image_path.is_relative_to(images_dir):
        raise ValueError('扫描图路径不在数据集内')
    with Image.open(image_path) as image:
        width, height = image.size
        dark = (np.asarray(image.convert('L')) < segmentation.DARK_THR).astype(float)
    detected = detect_grid(dark)
    _, top, _, bottom = detected['block']
    pitch = (bottom - top) / 24
    boxes = []
    for major, band in zip(detected['majors'], spans):
        glyphs = [{'grid_bbox': [0, start, 1, end]} for start, end in band]
        bt, bp, _ = fit_vertical(dark, glyphs, major['x1'], major['x2'], top, pitch, 24)
        boxes.append([major['x1'], bt, major['x2'], bt + 24 * bp])
    return {'ok': True, 'width': width, 'height': height, 'bands': boxes}


def main():
    try:
        print(json.dumps(scan_grid(json.load(sys.stdin)), ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
