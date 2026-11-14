#!/usr/bin/env python3
"""初校规范统一（保守拆分版）：带=大列。

只拆分「跨多个大列」的人工带（在 DP 定位的大列界处切开），绝不移动
已有带界、绝不动任何行内容——根除 C 类「变体区人工合并带」与自动
重组的多断带差异（17 对）。dry-run 打印计划，--apply 写回并重建
json/txt。
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools/eval"))
from kangxi_column_seg import segment, assign_lines  # noqa: E402

PUNCT_STRIP = "。，·\"：:、；《》【】*　 \t\n\r〇○●"


def norm(s):
    return "".join(ch for ch in s if ch not in PUNCT_STRIP)


def parse_gj(path):
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    at = next(i for i, l in enumerate(lines) if l.strip().startswith("@"))
    head = lines[: at + 1]
    body = [l for l in lines[at + 1:]]
    # 还原带（保持原行序，含 # / // 行）
    bands, cur = [], []
    for l in body:
        if l.strip():
            cur.append(l)
        elif cur:
            bands.append(cur)
            cur = []
    if cur:
        bands.append(cur)
    return head, bands


def major_breaks(page, n_lines):
    """DP 定位的大列界（行号空间：界 b = 行 [*, b) 属大列 k、[b,*) 属 k+1）。"""
    res = segment(page)
    if "error" in res:
        return None, res["error"]
    ests = [m["chars_est"] for maj in res["majors"] for m in maj["minors"]]
    lens = [len(norm(l)) for l in ALL_LINES[page]]
    ranges = assign_lines(lens, ests)
    breaks = set()
    for k in range(7):
        rng = ranges[2 * k + 1]
        if rng and rng[1] > rng[0]:
            breaks.add(rng[1])
    return breaks, None


ALL_LINES: dict[int, list[str]] = {}


def unify(page, apply_changes):
    path = REPO / "kangxi-gold/annotations" / f"{page:04d}.gj"
    head, bands = parse_gj(path)
    ALL_LINES[page] = [l for b in bands for l in b]
    breaks, err = major_breaks(page, len(ALL_LINES[page]))
    if breaks is None:
        return None, f"分割不可用：{err}"
    # 逐带检查：带 [i,j) 内部的大列界 → 拆分
    pos = 0
    new_bands, plan = [], []
    for b in bands:
        i, j = pos, pos + len(b)
        # 只接受产生 ≥2 行段的刀：1 行碎段=变体区 DP 边界 ±1 伪影，保留人工原状
        cuts = []
        prev = i
        for c in sorted(x for x in breaks if i < x < j):
            if c - prev >= 2 and j - c >= 2:
                cuts.append(c)
                prev = c
        if cuts:
            prev = i
            for c in cuts:
                new_bands.append(ALL_LINES[page][prev:c])
                plan.append((prev, c))
                prev = c
            new_bands.append(ALL_LINES[page][prev:j])
            plan.append((prev, j))
        else:
            new_bands.append(b)
        pos = j
    assert [l for b in new_bands for l in b] == ALL_LINES[page]
    return (head, bands, new_bands, plan), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    changed = []
    for p in [x for x in range(312, 336) if x != 329]:
        r, err = unify(p, args.apply)
        if err:
            print(f"@{p}: 跳过（{err}）")
            continue
        head, old, new, plan = r
        if [len(b) for b in old] == [len(b) for b in new]:
            continue
        changed.append(p)
        print(f"@{p}: {[len(b) for b in old]} → {[len(b) for b in new]}（{len(new) - len(old)} 刀：{plan}）")
        if args.apply:
            parts = list(head)
            for b in new:
                parts.append("")
                parts.extend(b)
            (REPO / "kangxi-gold/annotations" / f"{p:04d}.gj").write_text(
                "\n".join(parts).rstrip() + "\n", encoding="utf-8")
    print(f"\n共 {len(changed)} 页变更：{changed}")
    if args.apply and changed:
        subprocess.run(["npx", "-y", "tsx",
                        str(REPO / "kangxi-gold/scripts/build_annotations.ts"),
                        "--allow-drift"], check=True, cwd=REPO)


if __name__ == "__main__":
    main()
