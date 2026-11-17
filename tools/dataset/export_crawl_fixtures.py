#!/usr/bin/env python3
"""爬取侧 fixture 全量导出：entries.json + page-heads.json（guji-preview-grid
字头栏/字头弹窗的静态数据源）。两个入口共用同一份口径，防漂移：
- guji-preview-grid/scripts/link-dataset.sh 挂载后全量重建
- kangxi_page_tool.py cmd_add 加页后随写（曾致加页后字头栏显「爬取 0」，
  直到手动重跑 link-dataset.sh 才恢复——fixture 落后于库）

口径 = manifest 清单页 × kangxi_page_tool 查询 API（page_heads/entry_detail，
与爬取演示页同源）。爬取库不可用（本地 var/ 无库等）写空表并告警，不阻断。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GRID_DATASET = REPO / "guji-preview-grid" / "public" / "dataset"
ENTRIES_JSON = GRID_DATASET / "entries.json"
PAGE_HEADS_JSON = GRID_DATASET / "page-heads.json"

# entries.json 词条字段子集（与前端弹窗 CrawlEntryRecord 对齐）
KEEP = ("head", "guwen", "juan", "unicode", "radical", "radical_strokes",
        "extra_strokes", "total_strokes", "pinyin", "zhuyin", "cangjie",
        "unihan", "tongwen_edition", "wuying_edition", "text_paragraphs",
        "pua_other")


def head_item(it: dict) -> dict:
    cp = it.get("codepoint")
    return {"ord": it.get("ord"), "char": it.get("char"),
            "cp": f"{cp:X}" if cp else None, "k_code": it.get("k_code"),
            "svg": it.get("svg"), "entry_no": it.get("entry_no")}


def export(out_entries: Path, out_heads: Path, root: Path | None = None, *, announce: bool = True) -> dict:
    """全量导出两 fixture（sort_keys+indent 与历史产物一致）；返回统计。

    announce=False 供 cmd_add 内嵌调用：只写盘不出 stderr 统计行
    （调用方自行把返回值拼进响应 summaries）。
    """
    root = root or REPO
    manifest = json.load(open(root / "kangxi-gold" / "manifest.json", encoding="utf-8"))
    pages = [p["page"] for p in manifest["pages"]]

    records: dict[str, dict] = {}
    heads_by_page: dict[str, list[dict]] = {}
    db = None
    try:
        sys.path.insert(0, str(root / "tools/dataset"))
        import kangxi_page_tool as kpt  # 查询 API 门面（b6868ff：消费者 import 即用）

        if Path(kpt.kangxi_store.DEFAULT_DB).is_file():
            db = kpt.kangxi_store.DEFAULT_DB
            for page in pages:
                items = kpt.page_heads(page)
                heads_by_page[str(page)] = [head_item(it) for it in items]
                for it in items:
                    cp = it.get("codepoint")
                    if not cp:
                        continue  # 未编码 k_code：无详情端点
                    rec = kpt.entry_detail(cp)
                    if rec:
                        records[f"{cp:X}"] = {k: rec.get(k) for k in KEEP}
    except Exception as e:  # noqa: BLE001
        if announce:
            print(f"⚠ 爬取库不可用（{type(e).__name__}: {e}）——entries/page-heads 写空表，前端回退 .gj", file=sys.stderr)

    for path, obj in ((out_entries, records), (out_heads, heads_by_page)):
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    heads = sum(len(v) for v in heads_by_page.values())
    if announce:
        src = f"爬取库 {db}" if db else "无库（空表）"
        print(f"entries.json：{len(records)} 条词条；page-heads.json：{heads} 字头/{len(heads_by_page)} 页（{src}）", file=sys.stderr)
    return {"records": len(records), "heads": heads, "pages": len(heads_by_page), "db": db}


if __name__ == "__main__":
    # argv: [repo_root] [out_entries] [out_heads]——link-dataset.sh 显式传三参，
    # 裸跑用仓库内默认路径
    args = sys.argv[1:]
    root = Path(args[0]) if len(args) > 0 else None
    out_e = Path(args[1]) if len(args) > 1 else ENTRIES_JSON
    out_h = Path(args[2]) if len(args) > 2 else PAGE_HEADS_JSON
    export(out_e, out_h, root)
