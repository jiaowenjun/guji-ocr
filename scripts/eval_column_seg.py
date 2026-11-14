#!/usr/bin/env python3
"""列分割 × 初校金标 逐页验证：金标行→小列 单调分配（DP），按列残差评分。

用法：python3 scripts/eval_column_seg.py [-v]
评分口径（10 分制，2026-11-14 首轮结果见 docs/research/ 报告「列分割逐页验证」节）：
  金标行按阅读序单调分配到 16 小列（允许首/尾空列=金标未转写的字头/前部尾区，
  DP 最小化 Σ|chars_est − 段字数|）；
  正文列残差 ≤2 好 / ≤4 近 / >4 坏；wide 字头列（chars_est 设计上不可靠）≤6/≤8；
  未分配且有墨的列=「未覆盖」不按坏列扣分（每列 −0.25，cap 1）；
  扣分：覆盖列总偏差 >8% −2、>4% −1；坏列各 −0.5（cap 4）；近列各 −0.25（cap 2）。
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from kangxi_column_seg import segment  # noqa: E402
from eval_ocr_fold import gj_bands, norm  # noqa: E402


def assign_lines(lens, ests):
    """金标行单调分配到列，min Σ|ests[j] − 段和|；允许前导/尾随空列。

    返回每列的行区间 (i,k)；空列=(0,0) 或 None（未到达）。"""
    m, n = len(lens), len(ests)
    INF = float("inf")
    pre = [0]
    for l in lens:
        pre.append(pre[-1] + l)

    def seg(i, j):
        return pre[j] - pre[i]

    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for j in range(1, n + 1):
        dp[j][0] = dp[j - 1][0] + ests[j - 1]  # 前导空列
        back[j][0] = 0
        for k in range(1, m + 1):
            best, arg = INF, None
            for i in range(k - 1, -1, -1):
                if dp[j - 1][i] == INF:
                    continue
                c = dp[j - 1][i] + abs(ests[j - 1] - seg(i, k))
                if c < best:
                    best, arg = c, i
            dp[j][k] = best
            back[j][k] = arg
    best, bj = INF, None
    for j in range(1, n + 1):  # 尾随空列
        tail = sum(ests[x] for x in range(j, n))
        if dp[j][m] + tail < best:
            best, bj = dp[j][m] + tail, j
    ranges = [None] * n
    k, j = m, bj
    while j >= 1:
        i = back[j][k]
        ranges[j - 1] = (i, k)
        k, j = i, j - 1
    return ranges


def validate(page: int):
    res = segment(page)
    if "error" in res:
        return None
    cols = [m for maj in res["majors"] for m in maj["minors"]]
    wide_cols = {2 * j for j in range(8) if res["majors"][j]["kind"] == "wide"}
    ests = [m["chars_est"] for m in cols]

    lines = [l for b in gj_bands(REPO / "kangxi-gold/annotations" / f"{page:04d}.gj")
             for l in b]
    lens = [len(norm(l)) for l in lines]
    ranges = assign_lines(lens, ests)

    total_gold = sum(lens)
    covered = [(j, rng) for j, rng in enumerate(ranges) if rng and rng[1] > rng[0]]
    covered_est = sum(ests[j] for j, _ in covered)
    uncovered = sum(1 for j, rng in enumerate(ranges)
                    if (not rng or rng[1] == rng[0]) and ests[j] > 4)
    dev = (covered_est - total_gold) / max(total_gold, 1)

    good = near = bad = 0
    details = []
    for j, rng in covered:
        g = sum(lens[rng[0]:rng[1]])
        r = ests[j] - g
        tol, tol2 = (6, 8) if j in wide_cols else (2, 4)
        if abs(r) <= tol:
            good += 1
        elif abs(r) <= tol2:
            near += 1
            details.append((j, r, g, lines[rng[0]][:10]))
        else:
            bad += 1
            details.append((j, r, g, lines[rng[0]][:10]))

    score = 10.0
    if abs(dev) > 0.08:
        score -= 2
    elif abs(dev) > 0.04:
        score -= 1
    score -= min(4.0, bad * 0.5)
    score -= min(2.0, near * 0.25)
    score -= min(1.0, uncovered * 0.25)

    return dict(page=page, gold_lines=len(lines), total_gold=total_gold,
                covered_est=covered_est, dev=round(dev * 100, 1),
                good=good, near=near, bad=bad, uncovered=uncovered,
                wide=sorted(wide_cols), evidence=res["lines_evidence"],
                pitch=res["pitch"], score=round(max(0, score), 2),
                details=details)


if __name__ == "__main__":
    verbose = "-v" in sys.argv
    pages = [p for p in range(312, 336) if p != 329]
    rows = [r for r in (validate(p) for p in pages) if r]
    for r in rows:
        print(f"@{r['page']}  {r['score']:5.2f} 分 | 金标行 {r['gold_lines']:2d} 字 {r['total_gold']:3d} "
              f"| 覆盖列est {r['covered_est']:3d} 偏差 {r['dev']:+.1f}% | 列 好{r['good']}/近{r['near']}/坏{r['bad']}"
              f" 未覆盖{r['uncovered']} | wide {r['wide'] or '-'} 证据 {r['evidence']}")
        if verbose:
            for j, resd, g, txt in r["details"]:
                print(f"     列{j}(右起第{j+1}列) 残差 {resd:+d}（金标 {g} 字）首行『{txt}』")
    scores = [r["score"] for r in rows]
    print(f"\n均值 {sum(scores)/len(scores):.2f}，中位 {sorted(scores)[len(scores)//2]:.2f}，"
          f"≥9 分 {sum(1 for s in scores if s >= 9)} 页，<8 分 {sum(1 for s in scores if s < 8)} 页")
