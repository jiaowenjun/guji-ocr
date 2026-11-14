#!/usr/bin/env python3
"""初校真值 × 续文 OCR 裁剪 对照评估：ocr_trim_continuation 逐页验证。

用法：python3 scripts/eval_ocr_trim.py [-v] [--page N]
  -v 逐页打印边界上下文（裁点/真值末尾各 12 字）。
数据源：kangxi-gold/annotations/*.gj（初校真值）+ 生产代码路径
（kangxi_page_tool.continuation_from_prev → ocr_trim_continuation，OCR 走
持久缓存，服务不必运行）。

真值口径：本页 .gj 首个字头行（# 开头）之前的正文＝人工认定的本页续文；
纯延续页（无字头行）取全页。比较在 _norm 归一化坐标下进行（标点/折行差
异自然消解）。delta = 裁点 − 真值长度：>0 过裁（本页内容被推给下页），
<0 欠裁（下页内容留在了本页）。
"""
import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "crawl"))
import kangxi_page_tool as kpt  # noqa: E402
import kangxi_store  # noqa: E402

MANIFEST = kpt.MANIFEST
ANNOTATIONS = kpt.ANNOTATIONS


def gt_continuation(page: int) -> str:
    """真值：.gj 首个字头行之前的正文（跳过 // 注释行与 @页码行）。"""
    lines = (ANNOTATIONS / f"{page:04d}.gj").read_text(encoding="utf-8").splitlines()
    body = []
    for line in lines:
        s = line.strip()
        if s.startswith("@"):
            continue
        if s.startswith("#"):
            break  # 首个字头行即续文终点
        if s.startswith("//") or not s:
            continue
        body.append(line)
    return "".join(body)


def score(delta: int, trimmed_eq_full: bool) -> int:
    """10 分制：边界字数差打分；未执行裁剪等同未裁（delta 按全量算）。"""
    d = abs(delta)
    if d == 0:
        return 10
    if d <= 1:
        return 9
    if d <= 3:
        return 8
    if d <= 6:
        return 6
    if d <= 15:
        return 4
    if d <= 40:
        return 2
    return 1


def evaluate(store, page: int, verbose: bool = False) -> dict:
    r = {"page": page, "tag": "", "note": "", "score": None}
    cont, info = kpt.continuation_from_prev(page, store)
    gt_n = kpt._norm(gt_continuation(page))

    if info.get("skipped") or not cont:
        # 无续文两种情形：本页真值也确无续文（正常）；真值有而续入失败（续入问题）
        r["tag"] = "续入失败" if gt_n else "无续文"
        r["note"] = info.get("skipped") or "前页无溢出"
        r["gt_len"] = len(gt_n)
        return r

    trimmed, note = kpt.ocr_trim_continuation(page, cont, store)
    end, total, why = kpt.ocr_page_cut(page, "\n".join(cont), store)
    trim_n = kpt._norm("\n".join(trimmed))
    full_n = kpt._norm("\n".join(cont))
    assert trim_n == full_n[: len(trim_n)], "裁剪必须是前缀"

    delta = len(trim_n) - len(gt_n)
    r.update(
        cut=end, total=total, gt_len=len(gt_n), delta=delta,
        note=note, score=score(delta, len(trim_n) == len(full_n)),
    )
    if len(trim_n) == len(full_n):
        r["tag"] = "未裁剪" if len(gt_n) < len(full_n) else "全量即页界"
    else:
        r["tag"] = "过裁" if delta > 0 else ("欠裁" if delta < 0 else "精确")
    if verbose:
        r["ctx"] = {
            "cut_tail": trim_n[-12:],
            "gt_tail": gt_n[-12:],
            "gt_head_next": gt_n[len(trim_n): len(trim_n) + 12] if delta < 0 else "",
            "extra_kept": trim_n[len(gt_n): len(gt_n) + 12] if delta > 0 else "",
        }
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--page", type=int)
    ap.add_argument("--db", default=str(kangxi_store.DEFAULT_DB),
                    help="kangxi-crawl sqlite 路径（评估用副本，避免与爬虫互写）")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    store = kangxi_store.KangxiStore(args.db)
    pages = [p["page"] for p in manifest["pages"] if p["status"] == "first"]
    if args.page:
        pages = [p for p in pages if p == args.page]

    rows = []
    for page in pages:
        prev = ANNOTATIONS / f"{page - 1:04d}.gj"
        if not prev.exists():
            rows.append({"page": page, "tag": "跳过", "note": f"前页 {page - 1} 不在数据集"})
            continue
        rows.append(evaluate(store, page, args.v))

    scored = [r for r in rows if r.get("score") is not None]
    print(f"{'页':>4} {'标签':<6} {'裁点':>5} {'真值':>5} {'delta':>6}  得分  说明")
    for r in rows:
        cut = f"{r['cut']:>5}" if r.get("cut") is not None else "    -"
        gt = f"{r['gt_len']:>5}" if "gt_len" in r else "    -"
        dl = f"{r['delta']:>+6}" if "delta" in r else "     -"
        sc = f"{r['score']:>4}" if r.get("score") is not None else "   -"
        print(f"@{r['page']:<3} {r['tag']:<6} {cut} {gt} {dl} {sc}  {r['note']}")
        if args.v and "ctx" in r:
            for k, v in r["ctx"].items():
                if v:
                    print(f"      {k}: {v}")
    if scored:
        avg = sum(r["score"] for r in scored) / len(scored)
        exact = sum(1 for r in scored if r["delta"] == 0)
        print(f"\n计分页 {len(scored)}/{len(rows)}  均分 {avg:.2f}  精确 {exact} 页")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
