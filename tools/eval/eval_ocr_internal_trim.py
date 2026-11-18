#!/usr/bin/env python3
"""只读可行性实验：用局部乱序锚点提出页中字头的多余尾段。

不修改草稿、金标、数据库或 OCR，不接入生产。默认评估全部初校页；
python3 tools/eval/eval_ocr_internal_trim.py --page 402 --json
金标仅用于事后评分；候选来自现有尾裁后草稿，前页续文沿用生产入口。
本实验只处理独立单字字头，不处理古文、标题、圈注及其他复杂作用域。
"""
from __future__ import annotations

import argparse
from collections import Counter
import difflib
import hashlib
import html
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))
import kangxi_page_tool as kpt


def norm(raw: str) -> str:
    lines = [l.split("//", 1)[0] for l in raw.splitlines()
             if not l.lstrip().startswith("@")]
    return kpt._norm("".join(lines)).replace("#", "")


def digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def source_card_probe(query: str, store) -> dict:
    """402 定向源站结构核验；仅提取归一化文字，非正式 HTML 解析器。"""
    with store._conn() as connection:
        row = connection.execute("SELECT raw_html, source_url FROM entries WHERE codepoint=?",
                                 (ord(query),)).fetchone()
    raw = row["raw_html"] or ""
    pattern = (r"武英殿本</a>：(\d+)頁，第(\d+)字\s*"
               r"<p><font20><font color=000000>(.*?)<P align='right'>")
    cards = []
    for m in re.finditer(pattern, raw, re.S):
        images = list(re.finditer(r"src=\.\./kxzt/([^\s>]+\.svg)", raw[:m.start()]))
        svg = images[-1][1] if images else None
        cp = re.search(r"-([0-9A-Fa-f]+)\.svg$", svg or "")
        text = html.unescape(re.sub(r"<[^>]*>", "", m[3])).replace("\xa0", " ")
        cards.append({"head": chr(int(cp[1], 16)) if cp else None,
                      "page": int(m[1]), "nth_char": int(m[2]), "svg": svg,
                      "normalized_text": norm(text)})
    selected = next((c for c in cards if c["head"] == query), None)
    kept, inline = (selected["normalized_text"], []) if selected else (None, [])
    if kept is not None:
        for m in re.finditer(r"（(.)）", kept):
            target = next((c for c in cards if c["head"] == m[1] and c["head"] != query), None)
            if target:
                inline.append({"head": m[1], "page": target["page"],
                               "text_equals_other_card": kept[m.end():] == target["normalized_text"]})
                kept = kept[:m.start()]
                break
    return {"query": query, "source_url": row["source_url"], "cards": cards,
            "inline_other_entry": inline, "selected_normalized_text": kept}


def sections(raw: str) -> tuple[list[dict], str | None]:
    if any(c in raw for c in ("古文", "□", "$", "(", ")", "（", "）", "〈", "〉")):
        return [], "复杂字头/作用域不在本实验范围"
    matches = list(re.finditer(r"(?m)^#([^\n]+)\n", raw))
    out = []
    for i, m in enumerate(matches):
        head = kpt._norm(m[1])
        if len(head) != 1:
            return [], "字头非独立单字"
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        body = raw[m.end():end]
        out.append({"head": head, "body": norm(body), "raw": body,
                    "offset": len(norm(raw[:m.end()]))})
    return out, None


def propose(raw: str, ocr: str) -> dict:
    """纯函数；所有阈值是探索性规则，非概率置信度。"""
    a = norm(raw)
    entries, skip = sections(raw)
    result = {"draft_chars": len(a), "ocr_chars": len(ocr), "skip": skip,
              "proposals": [], "accepted": False, "output": a}
    if skip:
        return result
    width = 4
    ac = Counter(a[i:i + width] for i in range(len(a) - width + 1))
    oc = Counter(ocr[i:i + width] for i in range(len(ocr) - width + 1))

    def anchors(text: str) -> list[tuple[int, int]]:
        return [(i, ocr.index(text[i:i + width]))
                for i in range(len(text) - width + 1)
                if ac[text[i:i + width]] == oc[text[i:i + width]] == 1]

    for e, nxt in zip(entries, entries[1:]):
        text = e["body"]
        aa = anchors(text)
        if not aa:
            continue
        cut = max(i + width for i, _ in aa)
        if len(text) - cut < 20:
            continue
        # 末个锚点必须恰好到句末，不把最后一次命中当作任意字符裁点。
        sentence_ends = {len(norm(e["raw"][:m.start()]))
                         for m in re.finditer("[。；]", e["raw"])}
        if cut not in sentence_ends:
            continue
        supported = {x for i, _ in aa for x in range(i, i + width)}
        coverage = len(supported) / cut
        tail_support = sum(x in supported for x in range(max(0, cut - 12), cut))
        next_anchors = anchors(nxt["body"][:32])
        next_supported = {x for i, _ in next_anchors for x in range(i, i + width)}
        if coverage < .55 or tail_support < 6 or len(next_supported) < 8:
            continue
        tail_ocr = [j + width for i, j in aa if i + width == cut]
        if min(abs(j - t) for _, j in next_anchors for t in tail_ocr) > 80:
            continue
        start, end = e["offset"] + cut, e["offset"] + len(text)
        result["proposals"].append({
            "head": e["head"], "next_head": nxt["head"],
            "start": start, "end": end, "removed_chars": end - start,
            "keep_tail": text[max(0, cut - 18):cut], "removed": text[cut:],
            "prefix_anchor_coverage": round(coverage, 4),
            "tail_supported_chars": tail_support,
        })
    removed = sum(p["removed_chars"] for p in result["proposals"])
    residual = len(a) - removed - len(ocr)
    tolerance = max(8, math.ceil(len(ocr) * .02))
    result.update(removed_chars=removed, residual_chars=residual, tolerance=tolerance)
    # 整页长度只是闸门：本规则无法识别 OCR 恰好漏掉整段的情况。
    result["accepted"] = bool(removed and abs(residual) <= tolerance)
    if result["accepted"]:
        out = a
        for p in reversed(result["proposals"]):
            out = out[:p["start"]] + out[p["end"]:]
        result["output"] = out
    return result


def score(a: str, gold: str, detection: dict) -> dict:
    kinds = ["ambiguous"] * len(a)
    for tag, i, j, _, _ in difflib.SequenceMatcher(None, a, gold, autojunk=False).get_opcodes():
        if tag in ("equal", "delete"):
            kinds[i:j] = ["gold" if tag == "equal" else "extra"] * (j - i)
    counts = Counter(kinds[i] for p in detection["proposals"]
                     for i in range(p["start"], p["end"])) if detection["accepted"] else Counter()
    return {"removed_extra": counts["extra"], "removed_gold": counts["gold"],
            "removed_ambiguous": counts["ambiguous"],
            "output_equals_gold": detection["output"] == gold}


def evaluate(page: int, store) -> dict:
    md = kpt._ocr_cache_read(page, store)
    if md is None:
        return {"page": page, "skip": "无有效 OCR 缓存"}
    cont, info = kpt.continuation_from_prev(page, store)
    draft, counts = kpt.build_draft_gj(page, store, cont or None, info.get("head"), fold=False)
    gold_raw = kpt.page_gj(page) or ""
    ocr = kpt._norm("".join(kpt._ocr_groups(md)))
    a, gold = norm(draft), norm(gold_raw)
    result = propose(draft, ocr)
    result.update(page=page, gold_chars=len(gold), baseline_notes=counts.get("ocr_notes"),
                  hashes={"draft": digest(draft), "gold": digest(gold_raw), "ocr": digest(md)},
                  scoring=score(a, gold, result))
    negative = propose(gold_raw, ocr)
    result["clean_gold_control"] = {key: negative.get(key) for key in
                                    ("skip", "accepted", "removed_chars", "residual_chars")}
    if page == 402:
        result["source_card_probes"] = [source_card_probe(h, store) for h in ("仅", "仆")]
        result["normalized_output"] = result["output"]
        result["monotonic_large_gaps"] = [
            {"tag": tag, "draft_chars": j - i, "ocr_chars": y - x,
             "draft_start": a[i:i + 30], "ocr_text": ocr[x:y]}
            for tag, i, j, x, y in difflib.SequenceMatcher(None, a, ocr, autojunk=False).get_opcodes()
            if tag != "equal" and j - i >= 20]
        # 可识别的失效模式：把整段从 OCR 中丢掉时，长度也同时减少。
        omitted = ["又集韻普木切音支義同又集韻韻會", "正韻叅敷救切否去聲頓也"]
        damaged = ocr
        for fragment in omitted:
            damaged = damaged.replace(fragment, "")
        omission = propose(gold_raw, damaged)
        result["synthetic_ocr_omission_control"] = {
            "removed_ocr_chars": len(ocr) - len(damaged),
            "omitted_ocr_fragments": omitted,
            "accepted": omission["accepted"], "proposals": omission["proposals"],
            "warning": "这是人工删 OCR 的压力样本，不是真实模型失误频率。",
        }
    result.pop("output")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", type=int, action="append")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    store = kpt.kangxi_store.KangxiStore(readonly=True)
    pages = args.page or [p["page"] for p in kpt.load_manifest()["pages"] if p.get("status") == "first"]
    results = [evaluate(page, store) for page in pages]
    accepted = [r for r in results if r.get("accepted")]
    summary = {"pages": len(results), "eligible": sum(not r.get("skip") for r in results),
               "skip_reasons": dict(Counter(r["skip"] for r in results if r.get("skip"))),
               "proposed_pages": [r["page"] for r in results if r.get("proposals")],
               "accepted_pages": [r["page"] for r in accepted],
               "removed_extra": sum(r["scoring"]["removed_extra"] for r in accepted),
               "removed_gold": sum(r["scoring"]["removed_gold"] for r in accepted),
               "removed_ambiguous": sum(r["scoring"]["removed_ambiguous"] for r in accepted),
               "clean_control_eligible": sum(not r.get("clean_gold_control", {"skip": True}).get("skip") for r in results),
               "clean_control_accepted": [r["page"] for r in results if r.get("clean_gold_control", {}).get("accepted")]}
    if args.json:
        print(json.dumps({"experiment": "只读探索；402 调参样本，不接入生产",
                          "script_sha256": digest(Path(__file__).read_text()), "summary": summary,
                          "results": results}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        for r in results:
            if r.get("proposals"):
                print(r["page"], "accept" if r["accepted"] else "review",
                      [(p["head"], p["removed_chars"]) for p in r["proposals"]], r["scoring"])


if __name__ == "__main__":
    main()
