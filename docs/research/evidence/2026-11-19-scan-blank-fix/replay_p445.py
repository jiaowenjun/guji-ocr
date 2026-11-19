"""Replay the page-445 regression with frozen detectors and current-scan pixels.

Requires NumPy/Pillow and the scan disk configured by kangxi-gold/manifest.json.
The old API receives frozen spans from the annotation captured during diagnosis.
No production code or annotations are modified.
"""
import json
from unittest.mock import patch

import numpy as np
from PIL import Image

from replay import HERE, ROOT, cells, delta, load, sha


def main():
    old, new = load('ocr_scan_before'), load('ocr_scan_after')
    old_api, new_api = load('scan_grid_before'), load('scan_grid_after')
    for api, implementation in ((old_api, old), (new_api, new)):
        for name in ('detect_grid', 'fit_vertical', 'detect_blank_cells', 'segmentation'):
            setattr(api, name, getattr(implementation, name))
    manifest_path = ROOT / 'kangxi-gold/manifest.json'
    manifest = json.loads(manifest_path.read_text())
    entry = next(e for e in manifest['pages'] if e['page'] == 445)
    image_path = (manifest_path.parent / manifest['images_dir'] / entry['image']).resolve()
    expected = json.loads((HERE / 'p445-analysis.json').read_text())
    assert sha(image_path) == expected['image_sha256'], 'Scan image has changed'
    request = json.loads((HERE / 'p445-input.json').read_text())
    before = old_api.scan_grid(request, manifest_path)
    after = new_api.scan_grid(request, manifest_path)
    with Image.open(image_path) as image:
        gray = np.asarray(image.convert('L'))
    target = (4, 1, 1)
    stages = {
        'old_detector_new_geometry': old.detect_blank_cells(gray, after['bands'], request['spans']),
        'new_detector_old_geometry': new.detect_blank_cells(gray, before['bands']),
    }
    with patch.object(new, '_book_rule_mask', side_effect=lambda gray, cell, box, threshold:
                      np.zeros((box[3] - box[1], box[2] - box[0]), dtype=bool)):
        stages['new_detector_no_book_filter'] = new.detect_blank_cells(gray, after['bands'])
    result = {
        'page': 445,
        'image_sha256': sha(image_path),
        'before': before,
        'after': after,
        'delta': delta(before['blank_cells'], after['blank_cells']),
        'stages_target_is_blank': {name: target in cells(value) for name, value in stages.items()},
    }
    assert before == expected['before'] and after == expected['after']
    assert target not in cells(before['blank_cells']) and target in cells(after['blank_cells'])
    assert result['stages_target_is_blank'] == {
        'old_detector_new_geometry': True,
        'new_detector_old_geometry': False,
        'new_detector_no_book_filter': True,
    }
    (HERE / 'p445-verified.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'counts': [len(before['blank_cells']), len(after['blank_cells'])],
                      'delta': result['delta'], 'stages': result['stages_target_is_blank']}))


if __name__ == '__main__':
    main()
