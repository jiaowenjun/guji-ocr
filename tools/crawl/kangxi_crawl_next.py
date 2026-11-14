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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paths  # noqa: E402

import fetch_kangxi_entry as fe
import fetch_kangxi_page as fp
import kangxi_log
import kangxi_store
import kangxi_svg_cache

WD_DIRS = {  # WD-2T 上各类落盘目录（统一见 tools/paths.py；未挂载即退出，不回退）
    "images": paths.RAW_KANGXI_PAGES,
    "entries": paths.RAW_KANGXI_ENTRIES,
    "svg": paths.RAW_KANGXI_SVG,
}


def pick_dir(preferred: Path | None, label: str) -> Path:
    """采集落盘目录：CLI 覆盖优先，否则用外置盘目录；外置盘未挂载直接退出。"""
    if preferred is not None:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    paths.require_wd(label)
    wd = WD_DIRS[label]
    wd.mkdir(parents=True, exist_ok=True)
    return wd


def crawl_next_page(store: kangxi_store.KangxiStore, images_dir: Path, entries_dir: Path,
                    from_page: int = 1, order: str = "random",
                    svg_dir: Path | None = None) -> int:
    """抓取下一个未完成页（页 + 该页缺失字头详情）。

    order：random = 在未完成页中均匀随机选（默认）；sequential = 取最小未完成页。
    svg_dir：非 None 时页入库后缓存该页未编码字头的缩略图 svg（字形源保全，
    失败降级不中断）。返回：0 成功；1 该页抓取失败（下轮重新选页）；42 全部完成。
    """
    pick = store.random_missing_page if order == "random" else store.next_missing_page
    page = pick(from_page)
    if page is None:
        kangxi_log.emit("all_done")
        print("ALL_DONE：全部页已完整入库（阅读页 + 原图）")
        return 42
    kangxi_log.emit("round_start", page=page, order=order)

    print(f"下一页：{page:04d}")
    if not fp.fetch_page(page, images_dir, store, save_html=False, force=False):
        print(f"页 {page:04d} 抓取失败", file=sys.stderr)
        return 1

    if svg_dir is not None:
        try:
            svg_stat = kangxi_svg_cache.cache_page_svgs(store, page, svg_dir)
            if any(svg_stat.values()):
                print(f"页 {page:04d} 字头 svg 缓存：{svg_stat}")
        except Exception as e:  # 缩略图缓存失败不杀页流程（同 fetch_entry 副本韧性）
            print(f"⚠ 页 {page:04d} 字头 svg 缓存异常（{type(e).__name__}: {e}），已跳过",
                  file=sys.stderr, flush=True)

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
                    help=f"原图目录（默认 {WD_DIRS['images']}）")
    ap.add_argument("--entries-dir", type=Path, default=None,
                    help=f"详情 JSON 副本目录（默认 {WD_DIRS['entries']}）")
    ap.add_argument("--svg-dir", type=Path, default=None,
                    help=f"字头 svg 缓存目录（默认 {WD_DIRS['svg']}；外置盘未挂载则退出）")
    ap.add_argument("--from-page", type=int, default=1, help="起始页码（默认 1）")
    ap.add_argument("--order", choices=["random", "sequential"], default="random",
                    help="选页策略：random 未完成页中均匀随机（默认）；sequential 最小未完成页")
    args = ap.parse_args()

    store = kangxi_store.KangxiStore(args.db)
    fp.check_robots()  # 禁止即 sys.exit(2)
    images_dir = pick_dir(args.images_dir, "images")
    entries_dir = pick_dir(args.entries_dir, "entries")
    svg_dir = pick_dir(args.svg_dir, "svg")

    rc = crawl_next_page(store, images_dir, entries_dir, args.from_page, args.order, svg_dir)
    if rc == 0:
        print(json.dumps(store.stats(), ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())
