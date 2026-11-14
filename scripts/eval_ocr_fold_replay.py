#!/usr/bin/env python3
"""OCR 折行回放验证：以初校页为基准，逐页重放 ocr_fold_page_lines。

口径（复现 cmd_ocr_fold 的真实链路，输入=初校 .gj 的大行结构）：
  in   = 初校 .gj 解析出的 bands（人工校对后的行界在带内）
  out  = ocr_fold_page_lines(page, in)  —— 函数内部先压平旧折再重折（幂等）
  GT   = 初校带内的物理行界

评估范围：正文带（首行非 #字头 / 非注释，且带内无 // 行——注释带原样透传，
字头带受结构保护整带不折，二者行界都不是折行算法的输出）。

头邻界单列不计分：初校页是物理行转写格式，#字头行可嵌在正文带内
（@331+ 与 @313–328 格式混用）；而生产草稿（build_page_draft）字头行
永远独占一带——字头行前/后/内部的折点在生产中是带界或结构行，不是
折行算法的责任，归为头邻界只统计不扣分。

指标（带界永不折，全局归一化坐标安全）：
  raw    折点原样复现（原始坐标一致，含标点贴随与初校逐字相同）
  贴字   归一化坐标一致但标点贴随不同（如【随上行还是下行）
  ±2     折点偏 1-2 字
  漏折   初校有界、算法未折（隐性成本：需人工补行）
  过分裂 算法折了、初校无界（可见成本：删行即�）
评分：10 - 0.35×漏折 - 0.30×过分裂 - 0.10×贴字 - 0.05×±2，下限 0；
  无折行需求且未折=10；有需求却未折行（对齐不可信等回退）=2。

输出：stdout 逐页人读报告（-v 带失败上下文）；--json 仅输出证据 JSON。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kangxi_page_tool as kpt  # noqa: E402
import kangxi_store  # noqa: E402

ANN = kpt.ANNOTATIONS


def gj_bands(page: int) -> list[list[str]]:
    """初校 .gj 的正文大行（与 cmd_ocr_fold 同一口径：@页码 后空行分带）。"""
    lines = (ANN / f"{page:04d}.gj").read_text(encoding="utf-8").splitlines()
    start = 0
    for i, l in enumerate(lines):
        if l.strip().startswith("@"):
            start = i + 1
            break
    bands: list[list[str]] = []
    cur: list[str] = []
    for l in lines[start:]:
        if l.strip():
            cur.append(l)
        elif cur:
            bands.append(cur)
            cur = []
    if cur:
        bands.append(cur)
    return bands


def is_content(band: list[str]) -> bool:
    """正文带：非字头/注释开头，且带内无 // 注释行（有则整带透传，非折行输出）。"""
    first = band[0].lstrip()
    if first.startswith("#") or first.startswith("//"):
        return False
    return not any("//" in l for l in band)


def breaks_of(bands: list[list[str]]):
    """正文带折点与字头行区间。

    返回 (pts, head_spans, raw_text)：
      pts        [(归一化偏移, 原始偏移, 头邻)] —— 带内行界（末行接带界不计），
                 头邻=行本身或下一行以 # 开头（字头行前/后界）
      head_spans [# 开头行在原文中的 (起,止) 区间] —— 供 OUT 折点归类
      raw_text   各行 strip 后拼接的原文（折行只插换行，内容应逐一对应）
    """
    pts: list[tuple[int, int, bool]] = []
    head_spans: list[tuple[int, int]] = []
    raw_parts: list[str] = []
    n_off = r_off = 0
    for band in bands:
        for li, l in enumerate(band):
            s = l.strip()
            starts_head = s.startswith("#")
            if starts_head:
                head_spans.append((r_off, r_off + len(s)))
            raw_parts.append(s)
            if li < len(band) - 1:
                nxt_head = band[li + 1].lstrip().startswith("#")
                pts.append((n_off + len(kpt._norm(s)), r_off + len(s),
                            starts_head or nxt_head))
            r_off += len(s)
            n_off += len(kpt._norm(s))
    return pts, head_spans, "".join(raw_parts)


def in_head(pos: int, spans: list[tuple[int, int]]) -> bool:
    """原文偏移 pos 落在字头行区间内（含起止两侧：起=行前界，止=行后界）。"""
    return any(s <= pos <= e for s, e in spans)


def compare(gt, out, head_spans, raw_text) -> dict:
    """两列折点按归一化偏移对齐（±2 容差），头邻/正文分别计数 + 失败上下文。"""
    res = dict(raw=0, punct=0, near=0, missed=0, false=0,
               head_hit=0, head_missed=0, head_false=0, ctx=[])
    i = j = 0
    used_out = [False] * len(out)
    while i < len(gt) and j < len(out):
        gn, gr, ghead = gt[i]
        on, orr, _ = out[j]
        if gn == on or abs(gn - on) <= 2:
            kind = "raw" if gn == on and gr == orr else (
                "punct" if gn == on else "near")
            if ghead:
                res["head_hit"] += 1
            else:
                res[kind] += 1
                if kind != "raw":
                    tag = "贴字" if kind == "punct" else "±2"
                    res["ctx"].append(f"{tag}@{gn} GT|…{raw_text[max(0, gr - 8):gr]}¦"
                                      f"{raw_text[gr:gr + 8]}")
            used_out[j] = True
            i += 1
            j += 1
        elif gn < on:
            if ghead:
                res["head_missed"] += 1
            else:
                res["missed"] += 1
                res["ctx"].append(f"漏折@{gn} …{raw_text[max(0, gr - 10):gr]}¦{raw_text[gr:gr + 10]}")
            i += 1
        else:
            if in_head(orr, head_spans):
                res["head_false"] += 1
                res["ctx"].append(f"头裂@{on} …{raw_text[max(0, orr - 10):orr]}¦{raw_text[orr:orr + 10]}")
            else:
                res["false"] += 1
                res["ctx"].append(f"分裂@{on} …{raw_text[max(0, orr - 10):orr]}¦{raw_text[orr:orr + 10]}")
            j += 1
    while i < len(gt):
        gn, gr, ghead = gt[i]
        if ghead:
            res["head_missed"] += 1
        else:
            res["missed"] += 1
            res["ctx"].append(f"漏折@{gn} …{raw_text[max(0, gr - 10):gr]}¦{raw_text[gr:gr + 10]}")
        i += 1
    while j < len(out):
        on, orr, _ = out[j]
        if not used_out[j]:
            if in_head(orr, head_spans):
                res["head_false"] += 1
                res["ctx"].append(f"头裂@{on} …{raw_text[max(0, orr - 10):orr]}¦{raw_text[orr:orr + 10]}")
            else:
                res["false"] += 1
                res["ctx"].append(f"分裂@{on} …{raw_text[max(0, orr - 10):orr]}¦{raw_text[orr:orr + 10]}")
        j += 1
    return res


def evaluate(page: int, store: kangxi_store.KangxiStore, verbose: bool) -> dict:
    bands = gj_bands(page)
    content_in = [b for b in bands if is_content(b)]
    gt_pts, head_spans, raw_text = breaks_of(content_in)
    gt_content = [p for p in gt_pts if not p[2]]

    folded, note = kpt.ocr_fold_page_lines(page, bands, store)
    content_out = [b for b in folded if b and is_content(b)]
    out_pts, out_spans, out_raw = breaks_of(content_out)

    row = dict(page=page, bands=len(bands), content_bands=len(content_in),
               gt_breaks=len(gt_content), gt_head_breaks=len(gt_pts) - len(gt_content),
               note=note)
    # 不变量：折行永不改字（正文归一化全文前后一致）
    row["chars_intact"] = kpt._norm(raw_text) == kpt._norm(out_raw)

    if folded is bands:  # 未折行回退
        if not gt_pts:
            row.update(score=10, raw=0, punct=0, near=0, missed=0, false=0,
                       head_hit=0, head_missed=0, head_false=0,
                       verdict="无折行需求，正确跳过")
        else:
            row.update(score=2, raw=0, punct=0, near=0, missed=len(gt_content), false=0,
                       head_hit=0, head_missed=len(gt_pts) - len(gt_content), head_false=0,
                       verdict=f"回退未折行：{note}（初校有 {len(gt_pts)} 处行界待补）")
        return row

    cmp_ = compare(gt_pts, out_pts, head_spans, raw_text)
    row.update({k: cmp_[k] for k in ("raw", "punct", "near", "missed", "false",
                                     "head_hit", "head_missed", "head_false")})
    pen = 0.35 * cmp_["missed"] + 0.30 * cmp_["false"] + 0.10 * cmp_["punct"] + 0.05 * cmp_["near"]
    row["score"] = max(0, round(10 - pen, 1))
    head_note = (f"，头邻界 命中{cmp_['head_hit']}/"
                 f"{cmp_['head_hit'] + cmp_['head_missed']}"
                 f" 头裂{cmp_['head_false']}"
                 if (gt_pts or cmp_["head_false"]) else "")
    if not gt_pts and not cmp_["false"]:
        row["verdict"] = "无折行需求，未多折"
    elif not gt_pts:
        row["verdict"] = f"无需求却折 {cmp_['false']} 处（过分裂）"
    elif cmp_["missed"] == cmp_["false"] == cmp_["punct"] == cmp_["near"] == 0:
        row["verdict"] = f"{len(gt_content)} 处折点全部原样复现"
    else:
        bits = []
        if cmp_["missed"]:
            bits.append(f"漏折 {cmp_['missed']}")
        if cmp_["false"]:
            bits.append(f"过分裂 {cmp_['false']}")
        if cmp_["punct"]:
            bits.append(f"贴字差 {cmp_['punct']}")
        if cmp_["near"]:
            bits.append(f"偏移 {cmp_['near']}")
        row["verdict"] = "、".join(bits) + head_note
    if verbose:
        row["ctx_detail"] = cmp_["ctx"]
    return row


def main() -> None:
    verbose = "-v" in sys.argv
    store = kangxi_store.KangxiStore()
    manifest = json.loads(kpt.MANIFEST.read_text(encoding="utf-8"))
    status = {p["page"]: p["status"] for p in manifest["pages"]}
    done = sorted(p for p, s in status.items() if s in ("first", "final"))

    report = []
    for page in done:
        try:
            row = evaluate(page, store, verbose)
        except Exception as e:  # noqa: BLE001
            row = dict(page=page, score=None, verdict=f"评估异常：{e!r}")
        report.append(row)
        if "--json" not in sys.argv:
            sc = row.get("score")
            print(f"@{page} 正文带{row.get('content_bands', '?')} "
                  f"折点{row.get('gt_breaks', '?')} | 原样{row.get('raw', '-')} "
                  f"贴字{row.get('punct', '-')} ±2 {row.get('near', '-')} "
                  f"| 漏{row.get('missed', '-')} 裂{row.get('false', '-')} "
                  f"| {sc if sc is not None else '—'}分 {row.get('verdict', '')}")
            if not row.get("chars_intact", True):
                print(f"    ✗ @{page} 字符不守恒（折行改字？！）")
            for c in row.get("ctx_detail", []):
                print(f"    · {c}")

    scored = [r["score"] for r in report if r.get("score") is not None]
    tot = dict(gt_breaks=0, raw=0, punct=0, near=0, missed=0, false=0,
               head_hit=0, head_missed=0, head_false=0)
    for r in report:
        for k in tot:
            tot[k] += r.get(k, 0) or 0
    hits = tot["raw"] + tot["punct"] + tot["near"]
    summary = {
        "pages": len(report), "scored": len(scored),
        "avg": round(sum(scored) / len(scored), 2) if scored else None,
        "dist": {str(k): scored.count(k) for k in sorted(set(scored))},
        "fails": [r["page"] for r in report if (r.get("score") or 10) <= 5],
        "breaks": tot,
        "break_recall": round(hits / tot["gt_breaks"], 4) if tot["gt_breaks"] else None,
        "break_precision": (round(hits / (hits + tot["false"]), 4)
                            if hits + tot["false"] else None),
        "raw_exact_rate": (round(tot["raw"] / tot["gt_breaks"], 4)
                           if tot["gt_breaks"] else None),
        "chars_intact": all(r.get("chars_intact", True) for r in report),
    }
    if "--json" in sys.argv:
        print(json.dumps({"summary": summary, "pages": report}, ensure_ascii=False, indent=1))
    else:
        print("\n" + json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
