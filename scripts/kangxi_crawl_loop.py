#!/usr/bin/env python3
"""全书慢速循环爬取：每页之间以「截断正态分布」随机间隔（默认均值 3 分钟，
落在 1–10 分钟内）持续抓取，直至 7738 页全部入库。

间隔采样：N(μ=180s, σ=90s) 拒绝采样至落在 [60s, 600s]（真截断，非钳制，
边界无点质量；σ 可调）。配合 kangxi_store 去重：已入库页/字头零网络，
中断重启自动从下一个未完成页续抓。

每轮动作与 kangxi_crawl_next.py 相同（阅读页 + 原图 + 页→字头索引 +
该页缺失字头详情，内建 ≥1.2s 请求限速）。连续失败达到上限退出（站点故障/
磁盘错误），避免死循环重试同一页。

用法：
  python3 kangxi_crawl_loop.py                       # 前台运行，Ctrl+C 退出
  nohup python3 kangxi_crawl_loop.py > crawl.log 2>&1 &   # 长期后台（推荐）
  python3 kangxi_crawl_loop.py --max-pages 5         # 试运行：抓 5 页后退出
仅依赖标准库。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import fetch_kangxi_page as fp
import kangxi_store
from kangxi_crawl_next import FALLBACK_ENTRIES_DIR, FALLBACK_IMAGES_DIR, crawl_next_page, pick_dir


def truncated_normal_seconds(mean: float, sigma: float, lo: float, hi: float,
                              rng: random.Random | None = None) -> float:
    """N(mean, sigma) 拒绝采样至落在 [lo, hi]（截断正态）。"""
    rng = rng or random
    while True:
        x = rng.gauss(mean, sigma)
        if lo <= x <= hi:
            return x


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=kangxi_store.DEFAULT_DB,
                    help=f"SQLite 库路径（默认 {kangxi_store.DEFAULT_DB}）")
    ap.add_argument("--images-dir", type=Path, default=None,
                    help="原图目录（默认 WD-2T，未挂载时回退 datasets/kangxi-crawl/pages）")
    ap.add_argument("--entries-dir", type=Path, default=None,
                    help="详情 JSON 副本目录（默认 WD-2T，未挂载时回退 datasets/kangxi-crawl/entries）")
    ap.add_argument("--from-page", type=int, default=1, help="起始页码（默认 1）")
    ap.add_argument("--mean-seconds", type=float, default=180.0, help="间隔均值（秒，默认 180）")
    ap.add_argument("--sigma-seconds", type=float, default=90.0, help="间隔标准差（秒，默认 90）")
    ap.add_argument("--min-seconds", type=float, default=60.0, help="间隔下限（秒，默认 60）")
    ap.add_argument("--max-seconds", type=float, default=600.0, help="间隔上限（秒，默认 600）")
    ap.add_argument("--max-pages", type=int, default=0, help="试运行上限页数（0 = 不限，跑完全书）")
    ap.add_argument("--max-consecutive-failures", type=int, default=5,
                    help="连续整页失败退出阈值（默认 5）")
    args = ap.parse_args()

    if not (args.min_seconds <= args.mean_seconds <= args.max_seconds):
        ap.error("均值须落在 [min-seconds, max-seconds] 内")

    fp.check_robots()  # 禁止即 sys.exit(2)
    store = kangxi_store.KangxiStore(args.db)
    images_dir = pick_dir(args.images_dir, FALLBACK_IMAGES_DIR, "images")
    entries_dir = pick_dir(args.entries_dir, FALLBACK_ENTRIES_DIR, "entries")

    print(f"[{stamp()}] 循环爬取启动：间隔 ~ N(μ={args.mean_seconds:.0f}s, σ={args.sigma_seconds:.0f}s) "
          f"截断于 [{args.min_seconds:.0f}s, {args.max_seconds:.0f}s]，库 {args.db}", flush=True)
    print(f"[{stamp()}] 初始统计：{json.dumps(store.stats(), ensure_ascii=False)}", flush=True)

    done = failures = 0
    try:
        while True:
            try:
                rc = crawl_next_page(store, images_dir, entries_dir, args.from_page)
            except KeyboardInterrupt:
                raise
            except Exception as e:  # 单页异常（如重试耗尽/磁盘错误）不杀循环，计入熔断
                traceback.print_exc()
                print(f"[{stamp()}] 本轮异常（{type(e).__name__}: {e}），计入连续失败",
                      file=sys.stderr, flush=True)
                rc = 1
            if rc == 42:
                print(f"[{stamp()}] 全书完成，退出。{json.dumps(store.stats(), ensure_ascii=False)}", flush=True)
                return 0
            if rc == 1:
                failures += 1
                if failures >= args.max_consecutive_failures:
                    print(f"[{stamp()}] 连续 {failures} 页失败（站点/磁盘故障？），退出。", file=sys.stderr, flush=True)
                    return 1
            else:
                failures = 0
                done += 1
                if args.max_pages and done >= args.max_pages:
                    print(f"[{stamp()}] 达到试运行上限 {args.max_pages} 页，退出。"
                          f"{json.dumps(store.stats(), ensure_ascii=False)}", flush=True)
                    return 0

            delay = truncated_normal_seconds(args.mean_seconds, args.sigma_seconds,
                                             args.min_seconds, args.max_seconds)
            state = f"累计完成 {done} 页" + (f"，连续失败 {failures} 次" if failures else "")
            print(f"[{stamp()}] {state}，{delay:.0f}s（{delay / 60:.1f} 分）后抓下一轮", flush=True)
            time.sleep(delay)
    except KeyboardInterrupt:
        print(f"\n[{stamp()}] 手动停止；已抓 {done} 页，重启后自动续抓。", flush=True)
        return 0


if __name__ == "__main__":
    sys.exit(main())
