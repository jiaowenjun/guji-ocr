#!/usr/bin/env python3
"""生产链路正确性评估：对初校页跑「OCR自动断行」全流程，输出 vs 真值。

链路 = cmd_ocr_fold 真实路径：读 .gj 带 → ocr_fold_page_lines（压平+按
OCR 组重折）→ ocr_regroup_bands（大列重组）。
指标（均在归一化字符偏移空间，无需对齐——两侧同文本）：
  字符流不变   硬不变量（必须 100%）
  行界 F1      输出行折点 vs 金标行折点
  带界 F1      输出带界（\n\n）vs 金标带界
  得分         10 × 两 F1 均值（字符流破坏记 0）
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools/dataset"))
sys.path.insert(0, str(REPO / "tools/crawl"))
sys.path.insert(0, str(REPO / "tools/eval"))
import kangxi_page_tool as kpt  # noqa: E402
import kangxi_store  # noqa: E402
from eval_ocr_fold import gj_bands, PUNCT_STRIP  # noqa: E402

store = kangxi_store.KangxiStore()


def norm_offsets(bands):
    """带列表 → (总归一字数, 行界集, 带界集)（字符偏移空间）。"""
    line_b, band_b, acc = set(), set(), 0
    for b in bands:
        for l in b:
            acc += len("".join(ch for ch in l if ch not in PUNCT_STRIP))
            line_b.add(acc)
        band_b.add(acc)
    total = acc
    line_b.discard(total)
    band_b.discard(total)
    return total, line_b, band_b


def f1(a, b, tol=0):
    if not a and not b:
        return 1.0
    hit = sum(1 for x in a if any(abs(x - y) <= tol for y in b))
    p = hit / len(a) if a else 1.0
    r = hit / len(b) if b else 1.0
    return 2 * p * r / (p + r) if p + r else 0.0


def stream(bands):
    """规范化字符流：行首尾半角空白按转写惯例剔除（不占格）；全角空格保留（≡*）。"""
    return "".join(l.strip(" \t") for b in bands for l in b)


def run(page: int):
    gj = REPO / "kangxi-gold/annotations" / f"{page:04d}.gj"
    bands = [list(b) for b in gj_bands(gj)]
    in_desc = f"{len(bands)}带×{[len(b) for b in bands]}"

    folded, note = kpt.ocr_fold_page_lines(page, bands, store)
    regrouped, rnote = kpt.ocr_regroup_bands(page, folded)
    out_desc = f"{len(regrouped)}带×{[len(b) for b in regrouped]}"

    ok_stream = stream(bands) == stream(regrouped)
    _, gl, gb = norm_offsets(bands)
    _, ol, ob = norm_offsets(regrouped)
    lf1 = f1(ol, gl)
    bf1 = f1(ob, gb)
    score = 0.0 if not ok_stream else round(10 * (lf1 + bf1) / 2, 2)
    return dict(page=page, in_desc=in_desc, out_desc=out_desc, note=note,
                rnote=rnote, ok_stream=ok_stream, lf1=round(lf1, 3),
                bf1=round(bf1, 3), score=score,
                out=regrouped, gold=bands)


if __name__ == "__main__":
    show = [x for x in sys.argv[1:]] or None
    rows = [run(p) for p in [x for x in range(312, 336) if x != 329]]
    for r in rows:
        print(f"@{r['page']}  {r['score']:5.2f} | 输入 {r['in_desc']}"
              f" → 输出 {r['out_desc']} | 行界F1 {r['lf1']:.3f} 带界F1 {r['bf1']:.3f}"
              f" | 字符流 {'✓' if r['ok_stream'] else '✗✗✗'}")
        print(f"      {r['note']}；{r['rnote']}")
    scores = [r["score"] for r in rows]
    print(f"\n均值 {sum(scores)/len(scores):.2f}；满分(≥9.9) "
          f"{sum(1 for s in scores if s >= 9.9)} 页；字符流 {sum(r['ok_stream'] for r in rows)}/23")
    if show:
        for r in rows:
            if r["page"] in [int(s) for s in show]:
                print(f"\n===== @{r['page']} 输入（金标）=====")
                for b in r["gold"]:
                    print("  「" + " / ".join(b) + "」")
                print(f"===== @{r['page']} 输出 =====")
                for b in r["out"]:
                    print("  「" + " / ".join(b) + "」")
