"""Replay the frozen before/after implementations against the same scan files.

Run from any directory. The manifest supplies image locations; all legacy row
spans are frozen in input-priors.json. Writes a separate verified-results.json.
Requires the repository's NumPy/Pillow environment and the external scan disk.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / 'tools/dataset'))
sys.path.insert(0, str(ROOT / 'tools/eval'))


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cells(values):
    return {(c['band'], c['col'], c['row']) for c in values}


def delta(before, after):
    return {'added': sorted(cells(after) - cells(before)),
            'removed': sorted(cells(before) - cells(after))}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    old, new = load('ocr_scan_before'), load('ocr_scan_after')
    old_api, new_api = load('scan_grid_before'), load('scan_grid_after')
    # The frozen entry points must import their own detector, not the working
    # tree's ocr_scan module that their original import statement resolves to.
    for api, implementation in ((old_api, old), (new_api, new)):
        for name in ('detect_grid', 'fit_vertical', 'detect_blank_cells', 'segmentation'):
            setattr(api, name, getattr(implementation, name))

    manifest_path = ROOT / 'kangxi-gold/manifest.json'
    manifest = json.loads(manifest_path.read_text())
    entries = {entry['page']: entry for entry in manifest['pages']}
    image_root = (manifest_path.parent / manifest['images_dir']).resolve()
    inputs = json.loads((HERE / 'input-priors.json').read_text())
    prior_check = json.loads((HERE / 'prior-verification.json').read_text())
    historical = {r['page']: r for r in json.loads((HERE / 'historical-final-results.json').read_text())}
    results = []
    for index, request in enumerate(inputs):
        page = request['page']
        image_path = image_root / entries[page]['image']
        record = {'page': page, 'image': entries[page]['image'],
                  'image_sha256': sha(image_path), 'status': entries[page].get('status')}
        annotation = manifest_path.parent / 'annotations' / entries[page]['annotations']['gj']
        record['annotation_sha256_at_report'] = sha(annotation)
        for name, api in (('before', old_api), ('after', new_api)):
            try:
                record[name] = api.scan_grid(request, manifest_path)
            except ValueError as error:
                record[name] = {'ok': False, 'error': str(error)}
        if record['before']['ok'] and record['after']['ok']:
            before, after = record['before'], record['after']
            record['delta'] = delta(before['blank_cells'], after['blank_cells'])
            record['geometry_max_edge_delta_px'] = max(
                abs(a - b) for x, y in zip(before['bands'], after['bands']) for a, b in zip(x, y))
            with Image.open(image_path) as image:
                gray = np.asarray(image.convert('L'))
            geometry_only = old.detect_blank_cells(gray, after['bands'], request['spans'])
            no_draft_mask = old.detect_blank_cells(gray, after['bands'], [[] for _ in after['bands']])
            with patch.object(new, '_book_rule_mask',
                              side_effect=lambda gray, cell, box, threshold:
                              np.zeros((box[3] - box[1], box[2] - box[0]), dtype=bool)):
                without_book_filter = new.detect_blank_cells(gray, after['bands'])
            record['stages'] = {
                'old_detector_new_geometry': geometry_only,
                'pixel_candidates_without_large_mask': no_draft_mask,
                'new_detector_without_book_filter': without_book_filter,
                'geometry_effect': delta(before['blank_cells'], geometry_only),
                'large_mask_effect': delta(geometry_only, without_book_filter),
                'book_filter_effect': delta(without_book_filter, after['blank_cells']),
            }
            record['matches_historical_final'] = (
                historical[page]['before'] == before['blank_cells']
                and historical[page]['old_boxes'] == before['bands']
                and historical[page]['found'] == after['blank_cells']
                and historical[page]['boxes'] == after['bands'])
        else:
            record['matches_historical_final'] = (
                not record['before']['ok'] and not record['after']['ok']
                and historical[page].get('error') == record['after']['error'])
        results.append(record)
        if (index + 1) % 20 == 0 or index + 1 == len(inputs):
            print(f'{index + 1}/{len(inputs)}', flush=True)

    valid = [r for r in results if r['before']['ok'] and r['after']['ok']]
    changed = [r for r in valid if r['delta']['added'] or r['delta']['removed']]
    payload = {
        'date': '2026-11-19', 'timezone': 'Asia/Shanghai',
        'baseline_git_commit': '6bbd4bbe06b392fd22dee2bee72312009da7dc45',
        'coordinate_convention': 'band: right to left 0..7; col: left=0,right=1; row: top to bottom 0..23',
        'manifest_sha256': sha(manifest_path), 'prior_verification': prior_check,
        'source_sha256': {name: sha(HERE / name) for name in (
            'ocr_scan_before.py', 'ocr_scan_after.py', 'scan_grid_before.py', 'scan_grid_after.py', 'input-priors.json')},
        'working_dependencies_sha256': {name: sha(ROOT / name) for name in (
            'tools/eval/kangxi_column_seg.py', 'tools/dataset/ocr_render.py', 'tools/paths.py',
            'guji-preview-grid/src/components/dataset/use-scan-grid.ts',
            'guji-preview-grid/src/components/dataset/scan-grid.ts')},
        'summary': {
            'pages': len(results), 'both_located': len(valid),
            'both_failed': [r['page'] for r in results if not r['before']['ok'] and not r['after']['ok']],
            'changed_blank_sets': [r['page'] for r in changed],
            'changed_geometry': [r['page'] for r in valid if r['geometry_max_edge_delta_px'] > 0],
            'added': sum(len(r['delta']['added']) for r in valid),
            'removed': sum(len(r['delta']['removed']) for r in valid),
            'historical_matches': sum(r['matches_historical_final'] for r in results),
        },
        'pages': results,
    }
    (HERE / 'verified-results.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(payload['summary'], ensure_ascii=False))


if __name__ == '__main__':
    main()
