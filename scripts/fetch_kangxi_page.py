#!/usr/bin/env python3
"""kangxizidian.com 阅读页爬取器：给定页 ID，抓取该页整页原图。

依据 docs/research/2026-11-12-kangxizidian-网站结构调研.md：
- 阅读页 /v2/index2.php?page=N 左列为整页扫描 <img class="center-fit">，
  其 src 即原图直链（观察规律为 https://p.kangxizidian.com/kangxi2/NNNN.jpg；
  本脚本以页面解析结果为准，该模板仅用于漂移提示）；
- 页 HTML 为带 BOM 的非规范 XHTML（body 在 head 内、属性无引号、破损实体），
  需 utf-8-sig 解码 + 宽容正则，勿用 XML 严格解析；
- 站点全书共 7738 页（导航「最後頁」，跳页框 maxLength=4）。

策略：robots.txt 先行核查（全站 Disallow 即中止）；每次网络请求间隔
>=1.2s+抖动；重试退避；JPEG 魔数 + 尺寸解析 + 最小体积校验；
本地有效缓存跳过（--force 重下）；--save-html 同时留存阅读页原文
（供后续字头缩略图索引解析）。

用法：
  python3 fetch_kangxi_page.py --pages 313
  python3 fetch_kangxi_page.py --pages 312-328 --out DIR --save-html
仅依赖标准库。
"""
from __future__ import annotations

import argparse
import hashlib
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

READING_PAGE_TEMPLATE = "https://www.kangxizidian.com/v2/index2.php?page={page}"
KNOWN_URL_TEMPLATE = "https://p.kangxizidian.com/kangxi2/{page:04d}.jpg"  # 仅漂移提示用
TOTAL_PAGES = 7738
DEFAULT_OUT_DIR = Path("/Volumes/WD-2T/guji-ocr/datasets/kangxizidian-wuyingdian")
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
MIN_BYTES = 50_000  # 一页扫描图不应小于 50KB
RETRY_DELAYS = [5, 15, 45]


def http_get(url: str, timeout: float = 60.0) -> tuple[bytes, str]:
    """GET 并返回 (body, content_type)，4 次尝试带退避。"""
    last_err: Exception | None = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(), resp.headers.get("Content-Type", "")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < len(RETRY_DELAYS):
                delay = RETRY_DELAYS[attempt]
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
        fetched_paths = ["/v2/index2.php", "/kangxi2/0313.jpg"]
        blocking = [d for d in disallows if d and any(p.startswith(d) for p in fetched_paths)]
        if blocking:
            print(f"robots.txt 禁止抓取（{url}: {blocking}），中止。", file=sys.stderr)
            sys.exit(2)


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """从 JPEG 标记流读 (width, height)；非 JPEG 返回 None。"""
    if len(data) < 4 or data[:3] != b"\xff\xd8\xff":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:  # 跳到下一个标记
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = int.from_bytes(data[i + 2 : i + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):  # SOF
            height = int.from_bytes(data[i + 5 : i + 7], "big")
            width = int.from_bytes(data[i + 7 : i + 9], "big")
            return width, height
        i += 2 + seg_len
    return None


def extract_scan_url(html: str, base_url: str) -> str | None:
    """在阅读页 HTML 中定位整页扫描 <img class="center-fit"> 的 src。

    站点属性常无引号（src=https://…jpg>），正则对引号可选且排除空白/引号/尖括号；
    标签内 class 与 src 先后顺序不假设。
    """
    for tag in re.findall(r"<img\b[^>]*>", html, re.IGNORECASE):
        if not re.search(r"class=[\"']?center-fit\b", tag, re.IGNORECASE):
            continue
        m = re.search(r"src\s*=\s*(?P<q>[\"']?)(?P<url>[^\s\"'<>]+)(?P=q)", tag, re.IGNORECASE)
        if m:
            return urljoin(base_url, m.group("url"))
    return None


def valid_cached_image(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    return len(data) >= MIN_BYTES and jpeg_size(data) is not None


def parse_pages_arg(value: str) -> list[int]:
    pages: list[int] = []
    for part in value.split(","):
        if "-" in part:
            lo, hi = part.split("-", 1)
            pages.extend(range(int(lo), int(hi) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def fetch_page(page: int, out_dir: Path, save_html: bool, force: bool) -> bool:
    """抓取单页：解析阅读页 → 下载原图。返回是否成功。"""
    fname = f"{page:04d}.jpg"
    path = out_dir / fname
    if not force and valid_cached_image(path):
        print(f"[{page:04d}] {fname} 本地缓存有效，跳过（--force 重下）")
        return True

    # 1) 阅读页 HTML（站点带 BOM，用 utf-8-sig 剥离）
    page_url = READING_PAGE_TEMPLATE.format(page=page)
    polite_sleep()
    body, ctype = http_get(page_url)
    if "html" not in ctype.lower() and len(body) < 500:
        print(f"[{page:04d}] 阅读页响应异常（Content-Type: {ctype}，{len(body)}B）", file=sys.stderr)
        return False
    if save_html:
        (out_dir / f"{page:04d}.html").write_bytes(body)
    html = body.decode("utf-8-sig", "replace")

    scan_url = extract_scan_url(html, page_url)
    if not scan_url:
        print(
            f"[{page:04d}] 阅读页未找到 center-fit 扫描图（{len(body)}B）；"
            f"页面结构可能已变化，参见调研报告第 2/5 节",
            file=sys.stderr,
        )
        return False
    expected = KNOWN_URL_TEMPLATE.format(page=page)
    if scan_url != expected:
        print(f"[{page:04d}] 注意：解析 URL 偏离已知模板：{scan_url}（模板 {expected}）")

    # 2) 整页原图
    polite_sleep()
    data, ctype2 = http_get(scan_url)
    dims = jpeg_size(data)
    if "image" not in ctype2.lower() or dims is None or len(data) < MIN_BYTES:
        print(f"[{page:04d}] 非有效扫描图（Content-Type: {ctype2}，{len(data)}B）", file=sys.stderr)
        return False
    path.write_bytes(data)
    print(
        f"[{page:04d}] {fname} {len(data)}B {dims[0]}x{dims[1]} "
        f"sha256={hashlib.sha256(data).hexdigest()[:16]}… <- {scan_url}",
        flush=True,
    )
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", required=True, help="页码，如 313 或 312-328 或 312,313,320")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help=f"输出目录（默认 {DEFAULT_OUT_DIR}）")
    ap.add_argument("--save-html", action="store_true", help="同时保存阅读页原文 NNNN.html（供字头索引解析）")
    ap.add_argument("--force", action="store_true", help="忽略本地缓存强制重新下载")
    args = ap.parse_args()
    pages = parse_pages_arg(args.pages)

    outside = [p for p in pages if not 1 <= p <= TOTAL_PAGES]
    if outside:
        print(f"警告：页码 {outside} 超出站点导航所示范围 1-{TOTAL_PAGES}", file=sys.stderr)

    try:
        args.out.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"输出目录不可用（{e}）；外置盘未挂载时可指定 --out", file=sys.stderr)
        return 1

    check_robots()

    failures = []
    for n, page in enumerate(pages):
        if not fetch_page(page, args.out, args.save_html, args.force):
            failures.append(page)
    ok = len(pages) - len(failures)
    print(f"完成：{ok}/{len(pages)} 页 -> {args.out}" + (f"；失败页：{failures}" if failures else ""))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
