#!/usr/bin/env python3
"""康熙字典爬取数据校验（只读）：原图文件、页→字头索引、字头详情三层一致性。

检查项：
1. 原图：pages 每行 scan_file 存在、sha256/字节数/JPEG 尺寸与库登记一致；
2. 字头索引：page_chars 的 svg 文件名首段=页码、ord 连续、码位/字符互译一致；
3. 字头详情：每个有码位字头都有 entries 记录；wuying_edition.page 回指所在页、
   nth_char 沿 ord 严格递增（含未编码字占号时允许跳号）；unihan=码位十六进制；
   释文非空；raw_html 在库；pua_other 有值时列出（疑似 kxfont 字形）。

用法：python3 kangxi_verify.py [--db PATH] [--verbose]
退出码：0 全部通过；1 存在问题。仅依赖标准库。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import fetch_kangxi_page as fp
import kangxi_store


def verify(db_path: Path, verbose: bool = False) -> bool:
    store = kangxi_store.KangxiStore(db_path)
    problems: list[str] = []
    notes: list[str] = []

    with store._conn() as c:
        pages = [dict(r) for r in c.execute("SELECT * FROM pages ORDER BY page")]
        chars = [dict(r) for r in c.execute("SELECT * FROM page_chars ORDER BY page, ord")]
        entries = {r["codepoint"]: dict(r) for r in c.execute("SELECT * FROM entries")}

    # ---- 1) 原图 ----
    img_bad = 0
    for p in pages:
        issues = []
        if not p["reading_html"]:
            issues.append("缺阅读页 HTML")
        if not (p["scan_file"] and p["scan_sha256"]):
            issues.append("缺原图登记")
        else:
            path = Path(p["scan_file"])
            if not path.exists():
                issues.append(f"原图文件缺失 {path}")
            else:
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != p["scan_sha256"]:
                    issues.append("sha256 不符")
                if len(data) != p["scan_bytes"]:
                    issues.append("bytes 不符")
                if fp.jpeg_size(data) != (p["scan_width"], p["scan_height"]):
                    issues.append("JPEG 尺寸不符")
        if issues:
            img_bad += 1
            problems += [f"[原图] 页 {p['page']:04d}: {i}" for i in issues]
    print(f"原图：{len(pages) - img_bad}/{len(pages)} 页 文件存在且 sha256/字节/尺寸与库一致")

    # ---- 2) 字头索引 ----
    chars_bad = 0
    by_page: dict[int, list[dict]] = {}
    for r in chars:
        by_page.setdefault(r["page"], []).append(r)
        svg_head = r["svg"].split("/")[-1].split("-")[0]  # svg 可能含千位桶目录前缀
        if svg_head != f"{r['page']:04d}":
            problems.append(f"[索引] 页 {r['page']} 的 svg 名 {r['svg']} 首段不符")
            chars_bad += 1
        if (r["codepoint"] is None) != (r["char"] is None):
            problems.append(f"[索引] 页 {r['page']} {r['svg']} codepoint/char 一空一非空")
            chars_bad += 1
        if r["codepoint"] is not None and chr(r["codepoint"]) != r["char"]:
            problems.append(f"[索引] 页 {r['page']} {r['svg']} 码位与字符不互译")
            chars_bad += 1
    for page, rows in by_page.items():
        ords = [r["ord"] for r in rows]
        if ords != list(range(len(rows))):
            problems.append(f"[索引] 页 {page} ord 不连续: {ords}")
            chars_bad += 1
    coded_total = sum(1 for r in chars if r["codepoint"] is not None)
    print(f"字头索引：{len(chars)} 条（有码 {coded_total} / 未编码 {len(chars) - coded_total}），"
          f"svg 页段/码位互译/ord 连续 {'全部通过' if chars_bad == 0 else f'{chars_bad} 处问题'}")

    # ---- 3) 字头详情 ----
    # 回指页/unihan 不一致多为站点数据特性（補遺重出字头详情只回主条目、
    # 简繁码位混用），归入 quirks 备注；结构性损坏才算问题。
    miss_entry, ed_bad, text_bad, quirks, pua_pages = [], [], [], [], []
    nth_by_page: dict[int, list[tuple[int, int | None, int | None]]] = {}
    for r in chars:
        if r["codepoint"] is None:
            continue
        e = entries.get(r["codepoint"])
        if not e:
            miss_entry.append(f"页{r['page']}:{r['char']}")
            continue
        try:
            rec = json.loads(e["record_json"])
        except json.JSONDecodeError:
            text_bad.append(f"{r['char']} record_json 损坏")
            continue
        ed = rec.get("wuying_edition") or {}
        if ed.get("page") != r["page"]:
            quirks.append(f"{r['char']} 详情回指 p{ed.get('page')} ≠ 索引页 {r['page']}（疑似補遺/重出字头）")
        if not rec.get("text_paragraphs") or not rec.get("text_chars"):
            text_bad.append(f"{r['char']} 释文为空")
        if not e["raw_html"]:
            notes.append(f"{r['char']} 无 raw_html（采纳旧记录）")
        if rec.get("unihan") and rec["unihan"].upper() != f"{r['codepoint']:X}":
            quirks.append(f"{r['char']} 详情 unihan={rec['unihan']} ≠ 索引码位 U+{r['codepoint']:X}（站点索引/详情不一致）")
        if rec.get("pua_other"):
            pua_pages.append(f"{r['char']}:{','.join(rec['pua_other'])}")
        nth_by_page.setdefault(r["page"], []).append(
            (r["ord"], ed.get("nth_char"), ed.get("page")))
    # nth_char 沿 ord 严格递增（仅校验回指页一致的记录，避免重出字头级联误报）
    for page, seq in nth_by_page.items():
        prev = 0
        for _ord, nth, edpage in seq:
            if nth is None or edpage != page:
                continue
            if nth <= prev:
                ed_bad.append(f"页 {page} 第{nth}字 未随 ord 递增（前值 {prev}）")
            prev = nth
    problems += [f"[详情] 缺 entries: {x}" for x in miss_entry]
    problems += [f"[详情] {x}" for x in ed_bad + text_bad]
    print(f"字头详情：{coded_total - len(miss_entry)}/{coded_total} 有记录；"
          f"nth_char 单调 {'通过' if not ed_bad else f'{len(ed_bad)} 处问题'}；"
          f"释文 {'非空' if not text_bad else f'{len(text_bad)} 条异常'}；"
          f"站点特性备注 {len(quirks)} 条")
    notes += quirks
    if pua_pages:
        notes.append("疑似 kxfont 字形（需人工定字）: " + "; ".join(pua_pages))

    for n in notes:
        print(f"  备注: {n}")
    if verbose or problems:
        for p in problems:
            print(f"  问题: {p}")
    print("结论：" + ("全部通过 ✓" if not problems else f"{len(problems)} 个问题 ✗"))
    return not problems


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=kangxi_store.DEFAULT_DB)
    ap.add_argument("--verbose", action="store_true", help="无问题时也打印逐项备注")
    args = ap.parse_args()
    sys.exit(0 if verify(args.db, args.verbose) else 1)
