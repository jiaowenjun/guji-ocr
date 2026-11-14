#!/usr/bin/env python3
"""下载康熙字典武英殿版整页扫描图，并维护 kangxi-gold/manifest.json 的图片记录。

来源 kangxizidian.com：全圖頁（index2.php?page=N）引用的整页图直链
https://p.kangxizidian.com/kangxi2/NNNN.jpg（NNNN 为 4 位零填充页码）。
站点默认版本即武英殿版，与 guji-preview-grid/src/samples/kangxi-yibu.gj 的页码体系一致
（0312.jpg 已目视核对为「子集上·一部·一」起始页）。

策略：robots.txt 先行核查（全站 Disallow 即中止）；请求间隔 >=1.2s+抖动；
重试退避；JPEG 魔数 + Content-Type 校验；sha256 入清单；
已存在且校验通过的图片跳过网络下载（断点续传），--force 强制重下。

用法：
  python3 download_pages.py [--pages 312-328] [--images-dir DIR] [--manifest PATH] [--force]
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
import urllib.request
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IMAGES_DIR = Path("/Volumes/WD-2T/guji-ocr/raw/kangxizidian/pages")
DEFAULT_MANIFEST = REPO_ROOT / "kangxi-gold" / "manifest.json"
IMAGE_URL_TEMPLATE = "https://p.kangxizidian.com/kangxi2/{page:04d}.jpg"
TEXT_PAGE_TEMPLATE = "https://www.kangxizidian.com/v2/index.php?page={page}"
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


def check_robots() -> dict:
    """核查 robots.txt；对 User-agent:* 出现 Disallow: /（或覆盖我们路径的规则）即中止。"""
    verdict = {}
    for url in ROBOTS_URLS:
        try:
            body, _ = http_get(url)
            rules = body.decode("utf-8", "replace")
        except Exception as e:  # 无 robots.txt 视为默认允许
            verdict[url] = f"unreachable ({e})，按默认允许处理"
            continue
        if re.search(r"(?im)^user-agent:\s*\*", rules):
            section = rules.split(re.search(r"(?im)^user-agent:\s*\*", rules).group(0), 1)[1]
            section = re.split(r"(?im)^user-agent:", section)[0]
            disallows = [m.group(1).strip() for m in re.finditer(r"(?im)^disallow:\s*(.*)$", section)]
            # 以我们实际抓取的图片路径为准判断是否被规则覆盖
            fetched_path = "/kangxi2/0312.jpg"
            blocking = [d for d in disallows if d and fetched_path.startswith(d)]
        else:
            disallows, blocking = [], []
        verdict[url] = "allow" if not blocking else f"disallow: {blocking}"
        if blocking:
            print(f"robots.txt 禁止抓取（{url}: {blocking}），中止。", file=sys.stderr)
            sys.exit(2)
    return {
        "checked_at": str(date.today()),
        "rules": verdict,
        "note": "www 站为 User-agent: * / Allow: /；img CDN 无 robots.txt（默认允许）",
    }


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


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", default="312-328", help="页码范围，如 312-328 或 312,313,320")
    ap.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES_DIR)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--force", action="store_true", help="忽略本地缓存强制重新下载")
    args = ap.parse_args()
    pages = parse_pages_arg(args.pages)

    manifest = {}
    if args.manifest.exists():
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest.setdefault("dataset", "kangxi-gold")
    manifest["book"] = "康熙字典（武英殿版）"
    manifest["gold_version"] = "v1"
    manifest["source"] = {
        "site": "https://www.kangxizidian.com/v2/",
        "edition_note": (
            "站点默认版本即武英殿版；部首「一」指向 index.php?page=312，"
            "与 guji-preview-grid/src/samples/kangxi-yibu.gj 的 @312 页码体系一致；"
            "0312.jpg 已目视核对为「子集上·一部·一」起始页（版心：康熙字典 子集上）"
        ),
        "image_url_template": IMAGE_URL_TEMPLATE,
        "text_page_template": TEXT_PAGE_TEMPLATE,
        "watermark_note": "页脚有站点水印「kangxizidian.com 0312」，非原书内容",
        "robots": check_robots(),
    }
    manifest["images_dir"] = str(args.images_dir)
    entries = {e["page"]: e for e in manifest.get("pages", [])}

    args.images_dir.mkdir(parents=True, exist_ok=True)
    for n, page in enumerate(pages):
        fname = f"{page:04d}.jpg"
        url = IMAGE_URL_TEMPLATE.format(page=page)
        path = args.images_dir / fname
        if not args.force and valid_cached_image(path):
            data = path.read_bytes()
            size, dims, when = len(data), jpeg_size(data), entries.get(page, {}).get("downloaded_at", "cached")
            src = "cache"
        else:
            time.sleep(1.2 + random.uniform(0, 0.8))
            data, ctype = http_get(url)
            if "image" not in ctype.lower() or jpeg_size(data) is None:
                print(f"  ! {url} 返回的不是有效 JPEG（Content-Type: {ctype}，{len(data)} 字节），跳过", file=sys.stderr)
                return 1
            size, dims, when = len(data), jpeg_size(data), str(date.today())
            path.write_bytes(data)
            src = "download"
        entry = entries.get(page, {})
        entry.update(
            page=page,
            image=fname,
            url=url,
            size_bytes=size,
            sha256=sha256_of(path.read_bytes()),
            width=dims[0] if dims else None,
            height=dims[1] if dims else None,
            downloaded_at=when,
        )
        entries[page] = entry
        print(f"[{n + 1}/{len(pages)}] {fname} {size}B {dims} ({src})", flush=True)

    manifest["pages"] = [entries[p] for p in sorted(entries)]
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest 已更新：{args.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
