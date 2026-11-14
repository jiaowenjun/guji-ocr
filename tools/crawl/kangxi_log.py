#!/usr/bin/env python3
"""无人值守爬取的结构化事件日志（JSONL）与事后分析器。

事件文件每行一个 JSON 对象：{"ts": ISO8601, "event": "...", ...字段}。
默认未初始化时 emit 为空操作——各 CLI 不开日志行为不变；kangxi_crawl_loop
启动时 setup() 打开事件文件（默认与 SQLite 库同目录的
kangxi-crawl-events.jsonl；约 1.5KB/轮，全书 ~12MB，无需轮转）。

事件类型：
  loop_start / loop_exit / all_done   循环生命周期（含完整配置）
  round_start / interval / heartbeat  每轮选页、间隔采样、每 50 页心跳快照
  page_done / page_skip / page_error  页级结果（字节数/尺寸/sha/字头数/阶段）
  entry_done / entry_skip / entry_adopt / entry_error
                                      字头级结果（码位/字数/段数/PUA）
  http / http_retry                   每个网络请求的耗时/字节数/尝试次数/错误

事后分析：python3 kangxi_log.py [events.jsonl]
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import threading
from datetime import datetime
from pathlib import Path

_lock = threading.Lock()
_file = None


def setup(path: Path | str) -> Path:
    """打开事件文件（追加）。返回路径。"""
    global _file
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _file = open(path, "a", encoding="utf-8")
    return path


def emit(event: str, **fields) -> None:
    """追加一条事件；未 setup 时为空操作。"""
    if _file is None:
        return
    rec = {"ts": datetime.now().isoformat(timespec="milliseconds"), "event": event}
    rec.update(fields)
    with _lock:
        _file.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _file.flush()


def classify_url(url: str) -> str:
    if "index2.php" in url:
        return "reading_html"
    if ".jpg" in url:
        return "scan_jpg"
    if "index_v.php" in url:
        return "detail_html"
    if "robots.txt" in url:
        return "robots"
    return "other"


def _pct(sorted_xs: list[float], p: float) -> float:
    if not sorted_xs:
        return 0.0
    return sorted_xs[min(len(sorted_xs) - 1, int(len(sorted_xs) * p))]


def analyze(path: Path) -> None:
    """汇总事件文件：吞吐、HTTP 延迟分位、重试/错误时间线。"""
    rounds = pages_done = pages_err = entries_done = entries_skip = entries_err = 0
    http_by_kind: dict[str, list[float]] = {}
    http_bytes: dict[str, int] = {}
    retries: dict[str, int] = {}
    intervals: list[float] = []
    errors: list[tuple[str, str]] = []
    first_ts = last_ts = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev = rec.get("event")
            first_ts = first_ts or rec.get("ts")
            last_ts = rec.get("ts") or last_ts
            if ev == "round_start":
                rounds += 1
            elif ev == "page_done":
                pages_done += 1
            elif ev == "page_error":
                pages_err += 1
                errors.append((rec["ts"][:16], f"page {rec.get('page')}: {rec.get('error', '')[:60]}"))
            elif ev == "entry_done":
                entries_done += 1
            elif ev == "entry_skip":
                entries_skip += 1
            elif ev == "entry_error":
                entries_err += 1
                errors.append((rec["ts"][:16], f"entry {rec.get('sword')}: {rec.get('error', '')[:60]}"))
            elif ev == "http":
                kind = classify_url(rec.get("url", ""))
                http_by_kind.setdefault(kind, []).append(rec.get("ms", 0))
                http_bytes[kind] = http_bytes.get(kind, 0) + (rec.get("bytes") or 0)
            elif ev == "http_retry":
                errcls = rec.get("error", "?").split(":")[0]
                retries[errcls] = retries.get(errcls, 0) + 1
            elif ev == "interval":
                intervals.append(rec.get("seconds", 0))

    print(f"事件文件：{path}")
    print(f"时段：{first_ts} → {last_ts}")
    print(f"轮次 {rounds}｜页完成 {pages_done}、页失败 {pages_err}"
          f"｜详情完成 {entries_done}、库跳过 {entries_skip}、失败 {entries_err}")
    if intervals:
        print(f"间隔：n={len(intervals)} 均值={statistics.mean(intervals):.0f}s "
              f"min={min(intervals):.0f}s max={max(intervals):.0f}s")
    print("HTTP（按资源类型）：")
    for kind, xs in sorted(http_by_kind.items()):
        xs.sort()
        print(f"  {kind:12s} n={len(xs):5d} p50={_pct(xs, .5):5.0f}ms p95={_pct(xs, .95):5.0f}ms "
              f"max={xs[-1]:6.0f}ms 共 {http_bytes.get(kind, 0) / 1e6:.1f}MB")
    if retries:
        print("重试（按错误类）：", dict(sorted(retries.items(), key=lambda kv: -kv[1])))
    if errors:
        print(f"错误时间线（{len(errors)} 条，最近 10）：")
        for ts, msg in errors[-10:]:
            print(f"  {ts}  {msg}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    analyze(Path(sys.argv[1]))
