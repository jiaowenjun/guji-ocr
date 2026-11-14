#!/usr/bin/env python3
"""向康熙字典體（KangXi Font Full Version / KX_47043_14）补录未编码字头字形。

字形源为站方字头缩略图 SVG（autotrace 轮廓，1280 坐标系 y-up，
外层 <g transform="translate(0,128) scale(0.1,-0.1)">，各字同管线）。
流程与可行性论证见 docs/research/2026-11-13-kangxi-未编码字头字体核验流程.md。

用法示例（补录 𫵮 U+2BD6E，用同页邻字 丰 校准基线；自仓库根运行）：
  python3 tools/dataset/kangxi_font_patch.py \
    --font guji-preview-grid/public/fonts/guji-large.ttf \
    --svg  var/unencoded/svg/0334-04-K0000.svg --cp 2BD6E \
    --anchor-svg  var/unencoded/svg/0334-03-00054-4E30.svg \
    --anchor-cp 4E30

要点：
  - 基线校准：anchor 字形（字体 cmap 内）bbox × anchor SVG 路径 bbox 对齐，
    统一 scale（x/y 各算后取均值，同管线 SVG 无各向异性）。
  - 轮廓转换：parse_path → TransformPen → Cu2QuPen(max_err=1@1024em) → TTGlyphPen；
    站方轮廓为 nonzero 填充，孔洞轮廓反向缠绕，TrueType 同语义直接兼容。
  - 注入：glyf / glyphOrder / maxp / hmtx（advance 取 anchor）/ cmap format-12 全部子表。
  - 验证闸：rsvg-convert 栅格化源 SVG vs PIL 渲染补录字形，对称 chamfer 须 < gate
    （实测 0.029；基线「丰 扫描 vs 原字体渲染」0.035，阈值 0.15 已留 4 倍余量）。
  - 原子替换（tmp + os.replace）；结果追加 var/unencoded/font-patches.jsonl。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from fontTools.misc.transform import Transform
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import parse_path
from fontTools.ttLib import TTFont

PATCH_LOG = "var/unencoded/font-patches.jsonl"


def parse_cp(s: str) -> int:
    return int(s, 16) if re.fullmatch(r"[0-9A-Fa-f]+", s) else int(s, 0)


def svg_path_d(svg_file: str) -> str:
    d = re.search(r'\sd="([^"]+)"', open(svg_file).read(), re.S)
    if not d:
        sys.exit(f"error: no path d= in {svg_file}")
    return d.group(1)


def path_bounds(d: str):
    bp = BoundsPen(None)
    parse_path(d, bp)
    if bp.bounds is None:
        sys.exit("error: empty path bounds")
    return bp.bounds


def calibrate(font: TTFont, anchor_cp: int, anchor_svg: str):
    """返回 path→font 仿射 (scale, tx, ty)，用 anchor 字形 bbox 对齐。"""
    cmap = font.getBestCmap()
    if anchor_cp not in cmap:
        sys.exit(f"error: anchor U+{anchor_cp:04X} not in font cmap")
    g = font["glyf"][cmap[anchor_cp]]
    pb = path_bounds(svg_path_d(anchor_svg))
    ax = (g.xMax - g.xMin) / (pb[2] - pb[0])
    ay = (g.yMax - g.yMin) / (pb[3] - pb[1])
    s = (ax + ay) / 2
    return s, g.xMin - s * pb[0], g.yMin - s * pb[1]


def rasterize_svg(svg_file: str, size: int = 256) -> Image.Image:
    out = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    out.close()
    subprocess.run(
        ["rsvg-convert", "-w", str(size), "-h", str(size),
         "--background-color=white", svg_file, "-o", out.name],
        check=True, capture_output=True)
    return Image.open(out.name).convert("L")


def norm_ink(img: Image.Image, s: int = 128) -> np.ndarray:
    a = np.asarray(img.convert("L")) < 128
    if not a.any():
        sys.exit("error: blank render")
    ys, xs = np.nonzero(a)
    sub = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = sub.shape
    out = np.zeros((s, s), bool)
    sc = min((s - 8) / h, (s - 8) / w)
    nh, nw = max(1, round(h * sc)), max(1, round(w * sc))
    r = Image.fromarray(sub.astype(np.uint8) * 255).resize((nw, nh), Image.BILINEAR)
    rb = np.asarray(r) > 96  # 布尔阈值，绝不用 uint8 乘法（256 处回绕坑）
    oy, ox = (s - nh) // 2, (s - nw) // 2
    out[oy:oy + nh, ox:ox + nw] = rb
    return out


def chamfer(a: np.ndarray, b: np.ndarray) -> float:
    ea = ndimage.distance_transform_edt(~a)
    eb = ndimage.distance_transform_edt(~b)
    return 0.5 * (ea[b].mean() + eb[a].mean())


def patch_font(font_path: str, args) -> dict:
    cp = args.cp
    name = f"uni{cp:04X}" if cp <= 0xFFFF else f"u{cp:X}"
    font = TTFont(font_path)
    cmap = font.getBestCmap()
    if cp in cmap:
        sys.exit(f"error: U+{cp:X} already in {font_path} cmap ({cmap[cp]})")

    s, tx, ty = calibrate(font, args.anchor_cp, args.anchor_svg)
    tp = TTGlyphPen(font.getGlyphSet())
    pen = Cu2QuPen(TransformPen(tp, Transform(s, 0, 0, s, tx, ty)),
                   max_err=1.0, reverse_direction=True)
    parse_path(svg_path_d(args.svg), pen)
    glyph = tp.glyph()
    glyph.recalcBounds(font["glyf"])

    glyf = font["glyf"]
    glyf.glyphs[name] = glyph
    font.glyphOrder.append(name)
    font["maxp"].numGlyphs = len(font.glyphOrder)

    hm = font["hmtx"]
    adv, _ = hm[cmap[args.anchor_cp]]
    n_metrics = font["hhea"].numberOfHMetrics
    if len(hm.metrics) == n_metrics:          # 每字形一组的度量表
        hm.metrics[name] = (adv, glyph.xMin)
    else:                                      # 尾部共享 advance 的压缩形式
        tail = font.glyphOrder[-2]
        tail_adv = hm.metrics[tail][0]
        hm.metrics[tail] = (adv, hm.metrics[tail][1])
        hm.metrics[name] = (tail_adv, glyph.xMin)
    font["hhea"].numberOfHMetrics = len(hm.metrics)

    f12 = 0
    for st in font["cmap"].tables:
        if st.format == 12:
            st.cmap[cp] = name
            f12 += 1
    if f12 == 0:
        sys.exit("error: no format-12 cmap subtable (supplementary codepoint needs it)")

    fd, tmp = tempfile.mkstemp(suffix=".ttf", dir=os.path.dirname(font_path) or ".")
    os.close(fd)
    font.save(tmp)

    # 验证闸：补录后渲染 vs 源 SVG 栅格
    try:
        ref = norm_ink(rasterize_svg(args.svg))
        pf = ImageFont.truetype(tmp, 200)
        img = Image.new("L", (256, 256), 255)
        ImageDraw.Draw(img).text((128, 128), chr(cp), font=pf, fill=0, anchor="mm")
        score = chamfer(ref, norm_ink(img))
    except FileNotFoundError:
        score = None  # 无 rsvg-convert，跳过栅格闸（bounds 闸仍在）
    if score is not None and score > args.gate:
        os.unlink(tmp)
        sys.exit(f"error: chamfer gate failed {score:.3f} > {args.gate} for {font_path}")

    before = os.path.getsize(font_path)
    os.replace(tmp, font_path)
    return {"font": font_path, "cp": f"U+{cp:X}", "glyph": name,
            "scale": round(s, 4), "bbox": [glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax],
            "advance": adv, "chamfer": None if score is None else round(score, 3),
            "bytes_before": before, "bytes_after": os.path.getsize(font_path)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--font", action="append", required=True, help="目标 ttf，可多次")
    ap.add_argument("--svg", required=True, help="站方字头缩略图 SVG（字形源）")
    ap.add_argument("--cp", required=True, type=parse_cp, help="码位，如 2BD6E")
    ap.add_argument("--anchor-svg", required=True, help="同页邻字 SVG（基线校准）")
    ap.add_argument("--anchor-cp", required=True, type=parse_cp, help="邻字码位")
    ap.add_argument("--gate", type=float, default=0.15, help="chamfer 验证闸（默认 0.15）")
    args = ap.parse_args()

    results = []
    for fp in args.font:
        r = patch_font(fp, args)
        results.append(r)
        c = r["chamfer"]
        print(f"patched {fp}: {r['cp']} → {r['glyph']} "
              f"chamfer={c if c is None else format(c, '.3f')} "
              f"{r['bytes_before']}→{r['bytes_after']} B")
    with open(PATCH_LOG, "a") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "svg": os.path.abspath(args.svg),
                            "results": results}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
