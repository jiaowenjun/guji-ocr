#!/usr/bin/env python3
"""康熙字典两套扫描图的页号互查：站点页号（pages/NNNN.jpg）↔ 原始图（pages_original/）。

对应规则（2026-11-18 实证，四锚点验证：站点 312=01_0006_L 一部起始、
1999=04_0107_R〔扒打〕、2000=04_0107_L〔扔…𢩯〕、7714=13_0166_L 備考馬部起始）：

1. 站点页号 N（1-7738，即 www.kangxizidian.com/v2/index2.php?page=N，亦等于
   词条「武英殿本」页号）每两页对应原始集的一个「开」（physical leaf）：
   开序 K = ⌈N/2⌉；N 奇数 = 该开右半（_R，先读），N 偶数 = 左半（_L，后读），
   合中式古籍「右先左后」翻页序。
2. 开序按目录卷序累加：00.总目→01.子集→…→12.亥集→13.补遗；卷内按文件名
   第二段页号升序；无后缀（plain，书衣/分隔/卷末叶）与 _L/_R 成对页各算一开。
   全书 3869 开 × 2 = 7738，与站点导航总数分毫不差。
3. plain 叶占两个站点页号，但本地只存一面（另一面站点另拍，如 01_0001 书衣
   对应站点 302，站点 301 为同开御製扉页）——plain 的两个站点页都映射到该文件。
4. 原始集与站点图为同版同源扫描（内容逐字头一致）；站点图缩放过且带页脚水印。
   「同文書局本」页号（词条 tongwen_edition，石印本 ~1631 页）是另一套版本
   页码，与两套图片均不对应，勿混用。

用法（自仓库根）：
  python3 tools/crawl/kangxi_page_map.py 2000            # 站点页号 → 原始图路径
  python3 tools/crawl/kangxi_page_map.py --to-site 04.卯集 0107 R   # 反向查询
  python3 tools/crawl/kangxi_page_map.py --table         # 全表（CSV 到 stdout）
  python3 tools/crawl/kangxi_page_map.py --verify        # 结构校验 + 已爬图路径核对
完整规则文档（含开序总表、plain 语义、验证记录）：docs/kangxi-page-mapping.md
仅依赖标准库。
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paths  # noqa: E402

ORIGINAL_DIR = paths.RAW_KANGXI_PAGES.parent / "pages_original"
SITE_TOTAL = 7738  # 站点导航「最後頁」
# 卷目录名仅取前缀数字即可稳定排序（中文名随系统locale不稳）
_NAME_RE = re.compile(r"^(?P<vol>\d{2})_(?P<page>\d{4})(?P<half>_L|_R)?$")


def build_spreads(original_dir: Path = ORIGINAL_DIR) -> list[dict]:
    """按卷序/页号升序展开为全局开表；每开 = {vol_dir, vol, page, kind, files}。

    kind：plain = 无后缀单图；pair = _L+_R 两半。缺失的半页文件记 None（不抹掉开）。
    """
    vols = sorted(d for d in original_dir.iterdir() if d.is_dir())
    if not vols:
        sys.exit(f"原始图目录为空或不存在：{original_dir}")
    spreads: list[dict] = []
    for vd in vols:
        by_page: dict[int, dict] = {}
        for f in vd.iterdir():
            m = _NAME_RE.match(f.stem)  # stem 避开 .jpg；._* AppleDouble 自然不匹配
            if not m or f.suffix.lower() != ".jpg":
                continue
            p = int(m.group("page"))
            half = m.group("half")
            slot = by_page.setdefault(p, {"vol_dir": vd.name, "vol": m.group("vol"),
                                          "page": p, "L": None, "R": None, "plain": None})
            if half == "_L":
                slot["L"] = f
            elif half == "_R":
                slot["R"] = f
            else:
                slot["plain"] = f
        for p in sorted(by_page):
            s = by_page[p]
            kind = "plain" if s["plain"] else "pair"
            spreads.append({"vol_dir": s["vol_dir"], "vol": s["vol"], "page": p,
                            "kind": kind, "L": s["L"], "R": s["R"], "plain": s["plain"]})
    return spreads


def site_to_spread(n: int) -> tuple[int, str]:
    """站点页号 → (全局开序 K[1基], 半页 'L'/'R')；奇数页先读右半。"""
    if not 1 <= n <= SITE_TOTAL:
        sys.exit(f"站点页号须在 1-{SITE_TOTAL} 内：{n}")
    return (n + 1) // 2, "R" if n % 2 else "L"


def site_to_original(n: int, spreads: list[dict]) -> Path:
    """站点页号 → 原始图路径。plain 开：L/R 都返回该单图。"""
    k, half = site_to_spread(n)
    s = spreads[k - 1]
    if s["kind"] == "plain":
        assert s["plain"] is not None
        return s["plain"]
    f = s[half]
    if f is None:  # 半页文件缺失（理论上不存在，verify 会查）
        sys.exit(f"站点 {n} → {s['vol_dir']} {s['page']:04d}_{half} 文件缺失")
    return f


def original_to_site(vol_dir: str, page: int, half: str, spreads: list[dict]) -> int:
    """原始图（卷目录名 + 页号 + 'L'/'R'/plain）→ 站点页号。"""
    for i, s in enumerate(spreads, start=1):
        if s["vol_dir"] == vol_dir and s["page"] == page:
            if s["kind"] == "plain":
                return 2 * i - 1 if half.upper() == "R" else 2 * i
            return 2 * i - (1 if half.upper() == "R" else 0)
    sys.exit(f"未找到 {vol_dir} 页 {page:04d}")


def verify(spreads: list[dict]) -> int:
    """三重校验：总数守恒、双射、已爬站点图逐张能落到存在的原始文件。"""
    n_spread = len(spreads)
    err = 0
    if n_spread * 2 != SITE_TOTAL:
        print(f"✗ 开数 {n_spread} × 2 ≠ 站点总数 {SITE_TOTAL}")
        err += 1
    else:
        print(f"✓ {n_spread} 开 × 2 = {SITE_TOTAL}，与站点总数一致")
    if sum(1 for s in spreads if s["kind"] == "pair" and (s["L"] is None or s["R"] is None)):
        print("✗ 存在只有单半的 _L/_R 开")
        err += 1
    else:
        plains = sum(1 for s in spreads if s["kind"] == "plain")
        files = plains + 2 * (n_spread - plains)  # 盘上文件：plain 1 张，对页 2 张
        print(f"✓ {plains} plain（盘上 1 张、占 2 页号）+ {n_spread - plains} 对 L/R，"
              f"文件 {files} 张、页号 {SITE_TOTAL} 个，映射满射无空洞")
    images = sorted(p for p in paths.RAW_KANGXI_PAGES.glob("*.jpg")
                    if not p.name.startswith("._"))
    miss = [p for p in images if not site_to_original(int(p.stem), spreads).exists()]
    if miss:
        print(f"✗ {len(miss)} 张已爬图映射到不存在的原始文件，如 "
              f"{[p.name for p in miss[:5]]}")
        err += 1
    else:
        print(f"✓ 已爬 {len(images)} 张站点图全部映射到存在的原始文件")
    # 内容锚点（page_chars 首字 vs 已目视核验页，勿改：回归基准）
    anchors = {312: ("01.子集", 6, "L"), 1999: ("04.卯集", 107, "R"),
               2000: ("04.卯集", 107, "L"), 7714: ("13.补遗", 166, "L")}
    db = sqlite3.connect(paths.REPO_ROOT / "var/crawl/kangxi-crawl.sqlite3")
    for n, (vd, pg, half) in anchors.items():
        chars = [r[0] for r in db.execute(
            "SELECT char FROM page_chars WHERE page=? ORDER BY ord", (n,)) if r[0]]
        k, h = site_to_spread(n)
        s = spreads[k - 1]
        ok = (s["vol_dir"] == vd and s["page"] == pg
              and (s["kind"] == "plain" or h == half))
        print(f"{'✓' if ok else '✗'} 锚点 站点{n}（{''.join(chars[:3]) or '无字头'}…）"
              f" → {vd} {pg:04d}_{half if s['kind'] != 'plain' else 'plain'}")
        err += 0 if ok else 1
    return err


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("site_page", nargs="?", type=int, help="站点页号（1-7738）")
    ap.add_argument("--to-site", nargs=3, metavar=("卷目录", "页号", "L/R/plain"),
                    help="反向查询：如 04.卯集 0107 R")
    ap.add_argument("--table", action="store_true", help="输出全表 CSV")
    ap.add_argument("--verify", action="store_true", help="结构与锚点校验")
    args = ap.parse_args()

    spreads = build_spreads()
    if args.verify:
        return 1 if verify(spreads) else 0
    if args.table:
        w = csv.writer(sys.stdout)
        w.writerow(["site_page", "half", "volume_dir", "orig_page", "orig_kind",
                    "orig_file"])
        for n in range(1, SITE_TOTAL + 1):
            k, h = site_to_spread(n)
            s = spreads[k - 1]
            f = s["plain"] if s["kind"] == "plain" else s[h]
            w.writerow([n, h if s["kind"] != "plain" else f"{h}(plain)",
                        s["vol_dir"], f"{s['page']:04d}", s["kind"],
                        f.relative_to(ORIGINAL_DIR) if f else "MISSING"])
        return 0
    if args.to_site:
        vd, pg, half = args.to_site
        n = original_to_site(vd, int(pg), half, spreads)
        print(n)
        return 0
    if args.site_page:
        n = args.site_page
        k, h = site_to_spread(n)
        s = spreads[k - 1]
        print(f"站点 {n}（第 {k} 开{'右半(先读)' if h == 'R' else '左半(后读)'}）→ "
              f"{s['vol_dir']} 第 {s['page']:04d} 开"
              f"（{'plain 单图' if s['kind'] == 'plain' else h + ' 半页'}）")
        print(site_to_original(n, spreads))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
