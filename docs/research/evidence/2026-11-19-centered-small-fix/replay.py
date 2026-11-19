"""Compare the centred-small-text repair on the manifest's scan images.

Both implementations and the unchanged image-only API are frozen here. Reads
the external scan disk; writes results.json, never annotations or app data.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
import time

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(ROOT / 'tools/dataset'), str(ROOT / 'tools/eval')]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cells(values):
    return {(c['band'], c['col'], c['row']) for c in values}


def main():
    implementations = {key: load(key, f'ocr_scan_{key}.py') for key in ('before', 'after')}
    apis = {key: load(f'{key}_api', 'scan_grid_snapshot.py') for key in implementations}
    for key, api in apis.items():
        for name in ('detect_grid', 'fit_vertical', 'detect_blank_cells', 'segmentation'):
            setattr(api, name, getattr(implementations[key], name))
    # Freeze the scope: the user may continue adding pages during the audit.
    manifest_path = HERE / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    records = []
    for index, entry in enumerate(manifest['pages']):
        image_path = (manifest_path.parent / manifest['images_dir'] / entry['image']).resolve()
        record = {'page': entry['page'], 'image': entry['image'], 'image_sha256': sha(image_path)}
        for key, api in apis.items():
            start = time.perf_counter()
            try:
                record[key] = api.scan_grid({'page': entry['page']}, manifest_path)
            except ValueError as error:
                record[key] = {'ok': False, 'error': str(error)}
            record[key + '_seconds'] = round(time.perf_counter() - start, 3)
        if record['before']['ok'] and record['after']['ok']:
            before, after = record['before'], record['after']
            record['geometry_equal'] = before['bands'] == after['bands']
            record['delta'] = {
                'added': sorted(cells(after['blank_cells']) - cells(before['blank_cells'])),
                'removed': sorted(cells(before['blank_cells']) - cells(after['blank_cells'])),
            }
            with Image.open(image_path) as image:
                gray = np.asarray(image.convert('L'))
            record['centered_rows'] = [sorted(implementations['after']._scan_centered_rows(gray, box))
                                       for box in after['bands']]
            if record['delta']['added'] or record['delta']['removed']:
                print(f"Changed {entry['page']}: {record['delta']}", flush=True)
        records.append(record)
        if (index + 1) % 10 == 0 or index + 1 == len(manifest['pages']):
            print(f"{index + 1}/{len(manifest['pages'])}", flush=True)
    valid = [r for r in records if r['before']['ok'] and r['after']['ok']]
    summary = {
        'pages': len(records), 'both_ok': len(valid),
        'both_failed': [r['page'] for r in records if not r['before']['ok'] and not r['after']['ok']],
        'status_changed': [r['page'] for r in records if r['before']['ok'] != r['after']['ok']],
        'changed_blank_sets': [r['page'] for r in valid if r['delta']['added'] or r['delta']['removed']],
        'changed_geometry': [r['page'] for r in valid if not r['geometry_equal']],
        'added': sum(len(r['delta']['added']) for r in valid),
        'removed': sum(len(r['delta']['removed']) for r in valid),
    }
    payload = {
        'date': '2026-11-19', 'summary': summary, 'manifest_sha256': sha(manifest_path),
        'coordinate_convention': 'band: right to left 0..7; col: left=0,right=1; row: top to bottom 0..23',
        'source_sha256': {name: sha(HERE / name) for name in
                          ('ocr_scan_before.py', 'ocr_scan_after.py', 'scan_grid_snapshot.py')},
        'dependencies_sha256': {name: sha(ROOT / name) for name in
                                ('tools/eval/kangxi_column_seg.py', 'tools/dataset/ocr_render.py', 'tools/paths.py')},
        'pages': records,
    }
    (HERE / 'results.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
