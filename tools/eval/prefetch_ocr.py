#!/usr/bin/env python3
"""预识别：对已爬取到本地的页面批量跑 PaddleOCR，结果持久缓存到本地。

添加新页时 kangxi_page_tool 的 OCR 裁剪/折行优先读本缓存，未命中才提交
新 job——新页 OCR 等待从 ~40s+（冷启动/排队）降为 0（命中时零联网）。

服务调用/缓存写入/图定位消费 kangxi_page_tool 公开函数
（page_ocr / ocr_cache_valid / page_image），
本脚本只保留批量编排：限速、--force、todo 集合构造。
--pages 显式指定的页走 page_image 定位（store ∪ manifest）——直接下载
入库的 312–328 页也可预取（原版只认 store scan 行，一律「无扫描图」跳过，
这些页的缓存永远补不上）。

缓存位置：var/ocr-cache/<page:04d>.json
  {page, sha256, fetched_at, markdown}（sha256 与扫描图绑定，图变则失效重跑）
  空值和残缺结果视为失败，不写成功缓存，后续可以重试。

用法：
  python3 tools/eval/prefetch_ocr.py [--pages 335-360] [--limit N] [--force]
  python3 scripts/prefetch_ocr.py --all          # 全部已爬页（581 页，量大慎用）
默认：数据集中已有页的「下一页起」未缓存页（即近期将要添加的页）。
仅依赖标准库；OCR 经本地 paddleocr-baseline 服务（127.0.0.1:8010）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "crawl"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paths  # noqa: E402
import kangxi_store  # noqa: E402
from kangxi_page_tool import ocr_cache_valid as cache_valid, page_ocr

REPO = paths.REPO_ROOT
CACHE_DIR = paths.OCR_CACHE_DIR
MANIFEST = REPO / "kangxi-gold" / "manifest.json"


def dataset_last_page() -> int:
    if MANIFEST.exists():
        pages = json.loads(MANIFEST.read_text(encoding="utf-8")).get("pages") or []
        if pages:
            return max(p["page"] for p in pages)
    return 311


def parse_pages_arg(value: str | None) -> list[int] | None:
    if value is None:
        return None
    out: list[int] = []
    for part in value.split(","):
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", help="页码，如 335-360 或 335,340；默认=数据集末页起的未缓存已爬页")
    ap.add_argument("--all", action="store_true", help="全部已爬页（581 页，量大慎用）")
    ap.add_argument("--limit", type=int, default=20, help="本次最多处理页数（默认 20）")
    ap.add_argument("--force", action="store_true", help="忽略有效缓存强制重跑")
    args = ap.parse_args()

    store = kangxi_store.KangxiStore(readonly=True)
    with store._conn() as conn:
        crawled = sorted(
            r[0] for r in conn.execute("SELECT page FROM pages WHERE scan_sha256 IS NOT NULL")
        )
    if args.all:
        todo = crawled
    elif args.pages:
        todo = parse_pages_arg(args.pages)
    else:
        last = dataset_last_page()
        todo = [p for p in crawled if p > last]
    todo = [p for p in todo if args.force or not cache_valid(p, store)]
    todo = todo[: args.limit]
    if not todo:
        print("✓ 没有待预识别的页面。")
        return 0

    print(f"待预识别 {len(todo)} 页：@{todo[0]}–@{todo[-1]}" if len(todo) > 1 else f"待预识别 1 页：@{todo[0]}")
    ok = fail = 0
    for n, page in enumerate(todo, 1):
        time.sleep(1.2)  # 对上游礼貌限速
        try:
            md = page_ocr(page, store=store, force=args.force)
        except Exception as e:  # noqa: BLE001 —— 单页失败不终止批次
            print(f"[{n}/{len(todo)}] @{page} ✗ {e}", flush=True)
            fail += 1
            continue
        if md is None:
            print(f"[{n}/{len(todo)}] @{page} ✗ 识别失败或正文残缺，下次可重试", flush=True)
            fail += 1
            continue
        ok += 1
        print(f"[{n}/{len(todo)}] @{page} ✓ {len(md)} 字符", flush=True)

    print(f"完成：成功 {ok} / 失败 {fail}；缓存目录 {CACHE_DIR}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
