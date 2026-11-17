#!/usr/bin/env python3
"""Compute EM/CER/latency metrics for one or both engine result files.

Usage: receval_metrics.py ONNX_JSON SERVICE_JSONL
"""
import json
import statistics
import sys


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


def metrics(rows):
    ok, dists, glen, plen = 0, 0, 0, 0
    by_kind = {}
    for r in rows:
        g, p = norm(r['gold']), norm(r.get('pred'))
        d = lev(g, p)
        dists += d; glen += len(g); plen += len(p or '')
        ok += (d == 0 and len(g) > 0)
        k = by_kind.setdefault(r['kind'], [0, 0, 0, 0])  # n, em, dist, glen
        k[0] += 1; k[1] += (d == 0); k[2] += d; k[3] += len(g)
    out = {'n': len(rows), 'em': ok, 'em_rate': round(ok / len(rows), 4),
           'cer_corpus': round(dists / glen, 4) if glen else None,
           'cer_macro': round(statistics.mean(
               lev(norm(r['gold']), norm(r.get('pred'))) / max(1, len(norm(r['gold']))) for r in rows), 4),
           'char_output_over_gold': round(plen / glen, 3) if glen else None,
           'by_kind': {k: {'n': v[0], 'em_rate': round(v[1] / v[0], 4), 'cer': round(v[2] / v[3], 4) if v[3] else None}
                       for k, v in by_kind.items()}}
    return out


def main():
    onnx = json.load(open(sys.argv[1]))
    print('ONNX PP-OCRv6 (local):')
    print(json.dumps(metrics(onnx['rows']), ensure_ascii=False, indent=1))
    if len(sys.argv) > 2:
        svc = [json.loads(l) for l in open(sys.argv[2])]
        succ = [r for r in svc if r.get('status') == 'succeeded']
        print(f'\nservice PaddleOCR-VL: ({len(succ)}/{len(svc)} succeeded)')
        if succ:
            m = metrics(succ)
            m['latency_s'] = {'mean': round(statistics.mean(r['total_s'] for r in succ), 1),
                              'p50': round(statistics.median(r['total_s'] for r in succ), 1),
                              'max': round(max(r['total_s'] for r in succ), 1)}
            print(json.dumps(m, ensure_ascii=False, indent=1))
        fails = [r for r in svc if r.get('status') != 'succeeded']
        if fails:
            print('failures:', json.dumps(fails[:5], ensure_ascii=False))


if __name__ == '__main__':
    main()
