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
  python3 tools/eval/kangxi_column_seg.py 316 --draw     # 标注图（红=大列界，蓝实=列内小列界·有谷值证据，
                                                      #   蓝虚=网格补位；紫标 chars/cap）
  python3 tools/eval/kangxi_column_seg.py 312-335 --count # 列数/pitch/证据率 vs 金标行数
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paths  # noqa: E402

MD = paths.OCR_CACHE_DIR
DB = REPO / "paddleocr-baseline/data/ocr/ocr.sqlite3"
IMGDIR = paths.RAW_KANGXI_PAGES

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


def frame_candidates(dark, expected_w=960):
    """版框线检测 → 候选框列表（按配对宽度接近 expected_w 排序）。

    不能只取最外线：版心鱼尾栏（@323 在 x 1023–1117 之间）夹在外线与文本框
    右线之间；也不能只按宽度配对：@330 的 1026 线配对更近但真右线是 1041
    （差 15px 即令网格拟合崩塌）。故每个右半线簇都出一个候选框，交由
    segment() 的拟合证据仲裁。左线缺失（@312 裁切）回退 x0 = x1 − expected_w。"""
    H, W = dark.shape
    band = dark[int(H * 0.2):int(H * 0.8)]
    colr = band.mean(axis=0)
    xc = np.where(colr > 0.5)[0]
    rowr = dark[:, int(W * 0.2):int(W * 0.8)].mean(axis=1)
    yc = np.where(rowr > 0.5)[0]
    if len(xc) < 2 or len(yc) < 2:
        return []

    def clusters(idx):
        out = []
        for i in idx:
            if out and i - out[-1][-1] <= 3:
                out[-1].append(i)
            else:
                out.append([i])
        return [int(np.mean(c)) for c in out]

    xs, ys = clusters(xc), clusters(yc)
    y_t, y_b = ys[0], ys[-1]
    cands = []  # (cost, x_l, x_r)
    for x_r in xs:
        if x_r < expected_w * 0.5:
            continue
        lefts = [l for l in xs if l < x_r - expected_w * 0.6]
        if lefts:
            x_l = min(lefts, key=lambda l: abs(l - (x_r - expected_w)))
            cands.append((abs((x_r - x_l) - expected_w), x_l, x_r))
        else:
            cands.append((float("inf"), x_r - expected_w, x_r))  # 左线缺失
    cands.sort(key=lambda c: c[0])
    out = [(x_l, y_t, x_r, y_b) for _, x_l, x_r in cands]
    outer = (xs[0], y_t, xs[-1], y_b)  # 原始簇极值对（@330 的真右线 1041 恰是外线）
    if not any(c[0] == outer[0] and c[2] == outer[2] for c in out):
        out.append(outer)
    return out


def frame_bbox(dark, expected_w=960):
    """兼容旧接口：最优配对候选框（choose_block/pass-1 用）。"""
    cs = frame_candidates(dark, expected_w)
    return cs[0] if cs else None


def choose_block(page: int, dark, expected_w):
    """VL vertical_text 块 vs 版框检测。

    VL 块会整页漏检半页（@312 宽 635、@330 宽 898 vs 框内 ~950+），是已知
    失效模式；版框只多含框线本身（内缩 +6 吸收）。故 VL 宽 < 92%×框宽时
    信框，否则信 VL（更紧，天然排除页眉页脚）。"""
    vl = block_bbox_for(page)
    fb = frame_bbox(dark, int(expected_w))
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


def _fit_for_block(dark, bbox, pitch_range):
    """单候选块的剖面/谷值/网格拟合。失败返回 None。"""
    x0, y0, x1, y1 = bbox
    bx0, by0, bx1, by1 = x0 + 6, y0 + 6, x1 - 6, y1 - 6
    if bx1 - bx0 < N_SLOTS * pitch_range[0] * 0.8:  # 块太窄放不下 16 列
        return None
    blk = dark[by0:by1, bx0:bx1]
    prof = moving_avg(blk.mean(axis=0), SMOOTH_K)
    prof[:SMOOTH_K] = prof[SMOOTH_K:2 * SMOOTH_K].mean()
    prof[-SMOOTH_K:] = prof[-2 * SMOOTH_K:-SMOOTH_K].mean()
    med = float(np.median(prof))
    vx = [refine_valley(blk.mean(axis=0), i) for i in find_valleys(prof, med)]
    on = np.where(prof > max(0.05, med * 0.35))[0]
    ink_lo, ink_hi = (int(on[0]), int(on[-1])) if len(on) > 10 else (0, blk.shape[1] - 1)
    fit = fit_grid(vx, ink_lo, ink_hi, 0, blk.shape[1] - 1, pitch_range)
    if fit is None:
        return None
    lines, pitch, R = fit
    lines, evidence = snap_lines(lines, vx)
    return dict(bbox=bbox, blk=blk, bx0=bx0, by0=by0, lines=lines, pitch=pitch,
                evidence=evidence, n_ev=sum(evidence))


def fishtail_x(dark, x_start):
    """版心魚尾检测：页面上部带内找「连续 ≥18 列、列墨迹 >0.45」的实心黑块。

    魚尾是版心的决定性特征（正文列/字头大字/框线的列墨迹都 ≤~0.2，框线窄于
    18px）。返回魚尾左缘 x 或 None。用于封顶版框候选的右线——版心栏
    （@323 x 1023–1117）夹在文本框右线与外线之间，谷值证据无法区分（魚尾
    边缘也产生锐利谷），只有魚尾实体是可靠判据。"""
    H = dark.shape[0]
    band = dark[int(H * 0.06):int(H * 0.40), int(x_start):]
    if band.shape[1] < 30:
        return None
    colr = band.mean(axis=0)
    run = 0
    for i, s in enumerate(colr > 0.45):
        run = run + 1 if s else 0
        if run >= 18:
            return int(x_start) + i - 17
    return None


def segment(page: int, img_path=None, dark_thr=DARK_THR, pitch_range=PITCH_RANGE):
    """返回 dict：block/pitch/lines/majors（右→左，major 含 minors 右→左）。

    块选择：VL vertical_text 块与版框配对块**各跑一次网格拟合，取谷值吸附
    证据多者**（平局信 VL——更紧）。宽度比例规则（如 VL<92%×框宽）不够判：
    @330 的坏 VL(898) 与修好的框(966) 只差 9px 就翻转，而两者的拟合证据
    差距悬殊（4/17 vs 13/17）。"""
    img_path = img_path or IMGDIR / f"{page:04d}.jpg"
    g = np.array(Image.open(img_path).convert("L"))
    dark_all = (g < dark_thr).astype(np.float32)
    expected_w = N_SLOTS * (pitch_range[0] + pitch_range[1]) / 2
    vl = block_bbox_for(page)
    # VL 宽度已达先验（±半列）→ VL 完整，直接采用。版框候选只为补救 VL 漏检
    # （@312/@330 漏掉字头大字区）而设；VL 完整时引入框反而危险——版心边缘
    # 也能产生锐利谷值证据，@323 曾以 13:11 的证据把网格右移到魚尾上。
    vl_complete = vl and abs((vl[2] - vl[0]) - expected_w) <= expected_w / N_SLOTS * 0.55
    cands = []
    if vl:
        cands.append(("vl", vl))
    if not vl_complete:
        fcs = frame_candidates(dark_all, int(expected_w))
        # 魚尾封顶：实心黑块右缘以内的框候选排除（版心栏右线不是文本框线）
        ft = fishtail_x(dark_all, int(dark_all.shape[1] * 0.55))
        if ft is not None:
            fcs = [c for c in fcs if c[2] <= ft + 10]
        cands += [("frame", fb) for fb in fcs[:4]]
    if not cands:
        H, W = dark_all.shape
        cands.append(("margin", (50, 60, W - 50, H - 60)))

    best = None  # (src, fit)：证据最高；严格大于才替换 → 平局保持先者（VL 优先）
    for src, bb in cands:
        f = _fit_for_block(dark_all, bb, pitch_range)
        if f and (best is None or f["n_ev"] > best[1]["n_ev"]):
            best = (src, f)
    if best is None:
        x0, y0, x1, y1 = cands[0][1]
        return dict(page=page, block=[int(x0), int(y0), int(x1), int(y1)],
                    error="no valleys detected")
    src, F = best
    bbox = F["bbox"]
    x0, y0, x1, y1 = bbox
    blk, bx0, by0 = F["blk"], F["bx0"], F["by0"]
    lines, pitch, evidence = F["lines"], F["pitch"], F["evidence"]

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
                block_src=src,
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
    sys.path.insert(0, str(Path(__file__).resolve().parent))
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
    global IMGDIR
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", help="页码：333 或 312-335")
    ap.add_argument("--draw", action="store_true")
    ap.add_argument("--count", action="store_true")
    ap.add_argument("--img", help="覆盖扫描图路径")
    ap.add_argument("--imgdir", type=Path, default=None,
                    help=f"扫描图目录（默认 {IMGDIR}；外置盘未挂载时必传或 --img）")
    args = ap.parse_args()
    if args.imgdir is not None:
        IMGDIR = args.imgdir
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
