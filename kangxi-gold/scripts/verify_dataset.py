#!/usr/bin/env python3
"""kangxi-gold 金标数据集一致性校验。

校验项：
  1. manifest.json 存在，页码唯一，字段齐全；
  2. 每页图片存在于 images_dir，sha256 与尺寸（JPEG 标记流现读）与 manifest 一致；
  3. manifest 指定的 .gj 必须存在，且解析后恰为对应单页；
  4. 派生文本非空、不含解析器剔除的标点及控制字符；
  5. --snapshots 额外检查显式导出的 JSON/TXT 是否与当前源一致。

用法：
  python3 -I verify_dataset.py [--root kangxi-gold] [--pages 312-328]
退出码：0 全部通过；1 存在失败项（逐条列出）。派生复用 Node 生产解析器。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from annotation_source import derive_annotations

REPO_ROOT = Path(__file__).resolve().parents[2]
PARSER_STRIP_SET = '。，·":：、《》'  # 与 guji-preview-grid/src/parser/split-line.ts 剔除集一致


def jpeg_size(data: bytes):
    if len(data) < 4 or data[:3] != b"\xff\xd8\xff":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = int.from_bytes(data[i + 2 : i + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return int.from_bytes(data[i + 7 : i + 9], "big"), int.from_bytes(data[i + 5 : i + 7], "big")
        i += 2 + seg_len
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=REPO_ROOT / "kangxi-gold")
    ap.add_argument("--pages", default=None, help="默认取 manifest.json 的页清单（含新增页）")
    ap.add_argument("--snapshots", action="store_true", help="Also check explicit JSON/TXT exports for freshness")
    args = ap.parse_args()

    manifest_path = args.root / "manifest.json"
    if not manifest_path.exists():
        print(f"✗ 缺少 {manifest_path}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if args.pages:
        lo, hi = (int(x) for x in args.pages.split("-", 1))
        expected_pages = list(range(lo, hi + 1))
    else:
        expected_pages = sorted(p["page"] for p in manifest.get("pages", []))
    if not expected_pages:
        print("✗ manifest 页清单为空", file=sys.stderr)
        return 1
    errors: list[str] = []

    try:
        derived = derive_annotations(args.root)
    except Exception as error:
        print(f"Source derivation failed: {error}", file=sys.stderr)
        return 1

    pages = {e["page"]: e for e in manifest.get("pages", [])}

    got = sorted(pages)
    if got != expected_pages:
        errors.append(f"manifest 页码 {got[0]}–{got[-1]}（共{len(got)}页）≠ 期望 {lo}–{hi}")
    images_dir = Path(manifest["images_dir"])
    if not images_dir.is_dir():
        errors.append(f"images_dir 不存在或未挂载：{images_dir}")

    total_chars = 0
    for page in expected_pages:
        stem = f"{page:04d}"
        entry = pages.get(page)
        if entry is None:
            continue
        for key in ("image", "url", "sha256", "size_bytes", "width", "height", "annotations"):
            if key not in entry:
                errors.append(f"{stem}: manifest 缺字段 {key}")
        ann = entry.get("annotations") or {}

        img = images_dir / entry.get("image", f"{stem}.jpg")
        if img.is_file():
            data = img.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest != entry.get("sha256"):
                errors.append(f"{stem}: 图片 sha256 不符（磁盘 {digest[:12]}… ≠ manifest {str(entry.get('sha256'))[:12]}…）")
            if len(data) != entry.get("size_bytes"):
                errors.append(f"{stem}: 图片大小不符（磁盘 {len(data)} ≠ manifest {entry.get('size_bytes')}）")
            dims = jpeg_size(data)
            if dims != (entry.get("width"), entry.get("height")):
                errors.append(f"{stem}: 图片尺寸不符（磁盘 {dims} ≠ manifest ({entry.get('width')}, {entry.get('height')})）")
        else:
            errors.append(f"{stem}: 图片缺失 {img}")

        row = derived[page]
        text = row["text"]
        if not text.strip():
            errors.append(f"{stem}: empty derived text")
        hit = {ch for ch in text if ch in PARSER_STRIP_SET or ch == "\t" or (ord(ch) < 32 and ch != "\n")}
        if hit:
            errors.append(f"{stem}: unexpected text characters {sorted(hit)!r}")
        total_chars += len("".join(text.split()))
        if args.snapshots:
            for ext, expected in (("json", row["ir"]), ("txt", text)):
                path = args.root / "annotations" / f"{stem}.{ext}"
                try:
                    actual = json.loads(path.read_text(encoding="utf-8")) if ext == "json" else path.read_text(encoding="utf-8")
                    if actual != expected:
                        errors.append(f"{stem}: stale {ext} snapshot; run explicit export")
                except (OSError, ValueError) as error:
                    errors.append(f"{stem}: {error}")

    for e in errors:
        print(f"✗ {e}", file=sys.stderr)
    n_img = sum(1 for p in expected_pages if (images_dir / f"{p:04d}.jpg").is_file())
    print(
        f"{'✓ 全部通过' if not errors else '✗ 失败'}：{len(expected_pages)} 页 / 图片 {n_img} 张 / 正文 {total_chars} 字"
        f" / 校验项 {'全部通过' if not errors else f'{len(errors)} 项失败'}"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
