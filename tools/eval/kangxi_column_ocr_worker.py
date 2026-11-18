#!/usr/bin/env python3
"""列级 OCR 后台跟随任务：扫描已爬页面，按大列分割预识别并持久缓存。

与 kangxi_ocr_worker.py（整页 markdown）互补：本任务产出 var/ocr-cache/
columns/NNNN.json——8 大列各自的识别结果（阅读序右→左），供列级对齐/
折行分析零等待使用。

复用 kangxi_page_tool.page_column_ocr(page, model="paddle", store=store)：内部已含
列级持久缓存（图 sha256 + model 校验，部分成功持久保存）→ 服务在线时
只补失败列；本脚本只做跟随编排：
- 待办 = 已爬有图且列缓存缺失/失效的页，按页码升序（断点续跑成立）；
- 每页间隔 1.2s（与 prefetch_ocr 同口径；页内 8 列由 page_column_ocr 串行）；
- 无待办时休眠 --idle-seconds 重扫（新页由爬虫持续供给）；
- 连续失败达 --breaker 且服务离线才退出（附重启指引）；
- 事件日志 JSONL，与整页 worker 分文件。

用法：
  nohup python3 tools/eval/kangxi_column_ocr_worker.py > var/logs/column-ocr-worker.log 2>&1 &
  python3 tools/eval/kangxi_column_ocr_worker.py --once --max-pages 2   # 试运行
仅依赖标准库；OCR 经本地 paddleocr-baseline 服务（127.0.0.1:8010）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "crawl"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kangxi_log  # noqa: E402
import kangxi_store  # noqa: E402
import paths  # noqa: E402
from kangxi_page_tool import ocr_service_up, page_column_ocr, column_cache_valid, column_ocr_complete  # noqa: E402

RESTART_HINT = (
    "paddleocr-baseline 服务未运行（127.0.0.1:8010/health）。重启法见 "
    "memory/paddleocr-baseline-service：TOKEN 从 reflog 150cf35 取入临时 env，"
    "cd paddleocr-baseline && OCR_TOKEN=$TOKEN nohup .venv/bin/python "
    "-m paddleocr_baseline >> data/service.log 2>&1 &"
)


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def pending_pages(store: kangxi_store.KangxiStore) -> list[int]:
    """已爬有图且列级 OCR 缓存缺失/失效的页，升序。"""
    with store._conn() as c:
        crawled = [r[0] for r in c.execute(
            "SELECT page FROM pages WHERE scan_sha256 IS NOT NULL ORDER BY page")]
    return [p for p in crawled if not column_cache_valid(p, store)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=kangxi_store.DEFAULT_DB,
                    help=f"SQLite 库路径（默认 {kangxi_store.DEFAULT_DB}）")
    ap.add_argument("--events-file", type=Path,
                    default=paths.REPO_ROOT / "var" / "crawl" / "column-ocr-worker-events.jsonl",
                    help="JSONL 事件日志路径")
    ap.add_argument("--idle-seconds", type=float, default=60.0,
                    help="无待办时的重扫间隔（秒，默认 60）")
    ap.add_argument("--breaker", type=int, default=8,
                    help="连续失败退出阈值（默认 8，判定服务故障）")
    ap.add_argument("--max-pages", type=int, default=0, help="本次最多处理页数（0=不限）")
    ap.add_argument("--once", action="store_true", help="处理完当前待办即退出（不跟随新页）")
    args = ap.parse_args()

    if not ocr_service_up():
        print(RESTART_HINT, file=sys.stderr)
        return 2

    events = kangxi_log.setup(args.events_file)
    kangxi_log.emit("worker_start", pid=__import__("os").getpid(), db=str(args.db),
                    idle_s=args.idle_seconds, breaker=args.breaker, once=args.once)
    store = kangxi_store.KangxiStore(args.db, readonly=True)

    done = fails = 0
    consecutive = 0
    idle_rounds = 0
    print(f"[{stamp()}] 列级 OCR 跟随任务启动：事件 {events}，空闲重扫 {args.idle_seconds:.0f}s", flush=True)
    try:
        while True:
            todo = pending_pages(store)
            if not todo:
                if args.once:
                    print(f"[{stamp()}] ✓ 当前待办为空，--once 退出。", flush=True)
                    return 0
                idle_rounds += 1
                if idle_rounds % 30 == 1:
                    kangxi_log.emit("worker_idle", idle_rounds=idle_rounds, done=done)
                    print(f"[{stamp()}] 待办为空（已处理 {done} 页），{args.idle_seconds:.0f}s 后重扫", flush=True)
                time.sleep(args.idle_seconds)
                continue

            print(f"[{stamp()}] 待办 {len(todo)} 页：@{todo[0]:04d}–@{todo[-1]:04d}", flush=True)
            for page in todo:
                t0 = time.monotonic()
                try:
                    cols = page_column_ocr(page, model="paddle", store=store)
                except Exception as e:  # 单页异常不断任务
                    cols = None
                    kangxi_log.emit("ocr_error", page=page, error=f"{type(e).__name__}: {e}")
                    print(f"[{stamp()}] @{page:04d} ✗ 异常 {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                if not column_ocr_complete(cols):
                    fails += 1
                    consecutive += 1
                    kangxi_log.emit("ocr_fail", page=page, consecutive=consecutive)
                    print(f"[{stamp()}] @{page:04d} ✗ 列级识别失败（连续 {consecutive}）", flush=True)
                    if consecutive >= args.breaker:
                        if not ocr_service_up():
                            kangxi_log.emit("worker_exit", reason="service_down", done=done, fails=fails)
                            print(f"[{stamp()}] ✗ 连续 {consecutive} 页失败且服务离线，退出。\n{RESTART_HINT}",
                                  file=sys.stderr, flush=True)
                            return 2
                        consecutive = 0  # 服务仍在线——批页瞬时故障，重置继续
                        print(f"[{stamp()}] 服务仍在线，重置连续失败计数继续。", flush=True)
                else:
                    consecutive = 0
                    done += 1
                    secs = round(time.monotonic() - t0, 1)
                    empty = sum(1 for c in cols if not c.get("markdown"))
                    chars = sum(len(c.get("markdown") or "") for c in cols)
                    kangxi_log.emit("ocr_done", page=page, columns=len(cols), chars=chars,
                                    empty_columns=empty, seconds=secs,
                                    cached=column_cache_valid(page, store))
                    print(f"[{stamp()}] @{page:04d} ✓ {len(cols)} 列 / {chars} 字符"
                          f"（空列 {empty}，{secs}s）", flush=True)
                    if args.max_pages and done >= args.max_pages:
                        kangxi_log.emit("worker_exit", reason="max_pages", done=done)
                        print(f"[{stamp()}] 达到 --max-pages {args.max_pages}，退出。", flush=True)
                        return 0
                time.sleep(1.2)  # 页间限速（页内 8 列由 page_column_ocr 串行）
            if args.once:
                kangxi_log.emit("worker_exit", reason="once_done", done=done, fails=fails)
                print(f"[{stamp()}] --once：本批完成 {done} 页、失败 {fails} 页，退出。", flush=True)
                return 0 if fails == 0 else 1
    except KeyboardInterrupt:
        kangxi_log.emit("worker_exit", reason="keyboard_interrupt", done=done)
        print(f"\n[{stamp()}] 手动停止；已处理 {done} 页。", flush=True)
        return 0


if __name__ == "__main__":
    sys.exit(main())
