#!/usr/bin/env python3
"""Run local ONNX PP-OCRv6 (ultralytics TextRecognizer) over the same eval crops.

Usage: receval_onnx.py SAMPLE_JSON OUT_JSON
Timing: per-crop single-call latency (after warmup) plus one batched throughput pass.
"""
import json
import statistics
import sys
import time

import cv2
import numpy as np
from ultralytics.solutions.ocr import TextRecognizer

ROOT = '/Users/jwj/workspace/guji-ocr/var/datasets/kangxi-ocr/'


def main():
    sample = json.load(open(sys.argv[1]))
    rec = TextRecognizer('PP-OCRv6_medium_rec.onnx', None)

    crops = []
    for item in sample:
        im = cv2.imread(ROOT + item['image'])
        crops.append((item, im))

    warm = [c for _, c in crops[:8]]
    rec(warm)  # warmup loads ONNX + allocator

    # per-crop latency
    rows = []
    times = []
    for item, im in crops:
        t0 = time.perf_counter()
        (text, conf), = rec([im])
        times.append(time.perf_counter() - t0)
        rows.append({'id': item['id'], 'gold': item['text'], 'kind': item['kind'],
                     'page': item['source_page'], 'pred': text, 'conf': round(float(conf), 4),
                     'ms': round((time.perf_counter() - t0) * 1000, 1)})

    # batched throughput (recognizer sorts internally into batches of 8 by width)
    t0 = time.perf_counter()
    batched = rec([im for _, im in crops])
    batch_s = time.perf_counter() - t0

    stats = {
        'n': len(rows),
        'per_crop_ms': {'mean': round(statistics.mean(r['ms'] for r in rows), 1),
                        'p50': round(statistics.median(r['ms'] for r in rows), 1),
                        'p95': round(sorted(r['ms'] for r in rows)[int(.95 * len(rows))], 1),
                        'max': round(max(r['ms'] for r in rows), 1)},
        'batch_total_s': round(batch_s, 2),
        'batch_ms_per_crop': round(batch_s * 1000 / len(rows), 1),
        'batch_preds_match_percrop': sum(1 for r, (t, _) in zip(rows, batched) if r['pred'] == t),
    }
    json.dump({'stats': stats, 'rows': rows}, open(sys.argv[2], 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
