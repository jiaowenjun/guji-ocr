#!/usr/bin/env python3
"""前页续入回放验证：以初校页为基准，逐页重放 continuation_from_prev。

口径（复现 add 时的真实链路，唯一替换：前页 .gj 用初校版而非草稿版）：
  cont = continuation_from_prev(page)   —— 库内全量余段（未受页界约束）
  trim = ocr_trim_continuation(cont)    —— OCR 标尺裁到本页物理范围
  GT   = 初校 .gj 首个字头行之前的正文（人工放置在本页的续文）

指标（全部按 _norm 归一化）：
  host_ok   GT 前缀能在宿主字头库文内找到（宿主定位正确性）
  cover     cont 对 GT 的前缀覆盖率（未裁剪应 =100%，库内全量在手）
  over/under 裁剪末端相对 GT 末端的过留/欠留字数（SM 末块映射，容忍
             库文与图的零散异文——LCP 口径会被 1 字异文截断成假差异）
评分：10 = 与初校逐字一致；9/8/7 = 末端差 1-2/3-5/6-10 字；
5/3 = 差 11-20/20+ 字；漏续入=1；误宿主=2；正确跳过=10。

输出：stdout 逐页人读报告；末行 JSON 汇总（report 用）。
"""
from __future__ import annotations

import difflib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kangxi_page_tool as kpt  # noqa: E402
import kangxi_store  # noqa: E402

ANN = kpt.ANNOTATIONS

_STUB_RE = re.compile(r"^玉篇古文.字註詳.{0,3}畫?$")
_STRIP_SEP = r"[\s:：、]*"


def gj_bands(page: int) -> list[list[str]]:
    """初校 .gj 的正文大行（跳过头部注释与 @页码 行）。"""
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


def gt_leading(page: int) -> str:
    """首个字头行之前的正文（= 人工放置的前页续文），// 注释行跳过。

    按行判定而非空行分带：初校 .gj 的字头行独占一行但不必独占一带
    （482b91b 批量格式化后 @313–328 与 @331+ 格式混用），按带取会把
    行内 #字头 之后的下个词条正文误计入续文。
    """
    lines = (ANN / f"{page:04d}.gj").read_text(encoding="utf-8").splitlines()
    start = 0
    for i, l in enumerate(lines):
        if l.strip().startswith("@"):
            start = i + 1
            break
    out: list[str] = []
    for l in lines[start:]:
        s = l.strip()
        if not s or s.startswith("//"):
            continue
        if s.startswith("#"):
            break
        out.append(l)
    return "\n".join(out)


def lcp(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def find_fallback(hay: str, needle: str) -> int | None:
    """GT 前缀在库文定位：前缀长逐级回退（人工校订改了开头也不误判）。"""
    if not needle:
        return None
    for k in (16, 12, 8, 4):
        if len(needle) >= k:
            pos = hay.find(needle[:k])
            if pos >= 0:
                return pos
    return None


def entry_paras(store: kangxi_store.KangxiStore, head: str) -> list[str]:
    e = store.get_entry(ord(head)) if len(head) == 1 else None
    if not e:
        return []
    return [p for p in (json.loads(e["record_json"]).get("text_paragraphs") or []) if p.strip()]


def boundary_err(trim_n: str, gt_n: str) -> int:
    """裁剪末端 vs GT 末端的字数差（SM 末块两侧映射，容忍中间零散异文）。"""
    if not trim_n or not gt_n:
        return max(len(trim_n), len(gt_n))
    sm = difflib.SequenceMatcher(None, trim_n, gt_n, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
    if not blocks:
        return len(trim_n) + len(gt_n)
    end_t = max(b.a + b.size for b in blocks)
    end_g = max(b.b + b.size for b in blocks)
    return (len(trim_n) - end_t) + (len(gt_n) - end_g)


def score_page(gt_n: str, cont: list[str], trim_n: str, host_ok: bool) -> tuple[int, str]:
    if not gt_n and not cont:
        return 10, "正确跳过：本页首带即新字头，无续文"
    if not gt_n and cont:
        if not trim_n:
            return 9, "宿主条余段全在下页之后，OCR 裁剪净空——多续无害"
        return 3, f"误续入：GT 无续文却灌入 {len(trim_n)} 字"
    if not cont:
        return 1, "漏续入：GT 有续文但算法跳过"
    if not host_ok:
        return 2, "宿主疑似错位：GT 前缀不在该字头库文内"
    d = boundary_err(trim_n, gt_n) if trim_n else len(gt_n)
    if d == 0:
        if trim_n == gt_n:
            return 10, "与初校逐字一致"
        # 末端对齐但中间有零散异文（库文 vs 图）：续入范围正确，字差属数据源
        sm = difflib.SequenceMatcher(None, trim_n, gt_n, autojunk=False)
        diff = len(gt_n) - sum(b.size for b in sm.get_matching_blocks() if b.size)
        return 10, f"续入范围正确（末端对齐），中间零散异文 {diff} 字"
    if d <= 2:
        return 9, f"末端差 {d} 字"
    if d <= 5:
        return 8, f"末端差 {d} 字"
    if d <= 10:
        return 7, f"末端差 {d} 字"
    if d <= 20:
        return 5, f"末端差 {d} 字（较大）"
    return 3, f"末端差 {d} 字（过大）"


def main() -> None:
    verbose = "--json" not in sys.argv  # 人读逐页报告；--json 仅输出证据 JSON
    store = kangxi_store.KangxiStore()
    manifest = json.loads(kpt.MANIFEST.read_text(encoding="utf-8"))
    status = {p["page"]: p["status"] for p in manifest["pages"]}
    done = sorted(p for p, s in status.items() if s in ("first", "final"))

    cont_fn = kpt.continuation_from_prev
    report: list[dict] = []
    for page in done:
        gt_n = kpt._norm(gt_leading(page))
        row: dict = {"page": page, "gt_chars": len(gt_n)}

        if page - 1 not in status:
            row.update(score=None, note=f"前页 {page - 1} 缺档（数据缺口，非算法问题）")
            report.append(row)
            if verbose:
                print(f"@{page} GT {len(gt_n):>3} 字 | —— 跳过：前页 {page - 1} 缺档")
            continue

        cont, info = cont_fn(page, store)
        row.update(host=info.get("head"), host_page=info.get("host_page"),
                   skip=info.get("skipped"), cont_paras=info.get("paragraphs", 0))

        trim_n, trim_note = "", "（未执行）"
        if cont:
            trimmed, trim_note = kpt.ocr_trim_continuation(page, cont, store)
            trim_n = kpt._norm("\n".join(trimmed))
        row["trim_note"] = trim_note

        host_ok = True
        head = info.get("head")
        if gt_n and head:
            paras = entry_paras(store, head)
            if paras:
                entry_n = kpt._norm("".join(paras))
                host_ok = find_fallback(entry_n, gt_n) is not None

        cont_n = kpt._norm("\n".join(cont)) if cont else ""
        row.update(cont_chars=len(cont_n), trim_chars=len(trim_n))
        if gt_n and cont_n:
            row["cover"] = round(lcp(cont_n, gt_n) / len(gt_n), 3)
        if gt_n and trim_n:
            row["boundary_err"] = boundary_err(trim_n, gt_n)

        sc, verdict = score_page(gt_n, cont, trim_n, host_ok)
        row.update(score=sc, verdict=verdict)
        report.append(row)

        skip = info.get("skipped") or ""
        if verbose:
            print(
            f"@{page} GT {len(gt_n):>3} 字 | "
            + (f"跳过：{skip}" if skip else
               f"宿主「{head}」(@{info.get('host_page')}) 余 {info.get('paragraphs')} 段 {len(cont_n)} 字")
            + (f" | trim {len(trim_n)} 字（{trim_note}）" if cont else "")
            + (f" | cover {row.get('cover', '-')} 端差 {row.get('boundary_err', '-')}" if gt_n and cont else "")
            + f" | {sc} 分 {verdict}"
        )

    scored = [r["score"] for r in report if r.get("score") is not None]
    summary = {
        "pages": len(report),
        "scored": len(scored),
        "avg": round(sum(scored) / len(scored), 2) if scored else None,
        "dist": {str(k): scored.count(k) for k in sorted(set(scored))},
        "fails": [r["page"] for r in report if (r.get("score") or 10) <= 5],
        "gaps": [r["page"] for r in report if r.get("score") is None],
    }
    if "--json" in sys.argv:  # 证据文件模式：仅输出完整逐页 JSON
        print(json.dumps({"summary": summary, "pages": report}, ensure_ascii=False, indent=1))
        return
    print("\n" + json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
