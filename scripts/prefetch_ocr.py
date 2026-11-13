#!/usr/bin/env python3
"""预识别：对已爬取到本地的页面批量跑 PaddleOCR，结果持久缓存到本地。

添加新页时 kangxi_page_tool 的 OCR 裁剪/折行优先读本缓存，未命中才提交
新 job——新页 OCR 等待从 ~40s+（冷启动/排队）降为 0（命中时零联网）。

缓存位置：paddleocr-baseline/data/ocr-markdown/<page:04d>.json
  {page, sha256, fetched_at, markdown}（sha256 与扫描图绑定，图变则失效重跑）
  以及零文本哨兵 {"markdown": ""}（避免无文本页反复提交）。

用法：
  python3 scripts/prefetch_ocr.py [--pages 335-360] [--limit N] [--force]
  python3 scripts/prefetch_ocr.py --all          # 全部已爬页（581 页，量大慎用）
默认：数据集中已有页的「下一页起」未缓存页（即近期将要添加的页）。
仅依赖标准库；OCR 经本地 paddleocr-baseline 服务（127.0.0.1:8010）。
"""
from __future__ import annotations

import argparse
import difflib  # noqa: F401  （与 kangxi_page_tool 口径一致，便于日后复用对齐）
import hashlib
import json
import sys
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kangxi_store  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CACHE_DIR = REPO / "paddleocr-baseline" / "data" / "ocr-markdown"
MANIFEST = REPO / "kangxi-gold" / "manifest.json"
BASE = "http://127.0.0.1:8010"


def service_up() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=3) as r:
            return json.loads(r.read()).get("service") == "ocr"
    except Exception:
        return False


def cache_entry(page: int) -> dict | None:
    f = CACHE_DIR / f"{page:04d}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def cache_valid(page: int, store: kangxi_store.KangxiStore) -> bool:
    """缓存存在且 sha256 与库内扫描图一致（图变即失效）。"""
    entry = cache_entry(page)
    if entry is None:
        return False
    row = store.get_page(page) or {}
    return bool(entry.get("sha256")) and entry["sha256"] == row.get("scan_sha256")


def ocr_one(page: int, store: kangxi_store.KangxiStore) -> tuple[str | None, str]:
    """提交单页并返回 (markdown, note)；markdown None = 失败/无文本。"""
    row = store.get_page(page) or {}
    img = Path(row.get("scan_file") or "")
    if not img.is_file():
        return None, "无扫描图"
    payload = img.read_bytes()
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{img.name}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{BASE}/ocr/images",
        data=body,
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        submit = json.loads(r.read())
    image_id = submit.get("image_id")
    if not image_id:
        return None, "提交未返回 image_id"
    deadline = time.time() + 600
    while time.time() < deadline:
        time.sleep(3)  # 服务端 SHA 去重：同图历史 job 直接复用，秒回
        with urllib.request.urlopen(f"{BASE}/ocr/images/{image_id}", timeout=30) as r:
            view = json.loads(r.read())
        if view.get("result") is not None:
            break
        if view.get("error") is not None:
            return None, f"任务失败（{view.get('error')}）"
    else:
        return None, "轮询超时"
    result_view = view["result"]
    md = result_view.get("markdown") or ""
    if not md:
        md = (
            ((result_view.get("json") or {}).get("result") or {}).get("layoutParsingResults")
            or [{}]
        )[0].get("markdown", {}).get("text", "")
    return (md or ""), "ok"


def save_cache(page: int, sha: str, markdown: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{page:04d}.json").write_text(
        json.dumps(
            {
                "page": page,
                "sha256": sha,
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
                "markdown": markdown,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def dataset_last_page() -> int:
    if MANIFEST.exists():
        pages = json.loads(MANIFEST.read_text(encoding="utf-8")).get("pages") or []
        if pages:
            return max(p["page"] for p in pages)
    return 311


def parse_pages_arg(value: str | None) -> list[int] | None:
    if value is None:
        return None
    out: list[int] = []
    for part in value.split(","):
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", help="页码，如 335-360 或 335,340；默认=数据集末页起的未缓存已爬页")
    ap.add_argument("--all", action="store_true", help="全部已爬页（581 页，量大慎用）")
    ap.add_argument("--limit", type=int, default=20, help="本次最多处理页数（默认 20）")
    ap.add_argument("--force", action="store_true", help="忽略有效缓存强制重跑")
    args = ap.parse_args()

    if not service_up():
        print("✗ paddleocr-baseline 服务未运行（127.0.0.1:8010）。先启动：", file=sys.stderr)
        print("  cd paddleocr-baseline && OCR_TOKEN=<token> .venv/bin/python -m paddleocr_baseline", file=sys.stderr)
        return 2

    store = kangxi_store.KangxiStore()
    with store._conn() as conn:
        crawled = sorted(
            r[0] for r in conn.execute("SELECT page FROM pages WHERE scan_sha256 IS NOT NULL")
        )
    if not crawled:
        print("库内无已爬页面。", file=sys.stderr)
        return 1

    if args.all:
        todo = crawled
    elif args.pages:
        wanted = parse_pages_arg(args.pages)
        todo = [p for p in crawled if p in wanted]
        missing = sorted(set(wanted) - set(todo))
        if missing:
            print(f"提示：{len(missing)} 页未爬取（跳过）：@{missing[:10]}{'…' if len(missing) > 10 else ''}")
    else:
        last = dataset_last_page()
        todo = [p for p in crawled if p > last and not cache_valid(p, store)]
    todo = [p for p in todo if args.force or not cache_valid(p, store)]
    todo = todo[: args.limit]
    if not todo:
        print("✓ 没有待预识别的页面（缓存均有效）。")
        return 0

    print(f"待预识别 {len(todo)} 页：@{todo[0]}–@{todo[-1]}" if len(todo) > 1 else f"待预识别 1 页：@{todo[0]}")
    ok = no_text = fail = 0
    for n, page in enumerate(todo, 1):
        time.sleep(1.2)  # 对上游礼貌限速
        try:
            md, note = ocr_one(page, store)
        except Exception as e:  # noqa: BLE001 —— 单页失败不终止批次
            print(f"[{n}/{len(todo)}] @{page} ✗ {e}", flush=True)
            fail += 1
            continue
        if md is None:
            print(f"[{n}/{len(todo)}] @{page} ✗ {note}", flush=True)
            fail += 1
            continue
        sha = (store.get_page(page) or {}).get("scan_sha256", "")
        save_cache(page, sha, md)
        if md:
            ok += 1
            print(f"[{n}/{len(todo)}] @{page} ✓ {len(md)} 字符", flush=True)
        else:
            no_text += 1
            print(f"[{n}/{len(todo)}] @{page} ○ 无文本（哨兵已存，不再重复提交）", flush=True)

    print(f"完成：成功 {ok} / 无文本 {no_text} / 失败 {fail}；缓存目录 {CACHE_DIR}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
