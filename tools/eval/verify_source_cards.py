#!/usr/bin/env python3
"""来源卡片实现验收：旧转写与实际生成链路回放，可附全缓存解析检查。

python3 tools/eval/verify_source_cards.py --cache > var/source-cards-verification.json
只读本地库／OCR／初校，不启动 OCR、不写生成页面。
"""
from collections import Counter
from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))
import kangxi_page_tool as k
import eval_draft_excess_corpus as audit
from kangxi_entry_parser import parse_detail, _normalized


def legacy_detail(head, store, **kwargs):
    row = store.get_entry(head if isinstance(head, int) else ord(head))
    if row is None:
        return None
    record = json.loads(row["record_json"])
    return record.get("legacy_entry", record)


def draft(page, store):
    cont, info = k.continuation_from_prev(page, store)
    raw, counts = k.build_draft_gj(page, store, cont or None, info.get("head"), fold=False)
    return raw, counts, info


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", action="store_true")
    args = ap.parse_args()
    store = k.kangxi_store.KangxiStore(readonly=True)
    result = {"at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
              "baseline": "同一生成流程，使用旧聚合转写；402按用户提供初校标准额外纳入",
              "pages": [], "removed_score": {}, "implementation_sha256": {}}
    for name in ["tools/crawl/kangxi_entry_parser.py", "tools/crawl/fetch_kangxi_entry.py",
                 "tools/dataset/kangxi_page_tool.py", "tools/crawl/kangxi_crawl_demo.py",
                 "tools/tests/test_kangxi_entry_parser.py", "tools/tests/fixtures/kangxi-entry-cards.json"]:
        result["implementation_sha256"][name] = hashlib.sha256((k.REPO / name).read_bytes()).hexdigest()
    removed = Counter()
    for item in k.load_manifest()["pages"]:
        page = item["page"]
        gold_raw = k.page_gj(page) or ""
        if (item.get("status") not in ("first", "final") and page != 402) or not audit.visible(gold_raw):
            continue
        with patch.object(k, "entry_detail", side_effect=legacy_detail):
            before, _, before_info = draft(page, store)
        after, counts, info = draft(page, store)
        aa = audit.segments(before, before_info.get("head"))
        bb = audit.segments(after, info.get("head"))
        gg = audit.segments(gold_raw, info.get("head"))
        changes = []
        for a in aa:
            b = next((x for x in bb if (x["head"], x["continuation"]) == (a["head"], a["continuation"])), None)
            g = next((x for x in gg if (x["head"], x["continuation"]) == (a["head"], a["continuation"])), None)
            new_text = b["body"] if b else ""
            if a["body"] == new_text:
                continue
            diffs = audit.difference(a["body"], new_text)
            ranges = [(d["draft_start"], d["draft_end"]) for d in diffs if d["tag"] == "delete"]
            score = audit.removal_score(a["body"], g["body"] if g else "", ranges)
            removed.update(score)
            changes.append({"head": a["head"], "continuation": a["continuation"],
                            "diffs": diffs, "removed_score": score})
        result["pages"].append({"page": page, "status": item.get("status"),
            "gold_sha256": hashlib.sha256(gold_raw.encode()).hexdigest(),
            "before_chars": len(audit.visible(before)), "after_chars": len(audit.visible(after)),
            "gold_chars": len(audit.visible(gold_raw)), "body_changes": changes,
            "stream_equal_gold": audit.visible(after) == audit.visible(gold_raw),
            "stream_changes": audit.difference(audit.visible(before), audit.visible(after)),
            "notes": counts["ocr_notes"], "continuation": info})
    result["removed_score"] = dict(removed)
    if args.cache:
        stats, changed, unverified = Counter(), [], []
        with store._conn() as connection:
            for row in connection.execute("SELECT sword,raw_html,record_json FROM entries"):
                stats["entries"] += 1
                if not row["raw_html"]:
                    stats["no_html"] += 1
                    continue
                parsed = parse_detail(row["raw_html"], row["sword"])
                if parsed is None:
                    stats["not_parsed"] += 1
                    continue
                stats[parsed["selection_status"]] += 1
                record = json.loads(row["record_json"])
                legacy = record.get("legacy_entry", record)
                old = _normalized("".join(legacy["text_paragraphs"]))
                new = _normalized("".join(parsed["text_paragraphs"]))
                if old != new:
                    stats["text_changed"] += 1
                    changed.append({"head": row["sword"], "before_chars": len(old), "after_chars": len(new)})
                    if parsed.get("text_origin") != "og_slice" or new not in old:
                        unverified.append(row["sword"])
                elif parsed["text_paragraphs"] != legacy["text_paragraphs"]:
                    stats["unchanged_content_format_changes"] += 1
                if old and not new:
                    stats["unexpected_empty"] += 1
        result["cache"] = {"stats": dict(stats), "changed": changed, "unverified_changes": unverified}
    result["summary"] = {"pages": len(result["pages"]),
                         "changed_pages": [p["page"] for p in result["pages"] if p["stream_changes"]],
                         "removed_score": dict(removed)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if removed["gold"] or removed["ambiguous"] or (args.cache and result["cache"]["unverified_changes"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
