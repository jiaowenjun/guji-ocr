#!/usr/bin/env python3
"""Preview grid geometry, read-only. stdin: {page}.

Uses scan evidence and a fixed 24-row lattice, independent of edited text. Returns the
eight full band mappings and image-detected blank small cells, never text boxes.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

from ocr_scan import detect_blank_cells, detect_grid, fit_vertical, segmentation

MANIFEST = Path(__file__).resolve().parents[2] / 'kangxi-gold' / 'manifest.json'


def scan_grid(request, manifest_path=MANIFEST):
    page = request.get('page')
    if type(page) is not int or not 1 <= page <= 7738:
        raise ValueError('原图字格页码无效')

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
        gray = np.asarray(image.convert('L'))
        dark = (gray < segmentation.DARK_THR).astype(float)
    detected = detect_grid(dark)
    _, top, _, bottom = detected['block']
    pitch = (bottom - top) / 24
    boxes = []
    glyphs = [{'grid_bbox': [0, row, 1, row + 1]} for row in range(24)]
    for major in detected['majors']:
        # An empty scan has no phase evidence; retain its measured frame.
        x1, x2 = max(0, round(major['x1'])), min(width, round(major['x2']))
        targets = glyphs if dark[max(0, top):min(height, bottom), x1:x2].any() else []
        bt, bp, _ = fit_vertical(dark, targets, major['x1'], major['x2'], top, pitch, 24)
        boxes.append([major['x1'], bt, major['x2'], bt + 24 * bp])
    return {'ok': True, 'width': width, 'height': height, 'bands': boxes,
            'blank_cells': detect_blank_cells(gray, boxes)}


def main():
    try:
        print(json.dumps(scan_grid(json.load(sys.stdin)), ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
