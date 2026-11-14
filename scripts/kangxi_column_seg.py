#!/usr/bin/env python3
"""康熙字典扫描图分层列分割：大列（两小列单位）→ 小列。

版式（像素实测，2026-11-14）：小列 ≈ 60px 宽、~24 字/列（字步进 ≈ 列距 ≈ 59px）；
字头大字列 ≈ 2× 小列宽且内部无谷（一个glyph），是天然的大列对齐锚点；本版无界行，
列界靠列间隙的墨迹剖面谷值检测。

层次结构（阅读序，右→左）：
  majors[]            大列：kind='pair'（两小列）| 'wide'（大字列，整段即一单元）
    └ minors[]        小列：x 范围 + 纵向墨迹范围 y1/y2 + 容量 cap（≈字数）
                        + chars_est（y 剖面字峰实测数）

用法：
  python3 scripts/kangxi_column_seg.py 333            # 打印 JSON
  python3 scripts/kangxi_column_seg.py 316 --draw     # 另存标注图 PNG（红=大列界，蓝=列内小列界）
  python3 scripts/kangxi_column_seg.py 312-335 --count # 各页列数统计（对照金标行数）

依赖：Pillow + numpy；无 OCR 依赖。正文块 bbox 默认取 VL 缓存的 vertical_text 块
（sha256 → paddleocr-baseline/data/ocr/ocr.sqlite3），不可用时回退全页投影自检。
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
MD = REPO / "paddleocr-baseline/data/ocr-markdown"
DB = REPO / "paddleocr-baseline/data/ocr/ocr.sqlite3"
IMGDIR = Path("/Volumes/WD-2T/guji-ocr/datasets/kangxizidian-wuyingdian")

DARK_THR = 140          # 二值化阈值（刻本墨色 < 140）
SMOOTH_K = 11           # x 剖面平滑窗
VALLEY_MAX_SEP = 40     # 相邻谷最小间隔（小于此合并，防一谷多峰）
MIN_MINOR_W = 30        # 小列最小宽度
MIN_INK_ROWS = 12       # 小列至少墨迹行数


def norm(text: str) -> str:
    PUNCT_STRIP = "。，·\"：:、；《》【】*　 \t\n\r〇○●"
    return "".join(ch for ch in text if ch not in PUNCT_STRIP)


def moving_avg(a, k):
    return np.convolve(a, np.ones(k) / k, mode="same")


def block_bbox_for(page: int):
    """VL 缓存 vertical_text 块 bbox；缺失回退 None。"""
    f = MD / f"{page:04d}.json"
    if not f.exists() or not DB.exists():
        return None
    try:
        sha = json.loads(f.read_text(encoding="utf-8"))["sha256"]
        row = sqlite3.connect(str(DB)).execute(
            "SELECT result_json FROM images WHERE sha256=?", (sha,)).fetchone()
        rj = json.loads(row[0])
        xs, ys = [], []
        for blk in rj["result"]["layoutParsingResults"][0]["prunedResult"]["parsing_res_list"]:
            if blk["block_label"] in ("vertical_text", "text"):
                x1, y1, x2, y2 = blk["block_bbox"]
                xs += [x1, x2]
                ys += [y1, y2]
        if xs:
            return min(xs), min(ys), max(xs), max(ys)
    except Exception:
        pass
    return None


def find_valleys(prof, med):
    """剖面谷：局部极小且 < 0.62×中位；间隔 < VALLEY_MAX_SEPX 的取最深者。"""
    cand = [i for i in range(SMOOTH_K, len(prof) - SMOOTH_K)
            if prof[i] <= prof[i - 1] and prof[i] <= prof[i + 1]
            and prof[i] < med * 0.62]
    sel = []
    for i in cand:
        if sel and i - sel[-1] < VALLEY_MAX_SEP:
            if prof[i] < prof[sel[-1]]:
                sel[-1] = i
        else:
            sel.append(i)
    return sel


def refine_valley(raw_prof, idx, win=8):
    """平滑剖面谷位 → 原始剖面 ±win 内精确化。"""
    lo = max(0, idx - win)
    hi = min(len(raw_prof), idx + win + 1)
    return lo + int(np.argmin(raw_prof[lo:hi]))


def minor_y_extent(dark_strip):
    """小列纵向墨迹范围（平滑 y 剖面，去孤立噪点）。"""
    yp = moving_avg(dark_strip.mean(axis=1), 5)
    rows = np.where(yp > 0.06)[0]
    if len(rows) < MIN_INK_ROWS:
        return None
    return int(rows[0]), int(rows[-1])


def char_peaks(dark_strip, char_h):
    """y 剖面字峰计数（字步进 ≈ char_h，峰间隔下限 0.75×char_h）。"""
    yp = moving_avg(dark_strip.mean(axis=1), max(5, int(char_h * 0.35)))
    thr = max(0.10, np.median(yp[yp > 0]) * 0.5) if (yp > 0).any() else 0.10
    minsep = max(20, int(char_h * 0.75))
    peaks = []
    for i in range(3, len(yp) - 3):
        if yp[i] >= yp[i - 1] and yp[i] >= yp[i + 1] and yp[i] > thr:
            if not peaks or i - peaks[-1] > minsep:
                peaks.append(i)
    return len(peaks)


def segment(page: int, img_path=None, dark_thr=DARK_THR):
    """返回 dict：block/pitch/majors（右→左，major 含 minors 右→左）。"""
    img_path = img_path or IMGDIR / f"{page:04d}.jpg"
    g = np.array(Image.open(img_path).convert("L"))
    bbox = block_bbox_for(page)
    if bbox is None:
        h, w = g.shape
        bbox = (50, 60, w - 50, h - 60)
    x0, y0, x1, y1 = bbox
    dark = (g < dark_thr).astype(np.float32)
    bx0, by0, bx1, by1 = x0 + 6, y0 + 6, x1 - 6, y1 - 6
    blk = dark[by0:by1, bx0:bx1]
    prof = moving_avg(blk.mean(axis=0), SMOOTH_K)
    prof[:SMOOTH_K] = prof[SMOOTH_K:2 * SMOOTH_K].mean()
    prof[-SMOOTH_K:] = prof[-2 * SMOOTH_K:-SMOOTH_K].mean()
    med = float(np.median(prof))

    valleys = find_valleys(prof, med)
    raw = blk.mean(axis=0)
    vx = [refine_valley(raw, i) for i in valleys]

    # 段边界（含块两端），段 = 相邻谷之间
    edges = [0] + vx + [len(prof)]
    segs = []
    for a, b in zip(edges, edges[1:]):
        if b - a < MIN_MINOR_W:
            continue
        segs.append((a, b))

    # pitch = 谷间距中位（滤极端值）
    gaps = [segs[i + 1][0] - segs[i][0] for i in range(len(segs) - 1)]
    ok_gaps = [d for d in gaps if 40 <= d <= 100]
    pitch = float(np.median(ok_gaps)) if ok_gaps else 60.0

    # 小列几何（阅读序右→左）
    minors = []
    for a, b in segs:
        strip = blk[:, a:b]
        ext = minor_y_extent(strip)
        if ext is None:
            continue
        yy0, yy1 = ext
        cap = max(1, round((yy1 - yy0) / pitch) + 1)
        minors.append(dict(
            x1=int(a + bx0), x2=int(b + bx0), cx=round((a + b) / 2 + bx0),
            y1=int(yy0 + by0), y2=int(yy1 + by0),
            cap=cap, chars_est=char_peaks(strip, pitch)))
    minors.sort(key=lambda m: -m["cx"])

    # 大列分组：宽段（≥1.5×pitch，大字列/无谷双列）自成大列并重置配对奇偶；
    # 其余从右向左两两配对。
    majors = []
    buf = []
    for m in minors:
        w = m["x2"] - m["x1"]
        if w >= pitch * 1.5:
            if buf:
                majors.append(buf)
                buf = []
            majors.append([m])
        else:
            buf.append(m)
            if len(buf) == 2:
                majors.append(buf)
                buf = []
    if buf:
        majors.append(buf)

    out = dict(page=page, block=[int(x0), int(y0), int(x1), int(y1)],
               pitch=round(pitch, 1), n_minors=len(minors), n_majors=len(majors),
               majors=[])
    for grp in majors:
        wide = len(grp) == 1 and (grp[0]["x2"] - grp[0]["x1"]) >= pitch * 1.5
        out["majors"].append(dict(
            kind="wide" if wide else f"pair{'-half' if len(grp) == 1 else ''}",
            x1=min(m["x1"] for m in grp), x2=max(m["x2"] for m in grp),
            minors=grp))
    return out


def draw(page: int, result: dict, img_path=None, out_path=None):
    img_path = img_path or IMGDIR / f"{page:04d}.jpg"
    out_path = out_path or f"/tmp/colseg_{page:04d}.png"
    im = Image.open(img_path).convert("RGB")
    dr = ImageDraw.Draw(im)
    x0, y0, x1, y1 = result["block"]
    dr.rectangle([x0, y0, x1, y1], outline=(0, 160, 0), width=2)
    for maj in result["majors"]:
        # 大列界：红
        for xx in (maj["x2"], maj["x1"]):
            dr.line([xx, y0, xx, y1], fill=(255, 0, 0), width=2)
        for m in maj["minors"]:
            # 小列界：蓝（大列内部）
            for xx in (m["x2"], m["x1"]):
                dr.line([xx, m["y1"], xx, m["y2"]], fill=(30, 80, 255), width=1)
            dr.text((m["x1"] + 2, m["y1"] + 2),
                    f"{m['chars_est']}/{m['cap']}", fill=(200, 0, 200))
    im.save(out_path)
    return out_path


def gold_line_count(page: int):
    sys.path.insert(0, str(REPO / "scripts"))
    from eval_ocr_fold import gj_bands
    f = REPO / "kangxi-gold/annotations" / f"{page:04d}.gj"
    if not f.exists():
        return None
    return sum(len(b) for b in gj_bands(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", help="页码：333 或 312-335")
    ap.add_argument("--draw", action="store_true")
    ap.add_argument("--count", action="store_true", help="列数 vs 金标行数对照")
    ap.add_argument("--img", help="覆盖扫描图路径")
    args = ap.parse_args()
    if "-" in args.pages:
        lo, hi = (int(x) for x in args.pages.split("-"))
        pages = list(range(lo, hi + 1))
    else:
        pages = [int(p) for p in args.pages.split(",")]

    for p in pages:
        try:
            res = segment(p, img_path=args.img)
        except FileNotFoundError:
            print(f"@{p}: 扫描图不存在", file=sys.stderr)
            continue
        if args.draw:
            print("saved:", draw(p, res))
        if args.count:
            gold = gold_line_count(p)
            wide = sum(1 for m in res["majors"] if m["kind"] == "wide")
            print(f"@{p}: 大列 {res['n_majors']}（大字列 {wide}）小列 {res['n_minors']}"
                  f" | 金标行 {gold}")
        else:
            print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
