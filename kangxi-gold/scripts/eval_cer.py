#!/usr/bin/env python3
"""严格 CER 评测：kangxi-gold 金标 TXT vs OCR 输出文本。

对接 paddleocr-baseline 批量输出约定（batch_ocr.py 每图产出 <stem>.md），
图片名为 NNNN.jpg → OCR 文件 NNNN.md，页码即 int(stem)。

清洗规则（对参考与预测两侧施加同一函数，见 docs/research/README.md §11.3）：
  - 去除所有空白；
  - 去除显式列出的标点集（金标侧解析器已剔除 。，·":：、《》，
    扩展集覆盖 OCR 常见全/半角标点与书名框括号，两侧同样处理）；
  - 不做任何 Unicode 归一化、繁简转换或大小写折叠——繁简异体差别保留（严格 CER）。

指标：CER = (S+D+I)/N，Levenshtein 对齐分项计数；微平均 CER = Σ(S+D+I)/ΣN；
页均 CER；缺失/空输出的页按全删（D=N）计入，不剔除失败页。

用法：
  python3 -I eval_cer.py --ocr-dir <目录> [--gold-dir kangxi-gold/annotations] [--json OUT]
  python3 -I eval_cer.py --self-test
退出码：0 评测完成；2 用法错误。仅依赖标准库。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD = REPO_ROOT / "kangxi-gold" / "annotations"

# 金标侧解析器剔除集（split-line.ts）+ OCR 输出常见标点（含书名框括号【】与圈号）
PUNCT = (
    '。，、·：:；;！!？?，．.'  # 通用句读
    '「」『』《》〈〉【】[]()（）〈〉'  # 括号/书名框
    '"\'""''‘’“”"'  # 引号
    "…—―-～·＊*○◎〇"  # 省略/破折/着重/空格标记/圈号
)


def clean(s: str) -> str:
    return "".join(ch for ch in s if not ch.isspace() and ch not in PUNCT)


def align(ref: str, hyp: str):
    """Levenshtein 对齐，返回 (S, D, I)。全矩阵 + 回溯，页级千字内无压力。"""
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = min(
                dp[i - 1][j] + 1,  # 删除
                dp[i][j - 1] + 1,  # 插入
                dp[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]),  # 替换/相同
            )
    s = d = ins = 0
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            if ref[i - 1] != hyp[j - 1]:
                s += 1
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            d += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return s, d, ins


def ir_reference(path: Path) -> str:
    """从 Guji IR（NNNN.json）抽取阅读序文本并按文档自带 profile 清洗。

    与 irPageToText（guji-preview-grid/src/ir/text.ts）同构：大行一行；
    标题/字头/注文/书名同序；跨行书名只计入属本行的 part。"""
    doc = json.loads(path.read_text(encoding="utf-8"))
    profile = doc.get("meta", {}).get("profile", {})
    strip = set(profile.get("stripPunct", []))
    norm = {a: b for a, b in profile.get("normalize", [])}

    def clean(s: str) -> str:
        for a, b in norm.items():
            s = s.replace(a, b)
        return "".join(ch for ch in s if ch not in strip)

    lines = []
    for page in doc.get("pages", []):
        for band in page.get("bands", []):
            if "heading" in band:
                lines.append(clean(band["heading"]["text"]))
                continue
            parts = []
            for seg in band.get("segments", []):
                kind = seg.get("kind")
                if kind == "head":
                    parts.append(seg.get("char", ""))
                elif kind in ("text", "mark"):
                    parts.append(clean(seg.get("text", "")))
                elif kind == "book":
                    for p in seg.get("parts", []):
                        if not p.get("band") or p.get("band") == band.get("id"):
                            parts.append("".join(clean(x) for x in p.get("text", "").split("\n")))
            lines.append("".join(parts))
    return "\n".join(lines) + "\n" if lines else ""


def evaluate(gold_dir: Path, ocr_dir: Path, from_ir: bool = False):
    pattern = "*.json" if from_ir else "*.txt"
    gold_pages = {int(p.stem): p for p in sorted(gold_dir.glob(pattern)) if p.stem.isdigit()}
    if not gold_pages:
        sys.exit(f"2 金标目录无 NNNN.{ 'json' if from_ir else 'txt' }：{gold_dir}")
    rows = []
    for page, gold_path in sorted(gold_pages.items()):
        ref = clean(ir_reference(gold_path) if from_ir else gold_path.read_text(encoding="utf-8"))
        md = ocr_dir / f"{page:04d}.md"
        status = "ok"
        if not md.is_file():
            hyp, status = "", "missing"
        else:
            hyp = clean(md.read_text(encoding="utf-8"))
            if not hyp:
                status = "empty"
        s, d, i = align(ref, hyp) if hyp else (0, len(ref), 0)
        rows.append(
            {
                "page": page,
                "status": status,
                "n_ref": len(ref),
                "n_hyp": len(hyp),
                "S": s,
                "D": d,
                "I": i,
                "cer": (s + d + i) / len(ref) if ref else 0.0,
            }
        )
    return rows


def self_test() -> int:
    cases = [
        ("一二三四五", "一二三四五", (0, 0, 0)),
        ("一二三四五", "一二X四五", (1, 0, 0)),  # 替换
        ("一二三四五", "一二三四", (0, 1, 0)),  # 删除
        ("一二三四五", "一二三四五六", (0, 0, 1)),  # 插入
        ("一二三四五", "", (0, 5, 0)),  # 空输出=全删
        ("道立於一", "道立於壹", (1, 0, 0)),  # 异体不归并→记替换
        ("唐韻韻會", "【唐韻】\n【韻會】，", (0, 0, 0)),  # 标点/空白/书名框清洗
    ]
    failed = 0
    for ref, hyp, want in cases:
        got = align(clean(ref), clean(hyp))
        ok = got == want
        failed += 0 if ok else 1
        print(f"{'✓' if ok else '✗'} ref={ref!r} hyp={hyp!r} → S/D/I={got}（期望 {want}）")
    print("自测" + ("通过" if not failed else f"失败 {failed} 例"))
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold-dir", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("--ocr-dir", type=Path)
    ap.add_argument("--from-ir", action="store_true",
                    help="参考文本取 NNNN.json（Guji IR，含自带 profile）而非 NNNN.txt")
    ap.add_argument("--json", type=Path, help="机器可读结果输出路径")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.ocr_dir:
        ap.error("需要 --ocr-dir（或 --self-test）")

    rows = evaluate(args.gold_dir, args.ocr_dir, from_ir=args.from_ir)
    total_n = sum(r["n_ref"] for r in rows)
    total_ops = sum(r["S"] + r["D"] + r["I"] for r in rows)
    micro = total_ops / total_n if total_n else 0.0
    macro = sum(r["cer"] for r in rows) / len(rows) if rows else 0.0
    failures = [r for r in rows if r["status"] != "ok"]

    print(f"{'页':>4} {'状态':>7} {'N':>4} {'S':>4} {'D':>4} {'I':>4} {'CER':>7}")
    for r in rows:
        print(f"{r['page']:>4} {r['status']:>7} {r['n_ref']:>4} {r['S']:>4} {r['D']:>4} {r['I']:>4} {r['cer']:>7.4f}")
    print("-" * 44)
    print(f"微平均 CER = {total_ops}/{total_n} = {micro:.4f}    页均 CER = {macro:.4f}")
    if failures:
        print(f"失败页（missing/empty，按全删计）：{', '.join(str(r['page']) for r in failures)}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {"micro_cer": micro, "mean_page_cer": macro, "total_ref_chars": total_n, "pages": rows},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
