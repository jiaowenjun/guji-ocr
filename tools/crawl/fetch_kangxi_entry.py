#!/usr/bin/env python3
"""kangxizidian.com 字头详情爬取器：给定字头（或页码），抓取该字的详情卡片结构化数据。

依据 docs/research/2026-11-12-kangxizidian-网站结构调研.md 第 7 节：
- 详情端点 /search/index_v.php?stype=Word&sword={字}&detail=y（阅读页缩略图
  链接经 iframe 嵌入的真实数据页），服务端渲染纯 HTML，无 JS 依赖；
- 每张卡片保存自己的字形、古文、部首/笔画、拼音、倉頡及双版本页位。
  og:description 可能合并多个字形；正文由来源卡片确定范围，再映射回
  og 转写以保留标点。另条子段和考證单独保存，解析见 kangxi_entry_parser。
- 释文中的 U+EAB1 为站点段落分隔符；
  其余私用区（PUA）字符可能是站方 kxfont 字形，记录并在 pua_other 中标出；
- 侧栏「歡迎光臨/古今人名/康熙頻道」等 #cornerbody1 块为随机轮换广告位，勿爬；
- sword 须为单个 Unicode 可表示字符；缩略图链接为破损实体 &#x 的真·未编码字
  无法经此端点查询（--pages 模式会跳过并计数）。

输出：结构化记录与详情页原始 HTML 经 kangxi_store 入 SQLite（entries 表，
主键为查询 Unicode 码位，record 内保存 cards；二次运行零网络请求）；磁盘旧 JSON 自动采纳
入库不联网；同时仍写每字一个 JSON 文件副本（{码位}.json）。--save-html
留存 HTML 文件副本。

用法：
  python3 fetch_kangxi_entry.py --chars 丁,丂
  python3 fetch_kangxi_entry.py --pages 313            # 抓该页全部字头详情
  python3 fetch_kangxi_entry.py --pages 312-328 --save-html --db PATH
仅依赖标准库。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import kangxi_log
import kangxi_store
from kangxi_entry_parser import parse_detail

DETAIL_TEMPLATE = "https://www.kangxizidian.com/search/index_v.php?stype=Word&sword={sword}&detail=y"
READING_PAGE_TEMPLATE = "https://www.kangxizidian.com/v2/index2.php?page={page}"
ROBOTS_URLS = [
    "https://www.kangxizidian.com/robots.txt",
    "https://p.kangxizidian.com/robots.txt",
]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Referer": "https://www.kangxizidian.com/v2/",
}
RETRY_DELAYS = [5, 15, 45]
PARA_SEP = "\ueab1"  # 站点释文段落分隔符（PUA）


def http_get(url: str, timeout: float = 60.0) -> tuple[bytes, str]:
    """GET 并返回 (body, content_type)，4 次尝试带退避；成功/重试均记事件日志。"""
    t0 = time.monotonic()
    last_err: Exception | None = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                ctype = resp.headers.get("Content-Type", "")
            kangxi_log.emit("http", url=url, ms=round((time.monotonic() - t0) * 1000),
                            bytes=len(body), attempts=attempt + 1, ctype=ctype)
            return body, ctype
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < len(RETRY_DELAYS):
                delay = RETRY_DELAYS[attempt]
                kangxi_log.emit("http_retry", url=url, attempt=attempt + 1,
                                error=f"{type(e).__name__}: {e}", delay=delay)
                print(f"  ! {url} 失败（{e}），{delay}s 后重试", flush=True)
                time.sleep(delay)
    raise RuntimeError(f"{url} 多次重试仍失败：{last_err}")


def polite_sleep() -> None:
    time.sleep(1.2 + random.uniform(0, 0.8))


def check_robots() -> None:
    """核查 robots.txt；对 User-agent:* 出现覆盖抓取路径的 Disallow 即中止。"""
    for url in ROBOTS_URLS:
        try:
            body, _ = http_get(url)
            rules = body.decode("utf-8", "replace")
        except Exception as e:  # 无 robots.txt 视为默认允许
            print(f"robots {url} 不可达（{e}），按默认允许处理", file=sys.stderr)
            continue
        m = re.search(r"(?im)^user-agent:\s*\*", rules)
        if not m:
            continue
        section = rules.split(m.group(0), 1)[1]
        section = re.split(r"(?im)^user-agent:", section)[0]
        disallows = [d.group(1).strip() for d in re.finditer(r"(?im)^disallow:\s*(.*)$", section)]
        fetched_paths = ["/search/index_v.php", "/v2/index2.php"]
        blocking = [d for d in disallows if d and any(p.startswith(d) for p in fetched_paths)]
        if blocking:
            print(f"robots.txt 禁止抓取（{url}: {blocking}），中止。", file=sys.stderr)
            sys.exit(2)


def chars_from_reading_page(html: str) -> tuple[list[str], int]:
    """从阅读页缩略图列提取可查询字头。

    链接形如 href='index2.php?page=313&sword=&#x4E01'（实体可解码）；
    真·未编码字的实体为破损的 &#x（无码位），跳过并计数。
    """
    chars: list[str] = []
    broken = 0
    for m in re.finditer(r"sword=&#x([0-9A-Fa-f]+)", html):
        c = chr(int(m.group(1), 16))
        if c not in chars:
            chars.append(c)
    broken = len(re.findall(r"sword=&#x(?![0-9A-Fa-f])", html))
    return chars, broken


def fetch_entry(sword: str, out_dir: Path, store: kangxi_store.KangxiStore,
                save_html: bool, force: bool) -> bool:
    fname = f"{ord(sword):04X}.json"
    path = out_dir / fname
    if not force and store.get_entry(ord(sword)):
        store.log("entry", f"U+{ord(sword):04X}", "skip-db")
        kangxi_log.emit("entry_skip", sword=sword, codepoint=f"U+{ord(sword):04X}", reason="db")
        print(f"[{sword}] {fname} 数据库已有，跳过（--force 重下）")
        return True

    # 磁盘旧 JSON 采纳入库（不联网；损坏文件照常走网络重抓）
    if not force and path.exists():
        if store.adopt_entry_json(path):
            kangxi_log.emit("entry_adopt", sword=sword, codepoint=f"U+{ord(sword):04X}")
            print(f"[{sword}] {fname} 磁盘旧记录采纳入库")
            return True

    url = DETAIL_TEMPLATE.format(sword=urllib.parse.quote(sword))
    polite_sleep()
    body, ctype = http_get(url)
    html = body.decode("utf-8-sig", "replace")
    if save_html:
        (out_dir / f"{ord(sword):04X}.html").write_bytes(body)

    rec = parse_detail(html, sword)
    if rec is None:
        kangxi_log.emit("entry_error", sword=sword, codepoint=f"U+{ord(sword):04X}",
                        error="no card (字頭 missing)")
        print(f"[{sword}] 详情页未命中（{len(body)}B，Content-Type {ctype}），跳过", file=sys.stderr)
        return False
    rec["html_sha256"] = hashlib.sha256(body).hexdigest()
    store.save_entry(sword, rec, raw_html=html, source_url=url)
    try:
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        # 库为主存储，文件副本失败不中断流程（如目录缺失/盘满）
        kangxi_log.emit("artifact_warn", sword=sword, error=str(e))
        print(f"[{sword}] ⚠ JSON 文件副本写入失败（{e}）；数据库记录已保存", file=sys.stderr)
    kangxi_log.emit("entry_done", sword=sword, codepoint=f"U+{ord(sword):04X}",
                    text_chars=rec["text_chars"], paragraphs=len(rec["text_paragraphs"]),
                    pua=rec["pua_other"] or None,
                    wuying=rec.get("wuying_edition"))
    warn = f"  ⚠ PUA 字形: {rec['pua_other']}" if rec["pua_other"] else ""
    print(
        f"[{sword}] {fname} {rec['text_chars']}字 {len(rec['text_paragraphs'])}段 "
        f"卷別{rec['juan']} 武英殿 p{rec['wuying_edition'] and rec['wuying_edition']['page']}"
        f"第{rec['wuying_edition'] and rec['wuying_edition']['nth_char']}字{warn}",
        flush=True,
    )
    return True


def parse_range(value: str) -> list[int]:
    pages: list[int] = []
    for part in value.split(","):
        if "-" in part:
            lo, hi = part.split("-", 1)
            pages.extend(range(int(lo), int(hi) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chars", help="直接给定字头，逗号分隔，如 丁,丂,七")
    ap.add_argument("--pages", help="页码模式：抓阅读页解析字头后逐字取详情，如 313 或 312-328")
    ap.add_argument("--out", type=Path, default=None,
                    help="输出目录（默认 WD-2T raw/kangxizidian/entries；外置盘未挂载则退出）")
    ap.add_argument("--save-html", action="store_true", help="下载时同时保存详情页 HTML 文件副本")
    ap.add_argument("--db", type=Path, default=kangxi_store.DEFAULT_DB,
                    help=f"SQLite 库路径（默认 {kangxi_store.DEFAULT_DB}）")
    ap.add_argument("--force", action="store_true", help="忽略数据库与本地缓存强制重新下载")
    args = ap.parse_args()
    if not args.chars and not args.pages:
        ap.error("需指定 --chars 或 --pages 至少一项")
    if args.out is None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import paths

        paths.require_wd("字头详情抓取")
        args.out = paths.RAW_KANGXI_ENTRIES

    chars: list[str] = []
    if args.chars:
        for c in args.chars.split(","):
            c = c.strip()
            if len(c) != 1:
                print(f"--chars 每项须为单字：{c!r}", file=sys.stderr)
                return 1
            if c not in chars:
                chars.append(c)

    try:
        args.out.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"输出目录不可用（{e}）；外置盘未挂载时可指定 --out", file=sys.stderr)
        return 1

    check_robots()
    store = kangxi_store.KangxiStore(args.db)

    skipped_unencoded = 0
    if args.pages:
        for page in parse_range(args.pages):
            # 优先复用库中阅读页 HTML，避免重复抓取
            row = None if args.force else store.get_page(page)
            if row and row.get("reading_html"):
                html = row["reading_html"]
                src = "库中复用"
            else:
                polite_sleep()
                body, _ = http_get(READING_PAGE_TEMPLATE.format(page=page))
                html = body.decode("utf-8-sig", "replace")
                store.save_reading(page, body)  # 顺手入库（scan 留给 fetch_kangxi_page 补）
                src = "已下载入库"
            found, broken = chars_from_reading_page(html)
            skipped_unencoded += broken
            new = [c for c in found if c not in chars]
            chars.extend(new)
            print(f"[页 {page:04d}] 阅读页{src}：字头 {len(found)} 个（新增 {len(new)}），破损实体跳过 {broken} 个", flush=True)

    failures = []
    for n, c in enumerate(chars):
        if not fetch_entry(c, args.out, store, args.save_html, args.force):
            failures.append(c)
    ok = len(chars) - len(failures)
    summary = f"完成：{ok}/{len(chars)} 字 -> {args.out} | 库 {args.db}"
    if skipped_unencoded:
        summary += f"；另有 {skipped_unencoded} 个真·未编码字（破损实体）无法经详情端点查询"
    if failures:
        summary += f"；失败：{failures}"
    print(summary)
    print(json.dumps(store.stats(), ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
