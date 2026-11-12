#!/usr/bin/env python3
"""数据集对照页「添加新页」的桥接工具：补爬数据 → 生成 .gj 草稿 → 更新金标清单。

数据优先级（不重复爬虫）：kangxi-crawl.sqlite3 已有的页数据/字头详情直接用；
缺什么由 scripts/fetch_kangxi_page.py / fetch_kangxi_entry.py 增量补抓
（两者自身即「库里有则零网络请求」，页码页 2 个请求、字头详情每字 1 个请求）。

动作：
  add --page N          补数据 → 生成 kangxi-gold/annotations/NNNN.gj 草稿
                        （字头行 + 释义段落带；未编码字以 #□ + K 码注释占位）→
                        manifest.json 追加该页（status=draft）→ 重写
                        guji-preview-grid/public/dataset/index.json
  status --page N --to draft|first|final
                        改页标签（草稿/初校/精校）并同步 manifest 与 index.json

状态值：draft=草稿 / first=初校 / final=精校。
用法：python3 kangxi_page_tool.py add --page 329
仅依赖标准库。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kangxi_store  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
MANIFEST = REPO / "kangxi-gold" / "manifest.json"
ANNOTATIONS = REPO / "kangxi-gold" / "annotations"
INDEX_JSON = REPO / "guji-preview-grid" / "public" / "dataset" / "index.json"

STATUS_LABELS = {"draft": "草稿", "first": "初校", "final": "精校"}


def run_fetch(script: str, page: int) -> str:
    """复用既有爬取 CLI 增量补数据（库里有则零网络）；返回末行摘要。"""
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / script), "--pages", str(page)],
        capture_output=True, text=True, timeout=600,
    )
    if r.returncode != 0:
        raise RuntimeError(f"{script} 退出码 {r.returncode}\n{r.stdout}\n{r.stderr}")
    return (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else ""


def build_draft_gj(page: int, store: kangxi_store.KangxiStore) -> tuple[str, dict]:
    """由库内 page_chars + entries 生成 .gj 草稿与统计。"""
    chars = store.get_page_chars(page)
    if not chars:
        raise RuntimeError(f"页 {page} 无字头索引（page_chars 为空）——阅读页数据不完整")

    parts = [
        f"// 草稿：kangxizidian.com 爬取生成 {date.today()}，未经人工校对（状态：草稿）",
        "",  # 注释与 @页码 之间必须空行，否则并入同一大行致页声明不解析
        f"@{page}",
    ]
    counts = {"chars": 0, "unencoded": 0, "with_text": 0}
    for item in chars:
        parts.append("")
        if item["char"]:
            parts.append(f"#{item['char']}")
            counts["chars"] += 1
            entry = store.get_entry(item["codepoint"])
            if entry:
                record = json.loads(entry["record_json"])
                paragraphs = [p for p in record.get("text_paragraphs") or [] if p.strip()]
                if paragraphs:
                    counts["with_text"] += 1
                    # 每段释义一个空行分隔的大行；段落分隔符等 PUA 已由爬取器剥离
                    parts.append("")
                    parts.extend(paragraphs)
        else:
            k = item.get("k_code") or item.get("svg", "?")
            parts.append(f"#□")
            parts.append("")
            parts.append(f"// 未编码字（{k}）：站点无 Unicode 映射，请对照原图补录")
            counts["unencoded"] += 1
    return "\n".join(parts) + "\n", counts


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def write_index(manifest: dict) -> None:
    pages = [
        {
            "page": p["page"],
            "image": p["image"],
            "gj": p.get("annotations", {}).get("gj", f"{p['page']:04d}.gj"),
            "width": p.get("width"),
            "height": p.get("height"),
            "status": p.get("status", "first"),
        }
        for p in manifest.get("pages", [])
    ]
    INDEX_JSON.parent.mkdir(parents=True, exist_ok=True)
    INDEX_JSON.write_text(
        json.dumps(
            {"source": "kangxi-gold", "images_dir": manifest["images_dir"], "pages": pages},
            ensure_ascii=False, indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def cmd_add(page: int) -> dict:
    manifest = load_manifest()
    existing = {p["page"] for p in manifest.get("pages", [])}
    if page in existing:
        raise RuntimeError(f"页 {page} 已在数据集中")
    if not 1 <= page <= 7738:
        raise RuntimeError(f"页码 {page} 超出站点范围 1-7738")

    store = kangxi_store.KangxiStore()
    summaries = []
    if store.page_missing(page, ("reading", "scan")):
        summaries.append(run_fetch("fetch_kangxi_page.py", page))
    else:
        summaries.append("页数据：库中已有，未联网")
    chars = store.get_page_chars(page)
    missing_entries = [
        c["char"] for c in chars
        if c["char"] and store.get_entry(c["codepoint"]) is None
    ]
    if chars and missing_entries:
        summaries.append(run_fetch("fetch_kangxi_entry.py", page))
    elif chars:
        summaries.append(f"字头详情：库中已有 {len(chars) - len(missing_entries)}/{len(chars)}，未联网")

    row = store.get_page(page)
    if not row or not row.get("scan_sha256") or not row.get("scan_file"):
        raise RuntimeError(f"页 {page} 原图数据仍缺失")
    scan_file = Path(row["scan_file"])
    images_dir = Path(manifest["images_dir"])
    if scan_file.parent != images_dir:
        # 爬取时用了别的 --out：把图复制到数据集图片目录
        images_dir.mkdir(parents=True, exist_ok=True)
        target = images_dir / f"{page:04d}.jpg"
        target.write_bytes(scan_file.read_bytes())
        scan_file = target

    draft, counts = build_draft_gj(page, store)
    stem = f"{page:04d}"
    gj_path = ANNOTATIONS / f"{stem}.gj"
    gj_path.write_text(draft, encoding="utf-8")

    manifest["pages"] = sorted(
        manifest["pages"]
        + [{
            "page": page,
            "image": f"{stem}.jpg",
            "url": row.get("scan_url") or f"https://p.kangxizidian.com/kangxi2/{stem}.jpg",
            "size_bytes": row["scan_bytes"],
            "sha256": row["scan_sha256"],
            "width": row["scan_width"],
            "height": row["scan_height"],
            "downloaded_at": str(date.today()),
            "status": "draft",
            "annotations": {"gj": f"{stem}.gj", "json": f"{stem}.json", "txt": f"{stem}.txt"},
            "origin": "kangxizidian.com 爬取草稿（kangxi_page_tool.py add）",
        }],
        key=lambda p: p["page"],
    )
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_index(manifest)

    return {
        "ok": True,
        "page": page,
        "summaries": summaries,
        "counts": counts,
        "gj": str(gj_path.relative_to(REPO)),
        "status": "draft",
        "label": STATUS_LABELS["draft"],
    }


def cmd_status(page: int, to: str) -> dict:
    if to not in STATUS_LABELS:
        raise RuntimeError(f"未知状态 {to}（可选：{', '.join(STATUS_LABELS)}）")
    manifest = load_manifest()
    for p in manifest.get("pages", []):
        if p["page"] == page:
            p["status"] = to
            break
    else:
        raise RuntimeError(f"页 {page} 不在数据集中")
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_index(manifest)
    return {"ok": True, "page": page, "status": to, "label": STATUS_LABELS[to]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--page", type=int, required=True)
    s = sub.add_parser("status")
    s.add_argument("--page", type=int, required=True)
    s.add_argument("--to", required=True)
    args = ap.parse_args()

    try:
        result = cmd_add(args.page) if args.cmd == "add" else cmd_status(args.page, args.to)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001 —— 桥接给 HTTP 层
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
