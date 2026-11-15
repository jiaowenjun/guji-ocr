#!/usr/bin/env python3
"""预识别：对已爬取到本地的页面批量跑 PaddleOCR，结果持久缓存到本地。

添加新页时 kangxi_page_tool 的 OCR 裁剪/折行优先读本缓存，未命中才提交
新 job——新页 OCR 等待从 ~40s+（冷启动/排队）降为 0（命中时零联网）。

服务调用/缓存写入/图定位消费 kangxi_page_tool 公开函数
（ocr_service_up / ocr_submit_markdown / ocr_cache_write / page_image），
本脚本只保留批量编排：限速、--force、哨兵跳过、todo 集合构造。
--pages 显式指定的页走 page_image 定位（store ∪ manifest）——直接下载
入库的 312–328 页也可预取（原版只认 store scan 行，一律「无扫描图」跳过，
这些页的缓存永远补不上）。

缓存位置：var/ocr-cache/<page:04d>.json
  {page, sha256, fetched_at, markdown}（sha256 与扫描图绑定，图变则失效重跑）
  以及零文本哨兵 {"markdown": ""}（避免无文本页反复提交）。

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
from kangxi_page_tool import (  # noqa: E402
    ocr_cache_write,
    ocr_service_up,
    ocr_submit_markdown,
    page_image,
)

REPO = paths.REPO_ROOT
CACHE_DIR = paths.OCR_CACHE_DIR
MANIFEST = REPO / "kangxi-gold" / "manifest.json"


def cache_entry(page: int) -> dict | None:
    f = CACHE_DIR / f"{page:04d}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def cache_valid(page: int) -> bool:
    """缓存存在且 sha256 与当前扫描图一致（图变即失效）。

    图 sha 走 page_image 口径（store scan_file → manifest 回退），与
    ocr_cache_write 写入侧同源——manifest 直接入库页的校验不再恒失效。
    """
    entry = cache_entry(page)
    if entry is None or not entry.get("sha256"):
        return False
    img = page_image(page)
    return img is not None and entry["sha256"] == img.sha256


def ocr_one(page: int) -> tuple[str | None, str]:
    """提交单页并返回 (markdown, note)；None = 失败，"" = 无文本（哨兵）。"""
    img = page_image(page)
    if img is None:
        return None, "无扫描图"
    md = ocr_submit_markdown(img.path.read_bytes(), img.path.name)
    if md is None:
        return None, "提交/轮询失败或超时"
    return md, "ok"


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

    if not ocr_service_up():
        print("✗ paddleocr-baseline 服务未运行（127.0.0.1:8010）。先启动：", file=sys.stderr)
        print("  cd paddleocr-baseline && OCR_TOKEN=<token> .venv/bin/python -m paddleocr_baseline", file=sys.stderr)
        return 2

    store = kangxi_store.KangxiStore()
    with store._conn() as conn:
        crawled = sorted(
            r[0] for r in conn.execute("SELECT page FROM pages WHERE scan_sha256 IS NOT NULL")
        )
    if not crawled:
        print("库内无已爬页面。", file=sys.stderr)
        return 1

    if args.all:
        todo = crawled
    elif args.pages:
        wanted = parse_pages_arg(args.pages)
        todo = [p for p in wanted if page_image(p) is not None]  # store ∪ manifest
        missing = [p for p in wanted if p not in set(todo)]
        if missing:
            print(f"提示：{len(missing)} 页无扫描图（未爬取且不在数据集，跳过）：@{missing[:10]}{'…' if len(missing) > 10 else ''}")
    else:
        last = dataset_last_page()
        todo = [p for p in crawled if p > last and not cache_valid(p)]
    todo = [p for p in todo if args.force or not cache_valid(p)]
    todo = todo[: args.limit]
    if not todo:
        print("✓ 没有待预识别的页面（缓存均有效）。")
        return 0

    print(f"待预识别 {len(todo)} 页：@{todo[0]}–@{todo[-1]}" if len(todo) > 1 else f"待预识别 1 页：@{todo[0]}")
    ok = no_text = fail = 0
    for n, page in enumerate(todo, 1):
        time.sleep(1.2)  # 对上游礼貌限速
        try:
            md, note = ocr_one(page)
        except Exception as e:  # noqa: BLE001 —— 单页失败不终止批次
            print(f"[{n}/{len(todo)}] @{page} ✗ {e}", flush=True)
            fail += 1
            continue
        if md is None:
            print(f"[{n}/{len(todo)}] @{page} ✗ {note}", flush=True)
            fail += 1
            continue
        ocr_cache_write(page, store, md)
        if md:
            ok += 1
            print(f"[{n}/{len(todo)}] @{page} ✓ {len(md)} 字符", flush=True)
        else:
            no_text += 1
            print(f"[{n}/{len(todo)}] @{page} ○ 无文本（哨兵已存，不再重复提交）", flush=True)

    print(f"完成：成功 {ok} / 无文本 {no_text} / 失败 {fail}；缓存目录 {CACHE_DIR}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
