#!/usr/bin/env python3
"""数据集对照页「添加新页」的桥接工具：补爬数据 → 生成 .gj 草稿 → 更新金标清单。

数据优先级（不重复爬虫）：kangxi-crawl.sqlite3 已有的页数据/字头详情直接用；
缺什么由 scripts/fetch_kangxi_page.py / fetch_kangxi_entry.py 增量补抓
（两者自身即「库里有则零网络请求」，页码页 2 个请求、字头详情每字 1 个请求）。

动作：
  add --page N          补数据 → 生成 kangxi-gold/annotations/NNNN.gj 草稿
                        （字头行 + 释义段落带；未编码字以 #□ + K 码注释占位）→
                        manifest.json 追加该页（status=draft）→ 重写
                        guji-preview-grid/public/dataset/index.json
  status --page N --to draft|first|final
                        改页标签（草稿/初校/精校）并同步 manifest 与 index.json

状态值：draft=草稿 / first=初校 / final=精校。
用法：python3 kangxi_page_tool.py add --page 329
仅依赖标准库。
"""
from __future__ import annotations

import argparse
import difflib
import io
import json
import time
import uuid
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kangxi_store  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
MANIFEST = REPO / "kangxi-gold" / "manifest.json"
ANNOTATIONS = REPO / "kangxi-gold" / "annotations"
INDEX_JSON = REPO / "guji-preview-grid" / "public" / "dataset" / "index.json"

STATUS_LABELS = {"draft": "草稿", "first": "初校", "final": "精校"}


def run_fetch(script: str, page: int, label: str) -> str:
    """复用既有爬取 CLI 增量补数据（库里有则零网络）。

    末行是全库 stats JSON（两个 fetch 脚本打印同一份），原样入 summaries 会让
    前端状态栏出现两段重复长 JSON——转为一句带 label 的人话摘要。
    """
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / script), "--pages", str(page)],
        capture_output=True, text=True, timeout=600,
    )
    if r.returncode != 0:
        raise RuntimeError(f"{script} 退出码 {r.returncode}\n{r.stdout}\n{r.stderr}")
    last = (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else ""
    try:
        stats = json.loads(last)
    except ValueError:
        stats = None
    if isinstance(stats, dict) and "pages_total" in stats:
        return f"{label}：联网补抓完成（库内 {stats['pages_total']} 页 / {stats['entries_total']} 条字头）"
    return f"{label}：{last[:80]}" if last else f"{label}：完成"


PUNCT_STRIP = "。，·\"：:、；《》【】*　 \t\n\r"


def _norm(text: str) -> str:
    """清洗为匹配口径：去标点/空白/书名括号（与 .gj 词法的剔除集一致）。"""
    return "".join(ch for ch in text if ch not in PUNCT_STRIP)


def continuation_from_prev(
    page: int, store: kangxi_store.KangxiStore
) -> tuple[list[str], dict]:
    """前页（page-1）未完字头续入：取「宿主字头之后已放置的全部文本」在库内
    该字头的全量释义（段落拼接）中定位，返回余下的段落列表（首段可为半段，
    保留原文标点与未闭合书名的闭合括号）。

    宿主定位两级回溯：前页有字头则在前页找最后一个有库内详情者（行内
    「古文」变体无详情，溢出的是宿主字头）；前页是纯延续页（无字头标记，
    如 @332 整页是 @331「中」的续文）则逐页向前找宿主页，尾部 = 宿主页
    该字头之后 + 其后相邻页到 page-1 的全文拼接（已放置文本跨页累计）。

    跨页书名靠 per-page 语义边界自然衔接：前页未闭合书名渲染为下开口，
    本页行首的孤儿】延续渲染为上开口（无需跨文件机制）。
    """
    info = {"prev_page": page - 1, "head": None, "paragraphs": 0, "skipped": None}
    prev_gj = ANNOTATIONS / f"{page - 1:04d}.gj"
    if not prev_gj.exists():
        info["skipped"] = f"前页 {page - 1} 不在数据集"
        return [], info

    def host_in(raw_text: str):
        """在单页文本中找最后一个有库内详情的字头；返回 (head, entry, tail_raw)"""
        marks = list(re.finditer(r"#([^#(\s【□])", raw_text))
        for m in reversed(marks):
            cand = m.group(1)
            e = store.get_entry(ord(cand)) if len(cand) == 1 else None
            if e is not None:
                return cand, e, raw_text[m.end():]
        return None, None, ""

    raw = prev_gj.read_text(encoding="utf-8")
    head, entry, tail_raw = host_in(raw)
    info["host_page"] = page - 1
    if entry is None:
        # 前页是纯延续页：逐页向前找宿主页，边回溯边累计纯延续页全文（正序），
        # 尾部 = 宿主页字头后文本 + 其后各页（含前页）全文拼接——支持任意长延续链
        chained: list[str] = [raw]  # 回溯途经的纯延续页（倒序收集，最后正序拼接）
        back = page - 2
        while back >= 1:
            cand_gj = ANNOTATIONS / f"{back:04d}.gj"
            if not cand_gj.exists():
                break  # 数据集不连续，回溯终止
            cand_raw = cand_gj.read_text(encoding="utf-8")
            h, e, t = host_in(cand_raw)
            if e is not None:
                head, entry = h, e
                tail_raw = t + "\n" + "\n".join(reversed(chained))
                info["host_page"] = back
                break
            chained.append(cand_raw)
            back -= 1
        if entry is None:
            info["skipped"] = "前页及回溯各页的字头在库中均无详情"
            return [], info
    if entry is None:
        info["skipped"] = "前页字头在库中均无详情"
        return [], info
    info["head"] = head
    # 剥离尾部的「古文#变体…」前缀：变体字头是词条页元数据，不在释义段文本内
    tail_raw = re.sub(r"^\s*古文(?:#[^#\s【(]){1,4}", "", tail_raw)
    paragraphs = [
        p for p in (json.loads(entry["record_json"]).get("text_paragraphs") or []) if p.strip()
    ]
    if not paragraphs:
        info["skipped"] = f"字头「{head}」无释义段"
        return [], info

    tail_n = _norm(tail_raw)
    if not tail_n:
        info["skipped"] = "前页该字头无正文（可能整段在后页）"
        return [], info

    # 全量释义拼接（含归一化坐标 → (段序, 段内原文下标) 映射）
    full = "\u0001".join(paragraphs)
    norm_chars: list[str] = []
    idx_map: list[tuple[int, int]] = []
    for pi, para in enumerate(paragraphs):
        for ci, ch in enumerate(para):
            if ch not in PUNCT_STRIP:
                norm_chars.append(ch)
                idx_map.append((pi, ci))
    entry_n = "".join(norm_chars)

    # 定位：先锚定（尾部前缀在库文中找起点），再容差对齐到尾串末尾——
    # 前页可能有个别校订增删（如站点文本少一字），整串子串匹配会整体失败
    anchor = -1
    for k in range(min(len(tail_n), 24), 7, -1):
        anchor = entry_n.find(tail_n[:k])
        if anchor >= 0:
            break
    if anchor < 0:
        info["skipped"] = "前页尾部与库内段落不匹配（可能已大幅校订），未自动续入"
        return [], info
    sm = difflib.SequenceMatcher(None, entry_n, tail_n, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
    covered = sum(b.size for b in blocks)
    if covered / len(tail_n) < 0.9:
        info["skipped"] = (
            f"前页尾部与库内段落对齐覆盖率 {covered}/{len(tail_n)} 过低，未自动续入"
        )
        return [], info
    end = max(b.a + b.size for b in blocks)
    if end >= len(entry_n):
        info["skipped"] = (
            f"前页 {page - 1} 的 .gj 已完整收录字头「{head}」全部 {len(paragraphs)} 段"
            f"（物理上可能延伸到本页及以后）——请先在校对中把前页裁剪到其物理页界，"
            f"再添加本页，余段将自动续入"
        )
        info["fully_included"] = True
        return [], info
    pi0, ci0 = idx_map[end]
    out: list[str] = []
    rest = paragraphs[pi0][ci0:].strip()
    if rest:
        out.append(rest)
    out.extend(paragraphs[pi0 + 1:])
    info["paragraphs"] = len(out)
    return out, info


def ocr_trim_continuation(
    page: int, continuation: list[str], store: kangxi_store.KangxiStore
) -> tuple[list[str], str]:
    """用 PaddleOCR 基线服务把续文裁剪到页面物理范围（删头去尾）。

    文本始终以库内转写为准，OCR 只作范围标尺（2026-11-13 试探：@333 单页
    96.5% 准确率，自动裁剪与人工初校差 1 字）。流程：取该页扫描图 → 本地
    服务 /ocr 同步提交（服务未启动/识别失败时原样返回并说明，回退全量灌入）。
    """
    import urllib.request

    base = "http://127.0.0.1:8010"
    img = Path(store.get_page(page)["scan_file"])
    if not img.is_file():
        return continuation, "无扫描图，未裁剪"
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=3) as r:
            if json.loads(r.read()).get("service") != "ocr":
                return continuation, "OCR 服务未运行，未裁剪"
    except Exception:
        return continuation, "OCR 服务未运行，未裁剪"

    boundary = uuid.uuid4().hex
    payload = img.read_bytes()
    file_field = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{img.name}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{base}/ocr/images",
        data=file_field,
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        submit = json.loads(r.read())
    image_id = submit.get("image_id")
    if not image_id:
        return continuation, "OCR 提交未返回 image_id，未裁剪"
    deadline = time.time() + 600
    view = {}
    while time.time() < deadline:
        time.sleep(3)
        with urllib.request.urlopen(f"{base}/ocr/images/{image_id}", timeout=30) as r:
            view = json.loads(r.read())
        # weimo 视图：result 非 null 即终态成功；error 非 null 即失败
        if view.get("result") is not None:
            break
        if view.get("error") is not None:
            return continuation, f"OCR 任务失败（{view.get('error')}），未裁剪"
    else:
        return continuation, "OCR 轮询超时，未裁剪"

    result_view = view.get("result") or {}
    md_text = result_view.get("markdown") or ""
    if not md_text:
        md_text = (
            ((result_view.get("json") or {}).get("result") or {}).get("layoutParsingResults")
            or [{}]
        )[0].get("markdown", {}).get("text", "")

    cand_n = _norm("\n".join(continuation))
    ocr_n = _norm(md_text)
    if not ocr_n:
        return continuation, "OCR 无文本输出，未裁剪"
    sm = difflib.SequenceMatcher(None, cand_n, ocr_n, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
    cover = sum(b.size for b in blocks)
    end = max(b.a + b.size for b in blocks)
    # 门槛按「裁点前区域」判信而非 OCR 全长：页面含新字头时匹配数天然小于
    # OCR 全文（334：候选末段 375 字，页面上只有前 ~79 字）。要求裁点区域
    # 至少 20 字且其中过半是真实匹配（连续性证据），否则放弃裁剪回退全量
    if end < 20 or cover < end * 0.5:
        return continuation, f"OCR 与续文对齐不可信（裁点 {end} 字中匹配 {cover}），未裁剪"
    if end >= len(cand_n):
        return continuation, "续文已在页面范围内，无需裁剪"

    # 归一化裁点映射回原文：走一遍续文原文累计（跳过被剔除字符），取第 end 个保留字
    kept = 0
    cut_para, cut_idx = len(continuation) - 1, len(continuation[-1])
    for pi, para in enumerate(continuation):
        for ci, ch in enumerate(para):
            if ch in PUNCT_STRIP:
                continue
            if kept == end:
                cut_para, cut_idx = pi, ci
                break
            kept += 1
        else:
            continue
        break
    trimmed = list(continuation[:cut_para])  # 裁点前的整段全部保留
    if cut_idx > 0:
        trimmed.append(continuation[cut_para][:cut_idx].rstrip())  # 裁点所在段取前半
    removed = len(cand_n) - end
    return trimmed, f"OCR 裁剪：保留 {end}/{len(cand_n)} 字（页面物理末界），溢出 {removed} 字留给下页"


def build_draft_gj(
    page: int,
    store: kangxi_store.KangxiStore,
    continuation: list[str] | None = None,
    skip_head: str | None = None,
) -> tuple[str, dict]:
    """由库内 page_chars + entries 生成 .gj 草稿与统计；continuation 为前页
    未完字头的续文行（置于新字头之前，符合阅读顺序）；skip_head 防重复收录
    延续字头（站点 page_chars 通常不标延续，此为保险）。"""
    chars = store.get_page_chars(page)
    if not chars and not continuation:
        raise RuntimeError(
            f"页 {page} 无字头索引（page_chars 为空）且无前页续文——"
            "阅读页数据不完整或该页既无新字头也无延续内容"
        )

    parts = [
        f"// 草稿：kangxizidian.com 爬取生成 {date.today()}，未经人工校对（状态：草稿）",
        "",  # 注释与 @页码 之间必须空行，否则并入同一大行致页声明不解析
        f"@{page}",
    ]
    counts = {"chars": 0, "unencoded": 0, "with_text": 0}
    if continuation:
        # 续文（前页字头的余段）：每段一个大行
        for para in continuation:
            parts.append("")
            parts.append(para)
        counts["with_text"] += 1  # 续文计入有释文字头
    for item in chars:
        if skip_head and item["char"] == skip_head:
            counts["skipped_dup"] = counts.get("skipped_dup", 0) + 1
            continue
        parts.append("")
        if item["char"]:
            parts.append(f"#{item['char']}")
            counts["chars"] += 1
            entry = store.get_entry(item["codepoint"])
            if entry:
                record = json.loads(entry["record_json"])
                paragraphs = [p for p in record.get("text_paragraphs") or [] if p.strip()]
                if paragraphs:
                    counts["with_text"] += 1
                    # 每段释义一个空行分隔的大行；段落分隔符等 PUA 已由爬取器剥离
                    parts.append("")
                    parts.extend(paragraphs)
        else:
            k = item.get("k_code") or item.get("svg", "?")
            parts.append(f"#□")
            parts.append("")
            parts.append(f"// 未编码字（{k}）：站点无 Unicode 映射，请对照原图补录")
            counts["unencoded"] += 1
    return "\n".join(parts) + "\n", counts


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def write_index(manifest: dict) -> None:
    pages = [
        {
            "page": p["page"],
            "image": p["image"],
            "gj": p.get("annotations", {}).get("gj", f"{p['page']:04d}.gj"),
            "width": p.get("width"),
            "height": p.get("height"),
            "status": p.get("status", "first"),
        }
        for p in manifest.get("pages", [])
    ]
    INDEX_JSON.parent.mkdir(parents=True, exist_ok=True)
    INDEX_JSON.write_text(
        json.dumps(
            {"source": "kangxi-gold", "images_dir": manifest["images_dir"], "pages": pages},
            ensure_ascii=False, indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def cmd_add(page: int) -> dict:
    manifest = load_manifest()
    existing = {p["page"] for p in manifest.get("pages", [])}
    if page in existing:
        raise RuntimeError(f"页 {page} 已在数据集中")
    if not 1 <= page <= 7738:
        raise RuntimeError(f"页码 {page} 超出站点范围 1-7738")

    store = kangxi_store.KangxiStore()
    summaries = []
    if store.page_missing(page, ("reading", "scan")):
        summaries.append(run_fetch("fetch_kangxi_page.py", page, "页数据"))
    else:
        summaries.append("页数据：库中已有，未联网")
    chars = store.get_page_chars(page)
    missing_entries = [
        c["char"] for c in chars
        if c["char"] and store.get_entry(c["codepoint"]) is None
    ]
    if chars and missing_entries:
        summaries.append(run_fetch("fetch_kangxi_entry.py", page, "字头详情"))
    elif chars:
        summaries.append(f"字头详情：库中已有 {len(chars) - len(missing_entries)}/{len(chars)}，未联网")

    row = store.get_page(page)
    if not row or not row.get("scan_sha256") or not row.get("scan_file"):
        raise RuntimeError(f"页 {page} 原图数据仍缺失")
    scan_file = Path(row["scan_file"])
    images_dir = Path(manifest["images_dir"])
    if scan_file.parent != images_dir:
        # 爬取时用了别的 --out：把图复制到数据集图片目录
        images_dir.mkdir(parents=True, exist_ok=True)
        target = images_dir / f"{page:04d}.jpg"
        target.write_bytes(scan_file.read_bytes())
        scan_file = target

    # 前页未完字头续入（只读前页 .gj，不回写；站点 page_chars 不标延续字头）
    continuation, cont_info = continuation_from_prev(page, store)
    if cont_info.get("skipped"):
        summaries.append(f"前页续入跳过：{cont_info['skipped']}")
    else:
        summaries.append(
            f"前页续入：@{cont_info['prev_page']} 字头「{cont_info['head']}」余 {cont_info['paragraphs']} 段"
        )

    if continuation:
        continuation, trim_note = ocr_trim_continuation(page, continuation, store)
        summaries.append(trim_note)
    draft, counts = build_draft_gj(
        page, store, continuation=continuation or None, skip_head=cont_info.get("head")
    )
    stem = f"{page:04d}"
    gj_path = ANNOTATIONS / f"{stem}.gj"
    gj_path.write_text(draft, encoding="utf-8")

    manifest["pages"] = sorted(
        manifest["pages"]
        + [{
            "page": page,
            "image": f"{stem}.jpg",
            "url": row.get("scan_url") or f"https://p.kangxizidian.com/kangxi2/{stem}.jpg",
            "size_bytes": row["scan_bytes"],
            "sha256": row["scan_sha256"],
            "width": row["scan_width"],
            "height": row["scan_height"],
            "downloaded_at": str(date.today()),
            "status": "draft",
            "annotations": {"gj": f"{stem}.gj", "json": f"{stem}.json", "txt": f"{stem}.txt"},
            "origin": "kangxizidian.com 爬取草稿（kangxi_page_tool.py add）",
        }],
        key=lambda p: p["page"],
    )
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_index(manifest)

    return {
        "ok": True,
        "page": page,
        "summaries": summaries,
        "counts": counts,
        "gj": str(gj_path.relative_to(REPO)),
        "status": "draft",
        "label": STATUS_LABELS["draft"],
    }


def cmd_status(page: int, to: str) -> dict:
    if to not in STATUS_LABELS:
        raise RuntimeError(f"未知状态 {to}（可选：{', '.join(STATUS_LABELS)}）")
    manifest = load_manifest()
    for p in manifest.get("pages", []):
        if p["page"] == page:
            p["status"] = to
            break
    else:
        raise RuntimeError(f"页 {page} 不在数据集中")
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_index(manifest)
    return {"ok": True, "page": page, "status": to, "label": STATUS_LABELS[to]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--page", type=int, required=True)
    s = sub.add_parser("status")
    s.add_argument("--page", type=int, required=True)
    s.add_argument("--to", required=True)
    args = ap.parse_args()

    try:
        result = cmd_add(args.page) if args.cmd == "add" else cmd_status(args.page, args.to)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001 —— 桥接给 HTTP 层
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
