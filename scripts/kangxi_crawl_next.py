#!/usr/bin/env python3
"""增量爬取「下一页」完整数据：阅读页 + 原图 + 页→字头索引 + 该页全部字头详情。

供定时任务（每 10 分钟一页）慢速抓全全书用。配合 kangxi_store 去重：
- 页选择：从 --from-page 起取最小的未完成页（缺阅读页或原图），已完成的自动跳过；
- 字头详情只补该页缺失的码位，重复零网络；
- 全部 7738 页完成时打印 ALL_DONE 并以退出码 42 结束（定时任务据此暂停）。

用法：
  python3 kangxi_crawl_next.py [--db PATH] [--images-dir DIR] [--entries-dir DIR] [--from-page N]
仅依赖标准库。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import fetch_kangxi_entry as fe
import fetch_kangxi_page as fp
import kangxi_store

REPO_ROOT = Path(__file__).resolve().parents[1]
FALLBACK_IMAGES_DIR = REPO_ROOT / "datasets" / "kangxi-crawl" / "pages"
FALLBACK_ENTRIES_DIR = REPO_ROOT / "datasets" / "kangxi-crawl" / "entries"


def pick_dir(preferred: Path | None, fallback: Path, label: str) -> Path:
    """优先用外置盘目录，未挂载则回退仓库内目录；返回前确保目录存在。"""
    if preferred is not None:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    if fp.DEFAULT_OUT_DIR.parent.is_dir():  # WD-2T 已挂载
        wd = fp.DEFAULT_OUT_DIR if label == "images" else Path(
            "/Volumes/WD-2T/guji-ocr/datasets/kangxizidian-entries")
        wd.mkdir(parents=True, exist_ok=True)
        return wd
    print(f"⚠ WD-2T 未挂载，{label} 回退到 {fallback}")
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def crawl_next_page(store: kangxi_store.KangxiStore, images_dir: Path, entries_dir: Path,
                    from_page: int = 1, order: str = "random") -> int:
    """抓取下一个未完成页（页 + 该页缺失字头详情）。

    order：random = 在未完成页中均匀随机选（默认）；sequential = 取最小未完成页。
    返回：0 成功；1 该页抓取失败（下轮重新选页）；42 全部完成。
    """
    pick = store.random_missing_page if order == "random" else store.next_missing_page
    page = pick(from_page)
    if page is None:
        print("ALL_DONE：全部页已完整入库（阅读页 + 原图）")
        return 42

    print(f"下一页：{page:04d}")
    if not fp.fetch_page(page, images_dir, store, save_html=False, force=False):
        print(f"页 {page:04d} 抓取失败", file=sys.stderr)
        return 1

    chars = store.coded_chars_missing_entries(page)
    failed = []
    for ch in chars:
        if not fe.fetch_entry(ch, entries_dir, store, save_html=False, force=False):
            failed.append(ch)
    ok = len(chars) - len(failed)
    print(f"页 {page:04d} 完成：阅读页+原图+索引入库，字头详情 {ok}/{len(chars)}"
          + (f"，失败：{failed}" if failed else ""))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=kangxi_store.DEFAULT_DB,
                    help=f"SQLite 库路径（默认 {kangxi_store.DEFAULT_DB}）")
    ap.add_argument("--images-dir", type=Path, default=None,
                    help="原图目录（默认 WD-2T，未挂载时回退 datasets/kangxi-crawl/pages）")
    ap.add_argument("--entries-dir", type=Path, default=None,
                    help="详情 JSON 副本目录（默认 WD-2T，未挂载时回退 datasets/kangxi-crawl/entries）")
    ap.add_argument("--from-page", type=int, default=1, help="起始页码（默认 1）")
    ap.add_argument("--order", choices=["random", "sequential"], default="random",
                    help="选页策略：random 未完成页中均匀随机（默认）；sequential 最小未完成页")
    args = ap.parse_args()

    store = kangxi_store.KangxiStore(args.db)
    fp.check_robots()  # 禁止即 sys.exit(2)
    images_dir = pick_dir(args.images_dir, FALLBACK_IMAGES_DIR, "images")
    entries_dir = pick_dir(args.entries_dir, FALLBACK_ENTRIES_DIR, "entries")

    rc = crawl_next_page(store, images_dir, entries_dir, args.from_page, args.order)
    if rc == 0:
        print(json.dumps(store.stats(), ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())
