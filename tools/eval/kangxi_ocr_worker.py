#!/usr/bin/env python3
"""OCR 后台跟随任务：扫描已爬取页面，逐页 PaddleOCR 识别并持久缓存到本地。

与爬取循环（tools/crawl/kangxi_crawl_loop.py）互补：爬虫每 ~2 分钟入库新页，
本任务持续把这些页的 OCR 结果预填进 var/ocr-cache/——后续 OCR 裁剪/折行/
page_ocr 均零等待命中。

复用 kangxi_page_tool.page_ocr(page, model="paddle")：内部已含
有效持久缓存（图片指纹、模型、正文完整性）→ 未命中则提交 job 并回写；
本脚本只做跟随编排：
- 待办 = 已爬有图且缓存缺失/失效的页，按页码升序（断点续跑天然成立）；
- 每页间隔 1.2s（对本地服务礼貌，与 prefetch_ocr 同口径）；
- 无待办时休眠 --idle-seconds 后重扫（新页由爬虫持续供给）；
- 连续失败达 --breaker 判定服务故障退出（附重启指引）；--once 处理完
  当前待办即退出（试运行）；--max-pages 限制本次处理页数；
- 事件日志 JSONL（kangxi_log），与爬虫事件流同目录分文件。

用法：
  nohup python3 tools/eval/kangxi_ocr_worker.py > var/logs/ocr-worker.log 2>&1 &
  python3 tools/eval/kangxi_ocr_worker.py --once --max-pages 3   # 试运行
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
from kangxi_page_tool import ocr_service_up, page_ocr  # noqa: E402
from kangxi_page_tool import ocr_cache_valid as cache_valid  # noqa: E402

RESTART_HINT = (
    "paddleocr-baseline 服务未运行（127.0.0.1:8010/health）。重启法见 "
    "memory/paddleocr-baseline-service：TOKEN 从 reflog 150cf35 取入临时 env，"
    "cd paddleocr-baseline && OCR_TOKEN=$TOKEN nohup .venv/bin/python "
    "-m paddleocr_baseline >> data/service.log 2>&1 &"
)


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def pending_pages(store: kangxi_store.KangxiStore) -> list[int]:
    """已爬有图且 OCR 缓存缺失/失效的页，升序。"""
    with store._conn() as c:
        crawled = [r[0] for r in c.execute(
            "SELECT page FROM pages WHERE scan_sha256 IS NOT NULL ORDER BY page")]
    return [p for p in crawled if not cache_valid(p, store)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=kangxi_store.DEFAULT_DB,
                    help=f"SQLite 库路径（默认 {kangxi_store.DEFAULT_DB}）")
    ap.add_argument("--events-file", type=Path,
                    default=paths.REPO_ROOT / "var" / "crawl" / "ocr-worker-events.jsonl",
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

    done = fails = idle_rounds = 0
    consecutive = 0
    dry_passes = 0  # 连续「整遍零成功」计数——上游故障判定（2026-11-16 空转事故）
    print(f"[{stamp()}] OCR 跟随任务启动：事件 {events}，空闲重扫 {args.idle_seconds:.0f}s", flush=True)
    try:
        while True:
            pass_done = 0
            todo = pending_pages(store)
            if not todo:
                if args.once:
                    print(f"[{stamp()}] ✓ 当前待办为空，--once 退出。", flush=True)
                    return 0
                idle_rounds += 1
                if idle_rounds % 30 == 1:  # 约半小时报一次平安
                    kangxi_log.emit("worker_idle", idle_rounds=idle_rounds, done=done)
                    print(f"[{stamp()}] 待办为空（已处理 {done} 页），{args.idle_seconds:.0f}s 后重扫", flush=True)
                time.sleep(args.idle_seconds)
                continue

            print(f"[{stamp()}] 待办 {len(todo)} 页：@{todo[0]:04d}–@{todo[-1]:04d}", flush=True)
            for page in todo:
                t0 = time.monotonic()
                try:
                    md = page_ocr(page, model="paddle", store=store)
                except Exception as e:  # 单页异常不断任务
                    md = None
                    kangxi_log.emit("ocr_error", page=page, error=f"{type(e).__name__}: {e}")
                    print(f"[{stamp()}] @{page:04d} ✗ 异常 {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                if md is None:
                    fails += 1
                    consecutive += 1
                    kangxi_log.emit("ocr_fail", page=page, consecutive=consecutive)
                    print(f"[{stamp()}] @{page:04d} ✗ 识别失败（连续 {consecutive}）", flush=True)
                    if consecutive >= args.breaker:
                        if not ocr_service_up():
                            kangxi_log.emit("worker_exit", reason="service_down", done=done, fails=fails)
                            print(f"[{stamp()}] ✗ 连续 {consecutive} 页失败且服务离线，退出。\n{RESTART_HINT}",
                                  file=sys.stderr, flush=True)
                            return 2
                        consecutive = 0  # 服务仍在线——视为批页瞬时故障，重置继续
                        print(f"[{stamp()}] 服务仍在线，重置连续失败计数继续。", flush=True)
                else:
                    consecutive = 0
                    done += 1
                    pass_done += 1
                    secs = round(time.monotonic() - t0, 1)
                    note = f"{len(md)} 字符"
                    kangxi_log.emit("ocr_done", page=page, chars=len(md), seconds=secs,
                                    cached=cache_valid(page, store))
                    print(f"[{stamp()}] @{page:04d} ✓ {note}（{secs}s）", flush=True)
                    if args.max_pages and done >= args.max_pages:
                        kangxi_log.emit("worker_exit", reason="max_pages", done=done)
                        print(f"[{stamp()}] 达到 --max-pages {args.max_pages}，退出。", flush=True)
                        return 0
                time.sleep(1.2)  # 与 prefetch_ocr 同口径的页间限速
            # 整遍零成功 = 上游故障（本地 health 正常但 aistudio 报错/残缺）；
            # 连续两遍即退出，避免上游残缺结果导致无限热空转
            if len(todo) > 20 and pass_done == 0:
                dry_passes += 1
                kangxi_log.emit("dry_pass", dry_passes=dry_passes, todo=len(todo))
                print(f"[{stamp()}] ⚠ 整遍零成功（待办 {len(todo)}），连续 {dry_passes}/2", flush=True)
                if dry_passes >= 2:
                    kangxi_log.emit("worker_exit", reason="upstream_degraded", done=done, fails=fails)
                    print(f"[{stamp()}] ✗ 连续 {dry_passes} 遍零成功：上游 OCR 降级（本地服务在线），"
                          f"退出待人工核查 aistudio 上游。", file=sys.stderr, flush=True)
                    return 3
                time.sleep(300)  # 干等 5 分钟再试一遍
            else:
                dry_passes = 0
                # 低产遍退避：上游半死（成功率 <20%）时遍间歇 10 分钟，
                # 避免每遍全量重提交浪费上游调用（2026-11-17 实测 97% 失败率仍 ~20min/遍连磨）
                if len(todo) > 20 and pass_done < len(todo) * 0.2:
                    kangxi_log.emit("thin_pass", done=pass_done, todo=len(todo))
                    print(f"[{stamp()}] ⚠ 低产遍（{pass_done}/{len(todo)}），10 分钟后再扫", flush=True)
                    time.sleep(600)
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
