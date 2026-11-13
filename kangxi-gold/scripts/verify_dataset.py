#!/usr/bin/env python3
"""kangxi-gold 金标数据集一致性校验。

校验项：
  1. manifest.json 存在，pages 为连续页码（默认 312–328），字段齐全；
  2. 每页图片存在于 images_dir，sha256 与尺寸（JPEG 标记流现读）与 manifest 一致；
  3. 每页三个标注文件存在：NNNN.gj / NNNN.json / NNNN.txt；
  4. .gj 首个非空行是 @页码；
  5. .json 可解析为 {p, l} 且 p == 页码；
  6. .txt 非空、不含解析器剔除集内的标点（空白允许：* 转来的空格标记义项边界，
     评测时两侧同规则去除）、不含制表符/控制字符。

用法：
  python3 -I verify_dataset.py [--root kangxi-gold] [--pages 312-328]
退出码：0 全部通过；1 存在失败项（逐条列出）。仅依赖标准库。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PARSER_STRIP_SET = '。，·":：、《》'  # 与 guji-preview/src/parser/split-line.ts 剔除集一致


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
        for key in ("gj", "json", "txt"):
            if key not in ann:
                errors.append(f"{stem}: manifest.annotations 缺 {key}")

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

        gj = args.root / "annotations" / ann.get("gj", f"{stem}.gj")
        js = args.root / "annotations" / ann.get("json", f"{stem}.json")
        txt = args.root / "annotations" / ann.get("txt", f"{stem}.txt")
        for p in (gj, js, txt):
            if not p.is_file():
                errors.append(f"{stem}: 标注缺失 {p}")
        if gj.is_file():
            # 首个非空、非注释行应是 @页码（与解析器语义一致：// 行会被剔除）
            first = next(
                (l.strip() for l in gj.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.strip().startswith("//")),
                "",
            )
            if first != f"@{page}":
                errors.append(f"{stem}: .gj 首个非空行 {first!r} ≠ @{page}")
        if js.is_file():
            try:
                obj = json.loads(js.read_text(encoding="utf-8"))
                # Guji IR v2：{version:2, meta, pages:[{no, bands:[{lines}]}]}
                ir_pages = obj.get("pages") if isinstance(obj, dict) else None
                bands = ir_pages[0].get("bands") if ir_pages else None
                if (
                    obj.get("version") != 2
                    or not isinstance(ir_pages, list)
                    or len(ir_pages) != 1
                    or ir_pages[0].get("no") != page
                    or not isinstance(bands, list)
                    or not all(
                        isinstance(b.get("lines"), list) for b in bands
                    )
                ):
                    errors.append(f"{stem}: .json 非 guji-ir/1 结构（version={obj.get('version')}）")
            except json.JSONDecodeError as e:
                errors.append(f"{stem}: .json 解析失败：{e}")
        if txt.is_file():
            text = txt.read_text(encoding="utf-8")
            if not text.strip():
                errors.append(f"{stem}: .txt 为空")
            hit = {ch for ch in text if ch in PARSER_STRIP_SET or ch == "\t" or (ord(ch) < 32 and ch != "\n")}
            if hit:
                errors.append(f"{stem}: .txt 含不应出现的字符 {sorted(hit)!r}")
            total_chars += len("".join(text.split()))

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
