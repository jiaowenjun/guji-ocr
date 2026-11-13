#!/usr/bin/env python3
"""OCR 辅助导入全量测试：312–333（22 页，均已初校）作基准，测两项能力——

A. 文本范围（删头去尾）：候选续文（前页断点起的库内全量释义）经 OCR 裁剪，
   与初校 gj 对比：裁点偏移、首尾衔接。
   注：每页的"候选"按初校前页的断点重放（即 continuation_from_prev 逻辑），
   仅对纯延续页有意义（330/331 起）；312–328 样例页为首见页（无前页断点），
   范围测试改为：OCR 全文 vs 基准全文的覆盖率（页面物理范围识别能力）。
B. 折行边界：OCR markdown 空行组 = 物理行；测行界命中率（±0/±2/未中）、
   行数比、行首末字准确率。

输出 JSON 到 stdout（report 数据）。
"""
from __future__ import annotations
import difflib, json, sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
ANN = REPO / "kangxi-gold" / "annotations"
OCR_DIR = Path("/tmp/kx-fulltest/out")
PUNCT = "。，·\"::、；《》【】*　 \t\n\r◎〇"

def norm(t: str) -> str:
    return "".join(c for c in t if c not in PUNCT)

def gj_lines(page: int) -> list[str]:
    t = (ANN / f"{page:04d}.gj").read_text(encoding="utf-8")
    return [l for l in t.splitlines() if l.strip() and not l.strip().startswith(("//", "@"))]

def ocr_result(page: int) -> dict | None:
    f = OCR_DIR / f"{page:04d}.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text(encoding="utf-8"))
    r = d.get("result", {}).get("layoutParsingResults", [{}])[0]
    return (r.get("markdown") or {}).get("text") or ""

def blocks_of(a: str, b: str) -> list:
    return [x for x in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks() if x.size > 0]

report = {"pages": {}, "summary": {}}

fold_e0 = fold_e2 = fold_miss = 0
head_ok = tail_ok = line_pairs = 0
range_ok = range_low = range_none = 0
cer_sum = cer_n = 0

for page in list(range(312, 329)) + [330, 331, 332, 333]:
    lines = gj_lines(page)
    md = ocr_result(page)
    entry = {"gt_lines": len(lines)}
    if md is None:
        entry["error"] = "no ocr result"
        report["pages"][page] = entry
        continue
    groups = [g.replace("\n", "") for g in md.split("\n\n") if g.strip()]
    entry["ocr_groups"] = len(groups)
    gt_n = norm("".join(lines))
    ocr_n = norm("".join(groups))
    entry["gt_chars"], entry["ocr_chars"] = len(gt_n), len(ocr_n)

    # A. 范围（页面物理文本识别）：OCR vs 基准全文 覆盖/准确
    blks = blocks_of(gt_n, ocr_n)
    m = sum(b.size for b in blks)
    entry["range"] = {
        "coverage_of_gt": round(m / len(gt_n), 4) if gt_n else 0,
        "accuracy_of_ocr": round(m / len(ocr_n), 4) if ocr_n else 0,
        "matched": m,
    }
    cer = 1 - m / max(len(gt_n), len(ocr_n))
    entry["range"]["cer"] = round(cer, 4)
    cer_sum += cer * len(gt_n); cer_n += len(gt_n)
    # 首尾衔接：基准首 10 / 末 10 字是否都在 OCR 中（页面头尾识别）
    def sub_in(s): return s and s in ocr_n
    entry["range"]["head10_found"] = sub_in(gt_n[:10])
    entry["range"]["tail10_found"] = sub_in(gt_n[-10:]) if len(gt_n) >= 10 else sub_in(gt_n)
    if entry["range"]["head10_found"] and entry["range"]["tail10_found"] and cer < 0.15:
        range_ok += 1
    elif entry["range"]["coverage_of_gt"] < 0.5:
        range_low += 1

    # B. 折行：基准行界偏移 →（经匹配块映射）→ 最近 OCR 组界
    gt_off, acc = [], 0
    for l in lines:
        acc += len(norm(l)); gt_off.append(acc)
    ocr_off, acc = [], 0
    for g in groups:
        acc += len(norm(g)); ocr_off.append(acc)
    p = {"e0": 0, "e2": 0, "miss": 0}
    for off in gt_off[:-1]:
        pos = None
        for b in blks:
            if b.a <= off <= b.a + b.size:
                pos = b.b + (off - b.a); break
        if pos is None:
            p["miss"] += 1; continue
        near = min(ocr_off[:-1], key=lambda x: abs(x - pos)) if len(ocr_off) > 1 else None
        if near is None:
            p["miss"] += 1; continue
        d = abs(near - pos)
        if d == 0: p["e0"] += 1
        elif d <= 2: p["e2"] += 1
        else: p["miss"] += 1
    entry["folds"] = p
    fold_e0 += p["e0"]; fold_e2 += p["e2"]; fold_miss += p["miss"]
    # 行首末字（行数一致才比）
    if len(lines) == len(groups):
        for l, g in zip(lines, groups):
            nl, ng = norm(l), norm(g)
            if nl and ng:
                line_pairs += 1
                if nl[0] == ng[0]: head_ok += 1
                if nl[-1] == ng[-1]: tail_ok += 1
        entry["line_pairs"] = line_pairs
    report["pages"][page] = entry

tot_folds = fold_e0 + fold_e2 + fold_miss
report["summary"] = {
    "pages_total": len(report["pages"]),
    "range": {
        "ok_pages(head10&tail10&cer<0.15)": range_ok,
        "low_coverage_pages(<0.5)": range_low,
        "micro_cer": round(cer_sum / cer_n, 4) if cer_n else None,
    },
    "folds": {
        "boundaries_total": tot_folds,
        "hit_e0": fold_e0, "hit_e2": fold_e2, "miss": fold_miss,
        "hit_e0_rate": round(fold_e0 / tot_folds, 4) if tot_folds else None,
        "hit_e2_rate": round((fold_e0 + fold_e2) / tot_folds, 4) if tot_folds else None,
        "line_count_match_pages": sum(1 for e in report["pages"].values() if e.get("gt_lines") == e.get("ocr_groups")),
        "first_char_ok": head_ok, "last_char_ok": tail_ok, "line_pairs": line_pairs,
    },
}
print(json.dumps(report, ensure_ascii=False, indent=1))
