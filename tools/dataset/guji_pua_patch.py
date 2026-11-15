#!/usr/bin/env python3
"""PUA 自补字形生产工具：把无 Unicode 码位的字形补入仓库字体（U+E700–E7FF 段）。

注册表：guji-preview-grid/src/pua-registry.json（码位=字位；改进=version+1 重补同码位）。
scheme：
  scan-trace  截图轮廓（x_contours.json：闭运算+Moore+DP 的折线），现有实现；
  compose     字体自有部件合成（E703 路线），预留接口 NotImplementedError；
  copy-glyph  整字复制（E702 路线），预留接口 NotImplementedError。
校准：每字体以其 U+343A 㐺 字形 bbox 为锚（同族形），轮廓方向对齐该字体自身外轮廓。
注入：glyf/glyphOrder/maxp/hmtx（advance=锚字）/**vmtx（有则必补，否则 compile KeyError）**/cmap format-4。
验证：rsvg 免依赖——PIL 渲染补录字形 vs verify_image 归一化 chamfer，闸默认 0.5
（光栅源管线标尺：E701 实测 0.366，含 DP 简化误差；矢量源管线沿用 0.15 见 kangxi_font_patch.py）。
留痕：font-patches.jsonl 追加 + 注册表 version/hash 更新 + 登记簿人工行（docs/font-operations.md）。

用法（自仓库根）：
  python3 tools/dataset/guji_pua_patch.py --cp E701 [--dry-run] [--gate 0.5]
"""

import argparse
import hashlib
import json
import os
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY = os.path.join(REPO, "guji-preview-grid/src/pua-registry.json")
PATCH_LOG = os.path.join(REPO, "var/unencoded/kangxi-unencoded/font-patches.jsonl")
ANCHOR_CP = 0x343A  # 㐺——三人同族形，各字体均有


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def signed_area(pts):
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return a / 2


def font_facts(font):
    """锚字 bbox、advance、外轮廓方向符号、有无 vmtx。"""
    cmap = font.getBestCmap()
    gs = font.getGlyphSet()
    bp = BoundsPen(gs)
    gs[cmap[ANCHOR_CP]].draw(bp)
    rec = RecordingPen()
    gs[cmap[ANCHOR_CP]].draw(rec)
    first_poly = []
    for op, args in rec.value:  # 第一段闭合轮廓折线化（定向用）
        if op == "moveTo":
            first_poly = [args[0]]
        elif op == "lineTo":
            first_poly.append(args[0])
        elif op == "qCurveTo":
            pts = [p for p in args if p is not None]
            first_poly.append(pts[-1])
        elif op == "closePath" and first_poly:
            break
    adv = font["hmtx"][cmap[ANCHOR_CP]][0]
    return bp.bounds, adv, signed_area(first_poly) >= 0, "vmtx" in font


def build_scan_trace(font, contours):
    """折线（像素 y-down）→ 该字体坐标的平滑二次贝塞尔字形。"""
    anchor_bbox, _, ref_ccw, _ = font_facts(font)
    all_pts = [p for c in contours["components"] for p in c["outer"]]
    px = [p[1] for p in all_pts]
    py = [p[0] for p in all_pts]
    pw, ph = max(px) - min(px), max(py) - min(py)
    s = ((anchor_bbox[2] - anchor_bbox[0]) / pw + (anchor_bbox[3] - anchor_bbox[1]) / ph) / 2
    tx = anchor_bbox[0] - s * min(px)
    ty = anchor_bbox[3] + s * min(py)
    tp = TTGlyphPen(font.getGlyphSet())
    for comp in contours["components"]:
        poly = [(tx + s * x, ty - s * y) for y, x in comp["outer"]]
        if (signed_area(poly) >= 0) != ref_ccw:
            poly = poly[::-1]
        n = len(poly)
        mids = [((poly[i][0] + poly[(i + 1) % n][0]) / 2,
                 (poly[i][1] + poly[(i + 1) % n][1]) / 2) for i in range(n)]
        tp.moveTo(mids[-1])
        for i in range(n):
            tp.qCurveTo(poly[i], mids[i])
        tp.closePath()
    return tp.glyph()


def build_compose(font, contours):
    raise NotImplementedError("compose 方案（E703 路线）预留：字体部件合成，见试验 var/unihan/trial_pua_patch.py")


def build_copy_glyph(font, contours):
    raise NotImplementedError("copy-glyph 方案（E702 路线）预留：整字复制")


BUILDERS = {"scan-trace": build_scan_trace, "compose": build_compose, "copy-glyph": build_copy_glyph}


def norm_ink(arr, size=128):
    a = arr if arr.dtype == bool else arr < 128
    ys, xs = np.nonzero(a)
    sub = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = sub.shape
    out = np.zeros((size, size), bool)
    sc = min((size - 8) / h, (size - 8) / w)
    r = Image.fromarray(sub.astype(np.uint8) * 255).resize(
        (max(1, int(w * sc)), max(1, int(h * sc))), Image.BILINEAR)
    rb = np.asarray(r) > 96
    oy, ox = (size - rb.shape[0]) // 2, (size - rb.shape[1]) // 2
    out[oy:oy + rb.shape[0], ox:ox + rb.shape[1]] = rb
    return out


def chamfer(a, b):
    ea = ndimage.distance_transform_edt(~a)
    eb = ndimage.distance_transform_edt(~b)
    return 0.5 * (ea[b].mean() + eb[a].mean())


def patch_font(font_path, cp, glyph, adv, has_vmtx_expected):
    font = TTFont(font_path)
    cmap = font.getBestCmap()
    name = f"uni{cp:04X}"
    _, _, _, has_vmtx = font_facts(font)
    glyf = font["glyf"]
    glyf.glyphs[name] = glyph  # 调用方按该字体坐标构建
    glyph.recalcBounds(glyf)
    if name not in font.glyphOrder:
        font.glyphOrder.append(name)
    font["maxp"].numGlyphs = len(font.glyphOrder)
    hm = font["hmtx"]
    hm.metrics[name] = (adv, glyf.glyphs[name].xMin)
    font["hhea"].numberOfHMetrics = len(hm.metrics)
    if has_vmtx:
        vm = font["vmtx"]
        va, vtsb = vm[cmap[ANCHOR_CP]]
        vm.metrics[name] = (va, vtsb)
    hit = 0
    # 只写 Windows/Unicode 子表；Mac (1,0,*) 的 format-0/6 子表区间小，
    # 塞 BMP PUA 会使 entryCount 撑爆 length 字段（guji-large 实测坑）
    ok = ((3, 1, 4), (0, 3, 4), (0, 4, 12), (3, 10, 12))
    for st in font["cmap"].tables:
        if (st.platformID, st.platEncID, st.format) in ok:
            st.cmap[cp] = name
            hit += 1
    if hit == 0:
        raise SystemExit(f"error: {font_path} 无可注入 cmap 子表")
    tmp = font_path + ".tmp"
    font.save(tmp)
    return tmp


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cp", required=True, help="注册表内码位，如 E701")
    ap.add_argument("--gate", type=float, default=0.5, help="chamfer 验证闸（光栅源默认 0.5）")
    ap.add_argument("--dry-run", action="store_true", help="只验证字形与 chamfer，不写文件")
    args = ap.parse_args()

    reg = json.load(open(REGISTRY))
    entry = next((g for g in reg["glyphs"] if g["cp"].upper() == args.cp.upper()), None)
    if entry is None:
        raise SystemExit(f"error: {args.cp} 不在注册表 {REGISTRY}")
    builder = BUILDERS[entry["scheme"]]
    contours = json.load(open(os.path.join(REPO, entry["source"])))
    verify = np.asarray(Image.open(os.path.join(REPO, entry["verify_image"])).convert("L")) < 128
    ref = norm_ink(verify)

    results = []
    for rel in entry["fonts"]:
        path = os.path.join(REPO, rel)
        before_hash, before_bytes = sha256(path), os.path.getsize(path)
        font = TTFont(path)
        if int(args.cp, 16) in font.getBestCmap():
            raise SystemExit(f"error: U+{args.cp} 已在 {rel} cmap（重补须先删或走 version 升级流程）")
        bbox, adv, _, _ = font_facts(font)
        glyph = builder(font, contours)          # 按该字体自身锚校准
        # 验证：临时保存渲染 vs 参照
        tmp = patch_font(path, int(args.cp, 16), glyph, adv, False)
        f = ImageFont.truetype(tmp, 220)
        img = Image.new("L", (300, 300), 255)
        ImageDraw.Draw(img).text((40, 40), chr(int(args.cp, 16)), font=f, fill=0)
        score = chamfer(norm_ink(np.asarray(img) < 128), ref)
        print(f"{rel}: chamfer={score:.3f} (gate {args.gate})", end="")
        if score > args.gate:
            os.unlink(tmp)
            raise SystemExit(f"  ✗ 闸失败，拒绝写入")
        print(f" ✓  {before_bytes}→{os.path.getsize(tmp)} B")
        if not args.dry_run:
            os.replace(tmp, path)
            entry["sha256_after"][os.path.basename(rel)] = sha256(path)
        else:
            os.unlink(tmp)
        results.append({"font": rel, "chamfer": round(score, 3),
                        "bytes_before": before_bytes, "bytes_after": os.path.getsize(path)})

    if not args.dry_run:
        entry["version"] += 1
        entry["patched_at"] = time.strftime("%Y-%m-%d")
        entry.setdefault("history", []).append(
            {"version": entry["version"], "at": entry["patched_at"],
             "scheme": entry["scheme"], "results": results})
        json.dump(reg, open(REGISTRY, "w"), ensure_ascii=False, indent=2)
        with open(PATCH_LOG, "a") as f:
            f.write(json.dumps({
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": "guji_pua_patch",
                "cp": f"U+{int(args.cp, 16):X}", "scheme": entry["scheme"],
                "version": entry["version"], "results": results}, ensure_ascii=False) + "\n")
        print(f"已写入 {len(results)} 字体；注册表 version → {entry['version']}；jsonl 已追加。")
        print("收尾：index.css 缓存戳递增 + docs/font-operations.md 登记行。")


if __name__ == "__main__":
    main()
