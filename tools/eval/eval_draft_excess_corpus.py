#!/usr/bin/env python3
"""只读回放全部初校非空页，按语义字头比较草稿与初校并核验源站卡片。

金标只用于差异评分；源站候选由卡片身份和完整释文匹配决定。
不抓取、不调用 OCR、不写 .gj/manifest/数据库。JSON 写 stdout。
"""
from __future__ import annotations

from collections import Counter
import difflib
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))
import kangxi_page_tool as k
from kangxi_semantics import _line_tokens, find_host_marks, strip_guwen_prefix
import eval_ocr_internal_trim as pilot


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def visible(raw, small_only=False):
    return k._norm("".join(
        ch for line in raw.splitlines()
        if not re.fullmatch(r"\s*(@\d+|=+)\s*", line)
        for ch, large, *_ in _line_tokens(line) if not small_only or not large
    )).replace("•", "")


def small_raw(raw):
    raw = strip_guwen_prefix(raw)
    return "\n".join("".join(ch for ch, large, *_ in _line_tokens(line) if not large)
                     for line in raw.splitlines()
                     if not re.fullmatch(r"\s*(@\d+|=+)\s*", line))


def segments(raw, continuation_head=None):
    marks = find_host_marks(raw)
    starts = [raw.rfind("\n", 0, end) + 1 for _, end in marks]
    parts = []
    opening = small_raw(raw[:starts[0] if marks else len(raw)])
    if visible(opening):
        parts.append({"head": continuation_head, "body": visible(opening),
                      "raw": opening, "continuation": True})
    for i, (head, end) in enumerate(marks):
        body = small_raw(raw[end:starts[i + 1] if i + 1 < len(marks) else len(raw)])
        parts.append({"head": head, "body": visible(body), "raw": body, "continuation": False})
    return parts


def difference(a, b):
    return [{"tag": tag, "draft_start": i, "draft_end": j,
             "gold_start": x, "gold_end": y, "draft": a[i:j], "gold": b[x:y],
             "context": b[max(0, x - 15):x] + "│" + b[y:y + 15]}
            for tag, i, j, x, y in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
            if tag != "equal"]


def removal_score(a, gold, ranges):
    labels = ["ambiguous"] * len(a)
    for tag, i, j, _, _ in difflib.SequenceMatcher(None, a, gold, autojunk=False).get_opcodes():
        if tag in ("equal", "delete"):
            labels[i:j] = ["gold" if tag == "equal" else "extra"] * (j - i)
    positions = {i for start, end in ranges for i in range(start, end)}
    return dict(Counter(labels[i] for i in positions))


def source_plan(head, host_page, store, probe):
    """按页位选择卡片，再匹配其他卡片的完整正文；只返回库文删除坐标。"""
    detail = k.entry_detail(head, store)
    original = visible("".join(detail.get("text_paragraphs") or [])) if detail else ""
    cards = probe.get("cards", [])
    selected = [c for c in cards if c["head"] == head and c["page"] == host_page]
    result = {"host_page": host_page, "selected": None, "ranges": [], "original": original}
    if len(selected) != 1:
        result["reason"] = "无唯一匹配的字形＋页位卡片"
        return result
    selected = selected[0]
    result["selected"] = {key: selected[key] for key in ("head", "page", "svg")}
    for card in cards:
        if card is selected:
            continue
        # 本站 og 正文不包含独立的考證栏。此处仅为核验完整另一词条正文，
        # 不据字面“考證”直接修改生产数据。
        text = card["normalized_text"].split("考證")[0].replace("•", "")
        if len(text) < 4 or original.count(text) != 1:
            continue
        start = original.index(text)
        result["ranges"].append({"start": start, "end": start + len(text), "text": text,
                                  "other_head": card["head"], "other_page": card["page"]})
    return result


def ocr_suffix_candidates(raw, entries, ocr):
    """402 原型相同锚点/长度阈值，扩展为语义解析；未增加中段挖洞规则。"""
    a = visible(raw)
    width = 4
    ac = Counter(a[i:i + width] for i in range(len(a) - width + 1))
    oc = Counter(ocr[i:i + width] for i in range(len(ocr) - width + 1))

    def anchors(text):
        return [(i, ocr.index(text[i:i + width])) for i in range(len(text) - width + 1)
                if ac[text[i:i + width]] == oc[text[i:i + width]] == 1]

    proposals = []
    for ei, (entry, nxt) in enumerate(zip(entries, entries[1:])):
        if entry["continuation"]:
            continue
        text = entry["body"]
        aa = anchors(text)
        if not aa:
            continue
        cut = max(i + width for i, _ in aa)
        ends = {len(visible(entry["raw"][:m.start()])) for m in re.finditer("[。；]", entry["raw"])}
        if len(text) - cut < 20 or cut not in ends:
            continue
        supported = {x for i, _ in aa for x in range(i, i + width)}
        na = anchors(nxt["body"][:32])
        if len(supported) / cut < .55 or sum(x in supported for x in range(max(0, cut - 12), cut)) < 6:
            continue
        if len({x for i, _ in na for x in range(i, i + width)}) < 8:
            continue
        if min(abs(j - (y + width)) for _, j in na for i, y in aa if i + width == cut) > 80:
            continue
        proposals.append({"entry_index": ei, "head": entry["head"], "start": cut,
                          "end": len(text), "text": text[cut:]})
    removed = sum(p["end"] - p["start"] for p in proposals)
    tolerance = max(8, (len(ocr) + 49) // 50)
    residual = len(a) - removed - len(ocr)
    return {"proposals": proposals, "accepted": bool(proposals and abs(residual) <= tolerance),
            "residual_chars": residual, "tolerance": tolerance}


def main():
    store = k.kangxi_store.KangxiStore(readonly=True)
    manifest = k.load_manifest()
    rows, excluded, probes, source_plans = [], [], {}, {}
    all_source_scores = Counter()
    for p in manifest["pages"]:
        page = p["page"]
        if p.get("status") not in ("first", "final"):
            excluded.append({"page": page, "reason": p.get("status")})
            continue
        gold_raw = k.page_gj(page) or ""
        if not visible(gold_raw):
            excluded.append({"page": page, "reason": "empty"})
            continue
        cont, info = k.continuation_from_prev(page, store)
        raw, counts = k.build_draft_gj(page, store, cont or None, info.get("head"), fold=False)
        aa, gg = segments(raw, info.get("head")), segments(gold_raw, info.get("head"))
        md = k._ocr_cache_read(page, store)
        ocr = k._norm("".join(k._ocr_groups(md))) if md else None
        row = {"page": page, "gold_sha256": sha(gold_raw), "draft_sha256": sha(raw),
               "ocr_sha256": sha(md) if md else None, "ocr_chars": len(ocr) if ocr else None,
               "draft_chars": len(visible(raw)), "gold_chars": len(visible(gold_raw)),
               "baseline_notes": counts.get("ocr_notes"), "continuation": info,
               "entries": [], "draft_heads": [e["head"] for e in aa],
               "gold_heads": [e["head"] for e in gg]}
        for ei, entry in enumerate(aa):
            head, a = entry["head"], entry["body"]
            golds = [g for g in gg if g["head"] == head and g["continuation"] == entry["continuation"]]
            if len(golds) != 1:
                row["entries"].append({"head": head, "unmatched": True, "draft": a})
                continue
            gold = golds[0]["body"]
            erow = {"head": head, "continuation": entry["continuation"], "last": ei == len(aa) - 1,
                    "draft_chars": len(a), "gold_chars": len(gold), "diffs": difference(a, gold)}
            host_page = info.get("host_page") if entry["continuation"] else page
            if head not in probes:
                probes[head] = pilot.source_card_probe(head, store)
                source_row = store.get_entry(ord(head))
                probes[head]["raw_html_sha256"] = sha(source_row["raw_html"] or "")
                probes[head]["record_sha256"] = sha(source_row["record_json"])
            key = f"{head}@{host_page}"
            if key not in source_plans:
                source_plans[key] = source_plan(head, host_page, store, probes[head])
            plan = source_plans[key]
            projection = []
            # 草稿片段必须能唯一定位回完整库文，才投射其他词条的删除区间。
            if a and plan["original"].count(a) == 1:
                origin = plan["original"].index(a)
                for deletion in plan["ranges"]:
                    start = max(origin, deletion["start"])
                    end = min(origin + len(a), deletion["end"])
                    if end > start:
                        projection.append({"start": start - origin, "end": end - origin,
                                           "text": a[start-origin:end-origin],
                                           "other_head": deletion["other_head"],
                                           "other_page": deletion["other_page"]})
            erow["source_removals"] = projection
            erow["source_score"] = removal_score(a, gold, [(r["start"], r["end"]) for r in projection])
            all_source_scores.update(erow["source_score"])
            # 负对照：另一卡片完整正文若仍出现在初校中，单独报告，不擅自判错。
            erow["source_gold_hits"] = [r["other_head"] for r in plan["ranges"] if r["text"] in gold]
            row["entries"].append(erow)
        if ocr:
            row["original_pilot"] = {key: value for key, value in pilot.propose(raw, ocr).items() if key != "output"}
            refined = ocr_suffix_candidates(raw, aa, ocr)
            for proposal in refined["proposals"]:
                ei = proposal["entry_index"]
                entry = aa[ei]
                target = next(g["body"] for g in gg if g["head"] == entry["head"] and g["continuation"] == entry["continuation"])
                proposal["score"] = removal_score(entry["body"], target, [(proposal["start"], proposal["end"])])
            row["semantic_pilot"] = refined
            row["clean_gold_control"] = ocr_suffix_candidates(gold_raw, gg, ocr)
        rows.append(row)
    long_diffs = [{"page": r["page"], "head": e["head"], "last": e.get("last"),
                   "continuation": e.get("continuation"), **d}
                  for r in rows for e in r["entries"] for d in e.get("diffs", [])
                  if len(d["draft"]) >= 5 and len(d["draft"]) - len(d["gold"]) >= 4]
    out = {"scope": "当前已初校/精校非空页；当前代码回放，不是添加当时的历史草稿", "script_sha256": sha(Path(__file__).read_text()),
           "manifest_sha256": sha(k.MANIFEST.read_text()), "excluded": excluded,
           "summary": {"pages": len(rows), "valid_ocr_pages": sum(r["ocr_sha256"] is not None for r in rows),
                       "entries": sum(len(r["entries"]) for r in rows), "unique_heads": len(probes),
                       "multi_card_queries": [h for h, p in probes.items() if len(p["cards"]) > 1],
                       "source_projection_score": dict(all_source_scores),
                       "source_projection_pages": [r["page"] for r in rows if any(e.get("source_removals") for e in r["entries"])],
                       "semantic_ocr_proposed_pages": [r["page"] for r in rows if r.get("semantic_pilot", {}).get("proposals")],
                       "semantic_ocr_accepted_pages": [r["page"] for r in rows if r.get("semantic_pilot", {}).get("accepted")],
                       "clean_gold_false_deletion_pages": [r["page"] for r in rows if r.get("clean_gold_control", {}).get("accepted")]},
           "long_differences": long_diffs, "pages": rows, "source_probes": probes, "source_plans": source_plans}
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
