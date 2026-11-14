#!/usr/bin/env python3
"""康熙字典扫描图分层列分割：大列（两小列单位）→ 小列。

版式先验（用户给定 + 像素实测，2026-11-14）：
  - **每页必有 8 大列 16 小列**；各页大列宽度大致相同、小列宽度大致相同。
  - 小列 ≈ 60px 宽、~24 字/列（字步进 ≈ 列距 ≈ 59px）；一条金标行 = 一个小列。
  - 字头大字 ≈ 2× 小列宽、内部无谷，横跨一个大列的两个小列位。
  - 本版无界行（只有外框线），列界靠列间隙的墨迹剖面谷值检测。

算法（先验约束网格）：
  1. x 剖面谷值检测 → 候选列界（只有「有证据」的线）。
  2. 拟合 17 条等距网格线（R−k·p, k=0..16 → 16 小列位）：2D 搜索
     (p, R)，代价 = 谷值到最近网格线距离 + 左右端对齐残差；pitch 搜索域
     多页运行时用全体页池化中位 ±3px（「各页宽度大致相同」先验）。
  3. 网格线吸附：±5px 内有谷值的线取谷值精位（detected），否则保持网格
     位置（grid）——变体区漏谷的小列由网格补出。
  4. 每小列位测纵向墨迹范围 y1/y2、容量 cap、字峰数 chars_est。

层次结构（阅读序，右→左）：
  majors[8]           大列：split=True（内部线 detected）/ False（大字列跨位）
    └ minors[2]       小列：x 范围 + y 墨迹 + cap + chars_est + bound 线证据

用法：
  python3 scripts/kangxi_column_seg.py 333            # JSON
  python3 scripts/kangxi_column_seg.py 316 --draw     # 标注图（红=大列界，蓝实=列内小列界·有谷值证据，
                                                      #   蓝虚=网格补位；紫标 chars/cap）
  python3 scripts/kangxi_column_seg.py 312-335 --count # 列数/pitch/证据率 vs 金标行数
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
VALLEY_MAX_SEP = 40     # 相邻谷最小间隔（小于此取最深者合并）
SNAP_TOL = 5.0          # 网格线吸附谷值的容差 px
N_SLOTS = 16            # 先验：每页 16 小列（17 条网格线）
PITCH_RANGE = (50.0, 70.0)
MIN_INK_ROWS = 12


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
    lo = max(0, idx - win)
    hi = min(len(raw_prof), idx + win + 1)
    return lo + int(np.argmin(raw_prof[lo:hi]))


def minor_y_extent(dark_strip):
    yp = moving_avg(dark_strip.mean(axis=1), 5)
    rows = np.where(yp > 0.06)[0]
    if len(rows) < MIN_INK_ROWS:
        return None
    return int(rows[0]), int(rows[-1])


def char_peaks(dark_strip, char_h):
    yp = moving_avg(dark_strip.mean(axis=1), max(5, int(char_h * 0.35)))
    thr = max(0.10, np.median(yp[yp > 0]) * 0.5) if (yp > 0).any() else 0.10
    minsep = max(20, int(char_h * 0.75))
    peaks = []
    for i in range(3, len(yp) - 3):
        if yp[i] >= yp[i - 1] and yp[i] >= yp[i + 1] and yp[i] > thr:
            if not peaks or i - peaks[-1] > minsep:
                peaks.append(i)
    return len(peaks)


def fit_grid(valleys, ink_lo, ink_hi, bound_lo, bound_hi, pitch_range):
    """17 条等距线 R−k·p（k=0..16）拟合谷值。

    代价 = Σ 谷值到最近线距离 + 端线对齐残差（左端线 vs 墨迹左缘）。
    返回 (lines_local, pitch, R)；lines_local 升序（左→右），17 条。
    """
    best = None
    if not valleys:
        return None
    v = np.asarray(valleys, dtype=float)
    for p in np.arange(pitch_range[0], pitch_range[1] + 1e-9, 0.2):
        # R（最右线）锚：墨迹右缘附近扫描；线须全部落在 [bound_lo, bound_hi]
        for R in np.arange(ink_hi - 8, ink_hi + 9, 1.0):
            lines = R - p * np.arange(N_SLOTS + 1)
            if lines[-1] < bound_lo or lines[0] > bound_hi:
                continue
            d = np.abs(v[:, None] - lines[None, :]).min(axis=1)
            cost = d.sum() + abs(lines[-1] - ink_lo)
            if best is None or cost < best[0]:
                best = (cost, lines.copy(), float(p), float(R))
    if best is None:  # 边界放不下 16 列：放宽 bound 再试一次
        return fit_grid(valleys, ink_lo, ink_hi, bound_lo - 40, bound_hi + 40, pitch_range)
    return best[1], best[2], best[3]


def snap_lines(lines, valleys):
    """±SNAP_TOL 内有谷值的线吸附谷值；返回 (snapped_lines, evidence[17])。"""
    out, ev = [], []
    for L in lines:
        near = [v for v in valleys if abs(v - L) <= SNAP_TOL]
        if near:
            out.append(float(min(near, key=lambda v: abs(v - L))))
            ev.append(True)
        else:
            out.append(float(L))
            ev.append(False)
    return out, ev


def frame_bbox(dark):
    """全页投影检测版框线（长连续深色线，占比>0.5）。返回 (x0,y0,x1,y1) 或 None。

    @312 类页面左框线被裁切时 x0 回退 x1−16×期望宽。"""
    H, W = dark.shape
    band = dark[int(H * 0.2):int(H * 0.8)]
    colr = band.mean(axis=0)
    xc = np.where(colr > 0.5)[0]
    rowr = dark[:, int(W * 0.2):int(W * 0.8)].mean(axis=1)
    yc = np.where(rowr > 0.5)[0]
    if len(xc) < 2 or len(yc) < 2:
        return None

    def clusters(idx):
        out = []
        for i in idx:
            if out and i - out[-1][-1] <= 3:
                out[-1].append(i)
            else:
                out.append([i])
        return [int(np.mean(c)) for c in out]

    xs, ys = clusters(xc), clusters(yc)
    x_r, x_l = xs[-1], xs[0]
    y_b, y_t = ys[-1], ys[0]
    if x_r - x_l < W * 0.5:  # 左线缺失（裁切）：按先验 16 列宽回推
        x_l = x_r - 960
    return x_l, y_t, x_r, y_b


def choose_block(page: int, dark, expected_w):
    """VL vertical_text 块 vs 版框检测。

    VL 块会整页漏检半页（@312 宽 635、@330 宽 898 vs 框内 ~950+），是已知
    失效模式；版框只多含框线本身（内缩 +6 吸收）。故 VL 宽 < 92%×框宽时
    信框，否则信 VL（更紧，天然排除页眉页脚）。"""
    vl = block_bbox_for(page)
    fb = frame_bbox(dark)
    if vl and fb:
        if (vl[2] - vl[0]) < 0.92 * (fb[2] - fb[0]):
            return "frame", fb
        return "vl", vl
    if fb:
        return "frame", fb
    if vl:
        return "vl", vl
    H, W = dark.shape
    return "margin", (50, 60, W - 50, H - 60)


def segment(page: int, img_path=None, dark_thr=DARK_THR, pitch_range=PITCH_RANGE):
    """返回 dict：block/pitch/lines/majors（右→左，major 含 minors 右→左）。"""
    img_path = img_path or IMGDIR / f"{page:04d}.jpg"
    g = np.array(Image.open(img_path).convert("L"))
    dark_all = (g < dark_thr).astype(np.float32)
    # 先验期望宽：16 × pitch 搜索域中点（多页运行时已被池化先验收窄）
    expected_w = N_SLOTS * (pitch_range[0] + pitch_range[1]) / 2
    src, bbox = choose_block(page, dark_all, expected_w)
    x0, y0, x1, y1 = bbox
    dark = dark_all
    bx0, by0, bx1, by1 = x0 + 6, y0 + 6, x1 - 6, y1 - 6
    blk = dark[by0:by1, bx0:bx1]
    prof = moving_avg(blk.mean(axis=0), SMOOTH_K)
    prof[:SMOOTH_K] = prof[SMOOTH_K:2 * SMOOTH_K].mean()
    prof[-SMOOTH_K:] = prof[-2 * SMOOTH_K:-SMOOTH_K].mean()
    med = float(np.median(prof))

    vx = [refine_valley(blk.mean(axis=0), i) for i in find_valleys(prof, med)]
    # 墨迹左右缘（x 剖面 > 中位×0.35 的范围）
    on = np.where(prof > max(0.05, med * 0.35))[0]
    ink_lo, ink_hi = (int(on[0]), int(on[-1])) if len(on) > 10 else (0, blk.shape[1] - 1)

    fit = fit_grid(vx, ink_lo, ink_hi, 0, blk.shape[1] - 1, pitch_range)
    if fit is None:
        return dict(page=page, block=[int(x0), int(y0), int(x1), int(y1)],
                    error="no valleys detected")
    lines, pitch, R = fit
    lines, evidence = snap_lines(lines, vx)

    # 小列位（右→左）：slot k 由 lines[k]（右界）与 lines[k+1]（左界）构成
    minors = []
    for k in range(N_SLOTS):
        L, Rr = lines[k + 1], lines[k]  # L < Rr（lines 升序）
        strip = blk[:, int(round(L)) + 1:int(round(Rr)) - 1]
        ext = minor_y_extent(strip) if strip.shape[1] >= 8 else None
        if ext:
            yy0, yy1 = ext
            cap = max(1, round((yy1 - yy0) / pitch) + 1)
            ce = char_peaks(strip, pitch)
            m = dict(x1=int(round(L) + bx0), x2=int(round(Rr) + bx0),
                     cx=int(round((L + Rr) / 2 + bx0)),
                     y1=int(yy0 + by0), y2=int(yy1 + by0), cap=cap, chars_est=ce)
        else:
            m = dict(x1=int(round(L) + bx0), x2=int(round(Rr) + bx0),
                     cx=int(round((L + Rr) / 2 + bx0)),
                     y1=None, y2=None, cap=0, chars_est=0)
        m["bound"] = "detected" if (evidence[k] and evidence[k + 1]) else "grid"
        minors.append(m)

    majors = []
    for j in range(N_SLOTS // 2):
        pair = minors[2 * j:2 * j + 2]
        majors.append(dict(
            kind="pair" if evidence[2 * j + 1] else "wide",
            x1=pair[1]["x1"], x2=pair[0]["x2"], minors=pair))

    return dict(page=page, block=[int(x0), int(y0), int(x1), int(y1)],
                pitch=round(pitch, 1), n_minors=N_SLOTS, n_majors=N_SLOTS // 2,
                lines_evidence=f"{sum(evidence)}/{len(lines)}",
                majors=majors)


def draw(page: int, result: dict, img_path=None, out_path=None):
    img_path = img_path or IMGDIR / f"{page:04d}.jpg"
    out_path = out_path or f"/tmp/colseg_{page:04d}.png"
    im = Image.open(img_path).convert("RGB")
    dr = ImageDraw.Draw(im)
    x0, y0, x1, y1 = result["block"]
    dr.rectangle([x0, y0, x1, y1], outline=(0, 160, 0), width=2)
    for j, maj in enumerate(result["majors"]):
        for xx in (maj["x2"], maj["x1"]):   # 大列界：红
            dr.line([xx, y0, xx, y1], fill=(255, 0, 0), width=2)
        for m in maj["minors"]:
            for xx, ev in ((m["x2"], True), (m["x1"], m["bound"] == "detected")):
                if xx in (maj["x2"], maj["x1"]):
                    continue
                if m.get("y1") is None:
                    continue
                if ev:   # 列内小列界：蓝实线（谷值证据）
                    dr.line([xx, m["y1"], xx, m["y2"]], fill=(30, 80, 255), width=1)
                else:    # 网格补位：蓝虚线
                    yy = m["y1"]
                    while yy < m["y2"]:
                        dr.line([xx, yy, xx, min(yy + 6, m["y2"])],
                                fill=(30, 80, 255), width=1)
                        yy += 12
            if m.get("y1") is not None:
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


def detect_page_pitch(page: int, img_path=None):
    """pass-1：仅谷值间距池化用（轻量，无网格拟合）。"""
    img_path = img_path or IMGDIR / f"{page:04d}.jpg"
    g = np.array(Image.open(img_path).convert("L"))
    dark_all = (g < DARK_THR).astype(np.float32)
    src, bbox = choose_block(page, dark_all, N_SLOTS * 59)  # 名义先验宽
    x0, y0, x1, y1 = bbox
    blk = dark_all[y0 + 6:y1 - 6, x0 + 6:x1 - 6]
    prof = moving_avg(blk.mean(axis=0), SMOOTH_K)
    med = float(np.median(prof))
    vx = find_valleys(prof, med)
    return [b - a for a, b in zip(vx, vx[1:]) if 40 <= b - a <= 100]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", help="页码：333 或 312-335")
    ap.add_argument("--draw", action="store_true")
    ap.add_argument("--count", action="store_true")
    ap.add_argument("--img", help="覆盖扫描图路径")
    args = ap.parse_args()
    if "-" in args.pages:
        lo, hi = (int(x) for x in args.pages.split("-"))
        pages = list(range(lo, hi + 1))
    else:
        pages = [int(p) for p in args.pages.split(",")]

    # 先验 pitch：多页运行时池化（各页宽度大致相同）；单页用本地谷距
    if len(pages) > 1:
        pooled = []
        for p in pages:
            try:
                pooled += detect_page_pitch(p, img_path=args.img)
            except FileNotFoundError:
                pass
        if pooled:
            g = float(np.median(pooled))
            pitch_range = (max(40.0, g - 3), min(80.0, g + 3))
        else:
            pitch_range = PITCH_RANGE
    else:
        pitch_range = PITCH_RANGE

    for p in pages:
        try:
            res = segment(p, img_path=args.img, pitch_range=pitch_range)
        except FileNotFoundError:
            print(f"@{p}: 扫描图不存在", file=sys.stderr)
            continue
        if "error" in res:
            print(f"@{p}: {res['error']}")
            continue
        if args.draw:
            print("saved:", draw(p, res))
        if args.count:
            gold = gold_line_count(p)
            wide = sum(1 for m in res["majors"] if m["kind"] == "wide")
            empty = sum(1 for maj in res["majors"] for m in maj["minors"] if m["cap"] == 0)
            print(f"@{p}: pitch={res['pitch']} 大列 {res['n_majors']}"
                  f"（wide {wide}）小列 {res['n_minors']}（空位 {empty}）"
                  f"线证据 {res['lines_evidence']} | 金标行 {gold}")
        else:
            print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
