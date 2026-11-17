#!/usr/bin/env python3
"""Whole-page OCR comparison: online PaddleOCR-VL (cached) vs local grid-crop + ONNX PP-OCRv6.

Pipeline:
  1. gold assembly check: order crops by (band x desc -> lane x desc -> y asc) and
     verify concatenated GOLD texts equal the gold page transcription.
  2. local page text: same ordering applied to ONNX crop predictions.
  3. online page text: parsing_res_list block_content concat from the service DB cache.
  4. per-page CER + char-count ratio for both engines.
"""
import json
import sqlite3
import statistics
import sys

GOLD_DIR = '/Users/jwj/workspace/guji-ocr/kangxi-gold/annotations/'
DB = '/Users/jwj/workspace/guji-ocr/paddleocr-baseline/data/ocr/ocr.sqlite3'
PAGES = [312, 318, 328, 342, 349, 358]


def norm(s):
    return ''.join((s or '').split())


def lev(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def assemble(crops):
    """Order text_run + large crops: bands right-to-left, lanes right-to-left, top-to-bottom."""
    def band_key(c):
        return -c['bbox_in_page'][0]  # band left edge, right first
    bands = {}
    for c in crops:
        b = c['id'].split('-')[1]  # bN
        bands.setdefault(b, []).append(c)
    ordered = []
    for b in sorted(bands, key=lambda b: -min(c['bbox_in_page'][0] for c in bands[b])):
        group = bands[b]
        if len(group) == 1:
            ordered += group
            continue
        # lanes by x-center: right lane first; centered elements join the right lane flow by y
        xs = sorted(c['bbox_in_page'][0] + c['bbox_in_page'][2] for c in group)  # 2*center
        split = (xs[0] + xs[-1]) / 2
        right = [c for c in group if (c['bbox_in_page'][0] + c['bbox_in_page'][2]) / 2 >= split / 1]
        left = [c for c in group if c not in right]
        right.sort(key=lambda c: c['bbox_in_page'][1])
        left.sort(key=lambda c: c['bbox_in_page'][1])
        ordered += right + left
    return ordered


def main():
    onnx = {r['id']: r for r in json.load(open('/Users/jwj/workspace/guji-ocr/var/scratch/receval_onnx.json'))['rows']}
    sample = json.load(open('/Users/jwj/workspace/guji-ocr/var/scratch/receval_sample.json'))
    db = sqlite3.connect(DB)
    by_hash = {r[0]: (r[1], r[2], r[3]) for r in db.execute(
        "select sha256, result_json, created_at, finished_at from images where status='succeeded'")}
    import hashlib
    report = []
    for page in PAGES:
        crops = [c for c in sample if c['source_page'] == page and c['kind'] in ('text_run', 'large')]
        ordered = assemble(crops)
        gold_page = norm(open(GOLD_DIR + '%04d.txt' % page).read())
        gold_asm = norm(''.join(c['text'] for c in ordered))
        asm_ok = gold_asm == gold_page
        local = norm(''.join(onnx[c['id']]['pred'] for c in ordered))
        local_ms = sum(onnx[c['id']]['ms'] for c in ordered)
        h = hashlib.sha256(open('/Volumes/WD-2T/guji-ocr/raw/kangxizidian/pages/%04d.jpg' % page, 'rb').read()).hexdigest()
        rj, created, finished = by_hash[h]
        rj = json.loads(rj)
        blocks = []
        for pg in rj.get('result', {}).get('layoutParsingResults', []):
            for block in pg.get('prunedResult', {}).get('parsing_res_list', []):
                blocks.append(block.get('block_content') or '')
        online = norm(''.join(blocks))
        dur = None
        if created and finished:
            from datetime import datetime
            t0 = datetime.fromisoformat(created.replace('Z', '+00:00'))
            t1 = datetime.fromisoformat(finished.replace('Z', '+00:00'))
            dur = (t1 - t0).total_seconds()
        report.append({
            'page': page, 'crops': len(ordered), 'assembly_gold_exact': asm_ok,
            'gold_len': len(gold_page),
            'online': {'cer': round(lev(gold_page, online) / len(gold_page), 4),
                       'len_ratio': round(len(online) / len(gold_page), 3), 'measured_s': dur},
            'local': {'cer': round(lev(gold_page, local) / len(gold_page), 4),
                      'len_ratio': round(len(local) / len(gold_page), 3),
                      'recognize_ms': round(local_ms)},
        })
        print(json.dumps(report[-1], ensure_ascii=False))
    ok = [r for r in report if r['assembly_gold_exact']]
    print('\npages with validated gold assembly: %d/%d' % (len(ok), len(report)))
    for eng in ('online', 'local'):
        cers = [r[eng]['cer'] for r in report]
        print('%s: CER mean %.4f  range %.4f-%.4f' % (eng, statistics.mean(cers), min(cers), max(cers)))
    json.dump(report, open('/Users/jwj/workspace/guji-ocr/var/scratch/pageeval_report.json', 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
