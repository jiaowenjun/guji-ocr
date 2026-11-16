#!/usr/bin/env python3
"""Verify exported image/label/crop integrity without altering the dataset."""
import argparse
import json
from pathlib import Path

from PIL import Image

from build_ocr_dataset import DEFAULT_OUTPUT, intact, read_json, validate_annotation


def verify(output):
    manifest = read_json(output/'manifest.json')
    if manifest['errors']: raise ValueError('Build manifest contains failed pages')
    totals = {'pages': 0, 'page_images': 0, 'codepoints_per_domain': 0, 'regions_per_domain': 0,
              'glyph_slots_per_domain': 0, 'crops': 0, 'scan_geometry_status': 'proposed'}
    records = {r['page']: r for r in manifest['pages']}
    assert len(records) == len(manifest['pages']), 'Duplicate page records'
    expected_page_images = set(); expected_crop_images = set()
    for record in records.values():
        if not intact(output, record): raise ValueError(f"Corrupt artifacts: @{record['page']}")
        base = output/record['path']
        source_text = (base/'text.txt').read_text(encoding='utf-8')
        compact = ''.join(source_text.split())
        for domain in ('synthetic', 'scan'):
            a = read_json(base/f'{domain}.json'); validate_annotation(a)
            assert a['text'] == compact
            with Image.open(base/a['image']) as im: assert im.size == (a['width'], a['height'])
            cursor = 0
            for glyph in a['glyphs']:
                assert glyph['text_range'] == [cursor, cursor+len(glyph['text'])]
                cursor += len(glyph['text'])
            assert cursor == len(compact)
            assert a['reading_order'] == [r['id'] for r in a['regions']]
            assert a['glyph_reading_order'] == [g['id'] for g in a['glyphs']]
            expected_page_images.add(record['path']+'/'+a['image'])
            if domain == 'synthetic':
                # Every intended glyph must leave ink inside its allocated cell.
                with Image.open(base/a['image']) as im:
                    gray = im.convert('L')
                    for glyph in a['glyphs']:
                        b = tuple(round(v) for v in glyph['ink_bbox'])
                        assert gray.crop(b).getextrema()[0] < 100, glyph['id']
                totals['codepoints_per_domain'] += len(compact)
                totals['regions_per_domain'] += len(a['regions'])
                totals['glyph_slots_per_domain'] += len(a['glyphs'])
            totals['page_images'] += 1
        for crop in read_json(base/'crops.json'):
            x1,y1,x2,y2 = crop['bbox_in_page']
            with Image.open(base/crop['image']) as im: assert im.size == (x2-x1,y2-y1)
            assert crop['text'] and crop['split_group'] == 'kangxi-wuyingdian-development'
            expected_crop_images.add(record['path']+'/'+crop['image'])
            totals['crops'] += 1
        totals['pages'] += 1
    for file, expected in [('pages.jsonl',expected_page_images),('recognition.jsonl',expected_crop_images)]:
        rows = [json.loads(line) for line in (output/file).read_text(encoding='utf-8').splitlines()]
        assert len(rows) == len(expected) and {r['image'] for r in rows} == expected, file
    return totals


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    args=parser.parse_args()
    print(json.dumps(verify(args.output),ensure_ascii=False))
