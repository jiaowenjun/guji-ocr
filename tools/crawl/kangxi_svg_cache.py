#!/usr/bin/env python3
"""字头缩略图 SVG 本地缓存：随爬保全未编码字头字形源 + 存量回补。

动机（2026-11-13）：爬取管线只存字头 svg 的**文件名索引**（page_chars.svg），
二进制从不落盘——展示页缩略图全靠热链站方，字体补录的字形源亦无本地保全；
站方改版/下线 kxzt/ 目录即永久失源（当时已爬 3,000+ 字头、118 个 K0000）。

设计：
- 目录布局：{svg_dir}/{千位桶}/{名}.svg，相对路径即 page_chars.svg 字段，零映射；
  默认 WD-2T kangxizidian-heads-svg，未挂载回退 datasets/kangxi-crawl/heads-svg。
- 内容校验：必须以 <?xml 或 <svg 开头——带 /v2/ 前缀的 kxzt URL 会 200 返回
  1.6MB HTML（实测陷阱），直链固定用 www.kangxizidian.com/kxzt/。
- 复用 fetch_kangxi_page.http_get（4 次退避重试 + http 事件日志）与
  polite_sleep（≥1.2s 限速）；原子写（tmp + os.replace）。
- 随爬挂钩：kangxi_crawl_next.crawl_next_page 页入库后调用 cache_page_svgs，
  默认只抓未编码字头（K0000 + 2 段名孪生，字体补录字形源）；失败降级警告，
  不中断页流程（与 fetch_entry 副本写同韧性级别）。
- 采纳（adopt）：回补时若 --adopt-dir 下有同名平铺文件（如评估产物
  datasets/kangxi-unencoded/svg/）且内容合法，直接复制零网络。
- 事件：svg_fetch / svg_adopt / svg_error（命中缓存不记事件，避免噪声）。

用法：
  python3 kangxi_svg_cache.py                  # 存量回补：已爬各页的未编码字头
  python3 kangxi_svg_cache.py --scope all      # 全量回补所有已爬字头（千量级，~1 小时）
  python3 kangxi_svg_cache.py --dry-run        # 只统计缺口，不联网
仅依赖标准库。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paths  # noqa: E402

import fetch_kangxi_page as fp
import kangxi_log
import kangxi_store

REPO_ROOT = paths.REPO_ROOT
SVG_URL_PREFIX = "https://www.kangxizidian.com/kxzt/"
WD_SVG_DIR = paths.RAW_KANGXI_SVG
DEFAULT_ADOPT_DIR = paths.UNENCODED_DIR / "svg"


def looks_like_svg(data: bytes) -> bool:
    head = data.lstrip(b"\xef\xbb\xbf \t\r\n")[:64]
    return head.startswith(b"<?xml") or head.startswith(b"<svg")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def fetch_svg(rel: str, svg_dir: Path, adopt_dir: Path | None = None,
              force: bool = False) -> str:
    """确保 {svg_dir}/{rel} 存在。返回 "hit" | "adopt" | "fetch"；失败抛异常。

    rel 为 page_chars.svg 字段（如 0000s/0334-04-K0000.svg）。
    """
    dst = svg_dir / rel
    if dst.exists() and not force:
        return "hit"
    if adopt_dir is not None:
        src = adopt_dir / Path(rel).name
        if src.is_file() and looks_like_svg(src.read_bytes()[:256]):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            kangxi_log.emit("svg_adopt", svg=rel, src=str(src))
            return "adopt"
    url = SVG_URL_PREFIX + rel
    body, ctype = fp.http_get(url)
    if not looks_like_svg(body):
        kangxi_log.emit("svg_error", svg=rel, error="not svg", bytes=len(body), ctype=ctype)
        raise RuntimeError(f"{url} 返回非 SVG 内容（{len(body)} B，{ctype or '无类型'}）")
    _atomic_write(dst, body)
    kangxi_log.emit("svg_fetch", svg=rel, bytes=len(body))
    return "fetch"


def wanted_svgs(store: kangxi_store.KangxiStore, page: int, scope: str) -> list[str]:
    """该页应缓存的 svg 相对路径；scope: unencoded（codepoint 为空）| all。"""
    rows = store.get_page_chars(page)
    if scope == "unencoded":
        rows = [r for r in rows if r.get("codepoint") is None]
    return [r["svg"] for r in rows]


def cache_page_svgs(store: kangxi_store.KangxiStore, page: int, svg_dir: Path,
                    scope: str = "unencoded", adopt_dir: Path | None = None) -> dict:
    """缓存一页的字头 svg（随爬挂钩用）。单个失败不抛出，计入结果。"""
    out = {"hit": 0, "adopt": 0, "fetch": 0, "error": 0}
    for rel in wanted_svgs(store, page, scope):
        try:
            action = fetch_svg(rel, svg_dir, adopt_dir)
        except Exception as e:  # 降级：缩略图失败不影响页流程
            out["error"] += 1
            print(f"  ! svg {rel} 缓存失败（{type(e).__name__}: {e}）", file=sys.stderr, flush=True)
            continue
        out[action] += 1
        if action == "fetch":
            fp.polite_sleep()
    return out


def crawled_pages(store: kangxi_store.KangxiStore) -> list[int]:
    with store._conn() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT page FROM page_chars ORDER BY page")]


def pick_svg_dir(preferred: Path | None) -> Path:
    if preferred is not None:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    paths.require_wd("svg 缓存")
    WD_SVG_DIR.mkdir(parents=True, exist_ok=True)
    return WD_SVG_DIR


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=kangxi_store.DEFAULT_DB,
                    help=f"SQLite 库路径（默认 {kangxi_store.DEFAULT_DB}）")
    ap.add_argument("--svg-dir", type=Path, default=None,
                    help=f"缓存目录（默认 {WD_SVG_DIR}；外置盘未挂载则退出）")
    ap.add_argument("--scope", choices=["unencoded", "all"], default="unencoded",
                    help="unencoded = 仅未编码字头（默认）；all = 全部字头")
    ap.add_argument("--adopt-dir", type=Path, default=DEFAULT_ADOPT_DIR,
                    help=f"采纳目录：同名平铺 svg 直接复制（默认 {DEFAULT_ADOPT_DIR}）")
    ap.add_argument("--no-adopt", action="store_true", help="禁用采纳，一律联网抓取")
    ap.add_argument("--limit", type=int, default=0, help="最多处理的缺失文件数（0 = 不限）")
    ap.add_argument("--dry-run", action="store_true", help="只统计缺口，不联网不落盘")
    ap.add_argument("--events-file", type=Path, default=None,
                    help="JSONL 事件日志路径（默认不记；循环爬取运行中勿共用同一文件）")
    args = ap.parse_args()

    store = kangxi_store.KangxiStore(args.db)
    svg_dir = pick_svg_dir(args.svg_dir)
    adopt_dir = None if args.no_adopt else args.adopt_dir
    if args.events_file:
        kangxi_log.setup(args.events_file)

    pages = crawled_pages(store)
    todo = [(p, rel) for p in pages for rel in wanted_svgs(store, p, args.scope)
            if not (svg_dir / rel).exists()]
    total = sum(len(wanted_svgs(store, p, args.scope)) for p in pages)
    print(f"已爬 {len(pages)} 页，{args.scope} 字头 svg 共 {total}，本地已有 {total - len(todo)}，"
          f"缺 {len(todo)} → {svg_dir}", flush=True)
    if args.dry_run or not todo:
        return 0

    fp.check_robots()  # 禁止即 sys.exit(2)
    if args.limit:
        todo = todo[:args.limit]
    stat = {"adopt": 0, "fetch": 0, "error": 0}
    for i, (page, rel) in enumerate(todo, 1):
        try:
            action = fetch_svg(rel, svg_dir, adopt_dir)
        except Exception as e:
            stat["error"] += 1
            print(f"[{i}/{len(todo)}] ✗ {rel}：{type(e).__name__}: {e}", file=sys.stderr, flush=True)
            continue
        stat[action] += 1
        print(f"[{i}/{len(todo)}] {action:5s} {rel}", flush=True)
        if action == "fetch":
            fp.polite_sleep()
    print(f"完成：采纳 {stat['adopt']}，下载 {stat['fetch']}，失败 {stat['error']}", flush=True)
    return 1 if stat["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
