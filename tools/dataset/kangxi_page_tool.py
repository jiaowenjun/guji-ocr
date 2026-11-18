#!/usr/bin/env python3
"""数据集对照页「添加新页」的桥接工具：补爬数据 → 生成 .gj 草稿 → 更新金标清单。

数据优先级（不重复爬虫）：kangxi-crawl.sqlite3 已有的页数据/字头详情直接用；
缺什么由 scripts/fetch_kangxi_page.py / fetch_kangxi_entry.py 增量补抓
（两者自身即「库里有则零网络请求」，页码页 2 个请求、字头详情每字 1 个请求）。

动作：
  add --page N          补数据 → 生成 kangxi-gold/annotations/NNNN.gj 草稿
                        （字头行 + 释义段落带；未编码字形按全库实测语义归并：
                        K 码＝前字头古文变体——guwen 数量精确匹配时并入字头行
                        「#头 / 古文 / #AB」，不匹配时 #□ 占位紧跟主字头；2 段名伴随
                        字形只留注释；OCR 标尺把溢出到下页的尾段裁掉，下页添加
                        时自动续入）→ 回补本页未编码字形 svg 缓存 →
                        manifest.json 追加该页（status=draft）
                        → 后台预取 N+1（独立进程 prefetch-run，不阻塞 add 退出）
  status --page N --to draft|first|final
                        改页标签（草稿/初校/精校），只写 manifest
  dataset-index         只读当前 manifest 和 dataset-config.json
  crawl-glyphs --codepoints N ...
                        按码位解析当前人工身份映射及本地 SVG
  crawl-heads --page N   只读查询本页爬取字头；heads=null 表示阅读页尚未采集
  crawl-entry --codepoint N
                        只读查询单个码位的词条详情；entry=null 表示未收录
  ocr-pages             各页 OCR/预取浅状态清单（预取调试视图数据源）：
                        数据集页 ∪ 已爬页 ∪ OCR 缓存页，每页含采集完整度、
                        OCR 缓存状态（valid/stale/invalid/none）与元数据
  prefetch-status --page N
                        单页预取四步深查（只读现状，不抓取）：爬取/字头详情/
                        OCR/svg 存在性
  prefetch-run --page N
                        手动执行单页预取链路（同 add 后台预取的四步，同步等待；
                        未爬页会联网爬取）——独立验证 prefetch_next_page 行为
  prefetch-log --tail 50
                        var/ocr-cache/prefetch.log 尾部行（时间线展示）
  replay-pages          流程演示样例集：所有初校（first）页 + 金标带/行数
  pipeline-replay --page N
                        单页全管线只读重放（零写盘）：数据现状→前页续入→
                        草稿四态演化（完整续文组装/整页尾裁/折行/重组）→
                        金标对照（字符流/行界带界 F1/漏多折/首分歧）
  ocr-skeleton-replay --page N
                        新版流程实验（只读演示）：整页 OCR 底稿→分列分段→
                        库文蓝本对齐替换→按列切段终稿→金标对照——
                        OCR 骨架范式的各步骤与实证弱点展示

按页码访问（供 import 的消费者 API，不走子命令）：
  page_image(page)       → PageImage(path, sha256) | None（扫描图，两级定位同 _scan_for）
  page_image_bytes(page) → bytes | None
  page_heads(page)       → list[dict]（char/codepoint/k_code/svg…，页面顺序，含未编码字形）
  entry_detail(head)     → dict | None（字头详情：pinyin/guwen/text_paragraphs…，收单字或码位）
  page_ocr(page, model)  → str | None（执行识别：优先缓存，未命中提交服务并写缓存）
  page_columns(page)     → dict（列分割坐标：majors[8]/minors[16] 像素范围；失败含 error 键）
  page_column_ocr(page)  → list[8] | None（执行列级识别：持久保存部分成功，下次补失败列）
用法：python3 kangxi_page_tool.py add --page 329
      sys.path.insert(0, "tools/dataset"); from kangxi_page_tool import page_image, page_heads
仅依赖标准库。
"""
from __future__ import annotations

import argparse
import difflib
import io
import json
import os
import tempfile
import time
import uuid
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "crawl"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kangxi_store  # noqa: E402
import paths  # noqa: E402
from kangxi_entry_parser import resolve_entry  # noqa: E402
from kangxi_semantics import find_host_marks, strip_guwen_prefix, section_heading  # noqa: E402

HERE = Path(__file__).resolve().parent          # tools/dataset
CRAWL = HERE.parent / "crawl"
EVAL = HERE.parent / "eval"
REPO = HERE.parents[1]
MANIFEST = REPO / "kangxi-gold" / "manifest.json"
ANNOTATIONS = REPO / "kangxi-gold" / "annotations"

STATUS_LABELS = {"draft": "草稿", "first": "初校", "final": "精校"}

# —— add 计时打点（[timing] 前缀，stderr + prefetch.log 双写；仅 add 链路调用）——
_ADD_T0 = time.monotonic()


def _log_ts(marker: str) -> None:
    msg = f"[timing] {marker} (+{time.monotonic() - _ADD_T0:.1f}s since add-start)"
    print(f"{time.strftime('%H:%M:%S')} {msg}", file=sys.stderr, flush=True)
    try:
        import logging

        logging.basicConfig(
            filename=paths.OCR_CACHE_DIR / "prefetch.log", filemode="a",
            level=logging.INFO, format="%(asctime)s %(message)s",
        )
        logging.info(msg)
    except Exception:  # noqa: BLE001 —— 日志失败不影响主流程
        pass


def _fetch_summary(last: str, label: str) -> str:
    """fetch 脚本末行输出 → 一句带 label 的人话摘要（纯函数）。

    末行是全库 stats JSON（两个 fetch 脚本打印同一份），原样入 summaries 会让
    前端状态栏出现两段重复长 JSON。"""
    try:
        stats = json.loads(last)
    except ValueError:
        stats = None
    if isinstance(stats, dict) and "pages_total" in stats:
        return f"{label}：联网补抓完成（库内 {stats['pages_total']} 页 / {stats['entries_total']} 条字头）"
    return f"{label}：{last[:80]}" if last else f"{label}：完成"


def run_fetch(script: str, page: int, label: str) -> str:
    """复用既有爬取 CLI 增量补数据（库里有则零网络）；摘要转换在 _fetch_summary。"""
    r = subprocess.run(
        [sys.executable, str(CRAWL / script), "--pages", str(page)],
        capture_output=True, text=True, timeout=600,
    )
    if r.returncode != 0:
        raise RuntimeError(f"{script} 退出码 {r.returncode}\n{r.stdout}\n{r.stderr}")
    last = (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else ""
    return _fetch_summary(last, label)


PUNCT_STRIP = "。，·\"：:、；《》【】*　 \t\n\r"


def _norm(text: str) -> str:
    """清洗为匹配口径：去标点/空白/书名括号（与 .gj 词法的剔除集一致）。"""
    return "".join(ch for ch in text if ch not in PUNCT_STRIP)


def locate_tail(entry_n: str, tail_n: str, *, opening_n: str | None = None) -> tuple[int | None, str]:
    """续入锚定：尾部前缀锚定 + 容差对齐。返回 (库文坐标末界, "") 或
    (None, 原因)，原因为 anchor / coverage 覆盖/总长 / fully / short_*。
    前页可能有个别校订增删（如站点文本少一字），整串子串匹配会整体失败，
    故先按 24→8 字递减锚定再 SequenceMatcher 容差（覆盖率 ≥0.9）。
    不足 8 字（含仅排下字头）只接受词条的精确前缀，并要求本页 OCR 开头
    证实余文；不能在全文中搜索短串（@370「廣韻」在些条出现两次）。
    短前缀拒绝原因以 short_ 开头，供调用方提示待核而非误报校订不匹配。"""
    if len(tail_n) < 8:
        if not entry_n.startswith(tail_n):
            return None, "short_prefix"
        end = len(tail_n)
        if end >= len(entry_n):
            return None, "fully"
        if not opening_n:
            return None, "short_ocr_missing"
        # 只比较紧接页界的前 24 字；页中命中不能证明页首存在续文。
        # 至少 8 字连续匹配、总覆盖率 90%，且匹配须从两串开头开始。
        prefix = entry_n[end:end + 24]
        observed = opening_n[:len(prefix)]
        blocks = [b for b in difflib.SequenceMatcher(None, prefix, observed, autojunk=False)
                  .get_matching_blocks() if b.size]
        if (not blocks or blocks[0].a != 0 or blocks[0].b != 0
                or max(b.size for b in blocks) < 8
                or sum(b.size for b in blocks) < len(prefix) * 0.9):
            return None, "short_ocr_mismatch"
        return end, ""

    anchor = -1
    for k in range(min(len(tail_n), 24), 7, -1):
        anchor = entry_n.find(tail_n[:k])
        if anchor >= 0:
            break
    if anchor < 0:
        return None, "anchor"
    sm = difflib.SequenceMatcher(None, entry_n, tail_n, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
    covered = sum(b.size for b in blocks)
    if covered / len(tail_n) < 0.9:
        return None, f"coverage {covered}/{len(tail_n)}"
    end = max(b.a + b.size for b in blocks)
    if end >= len(entry_n):
        return None, "fully"
    return end, ""


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
    raw_prev = page_gj(page - 1)
    if raw_prev is None:
        info["skipped"] = f"前页 {page - 1} 不在数据集"
        return [], info

    def host_in(raw_text: str, source_page: int):
        """在单页文本中找最后一个有库内详情的主字头；返回 (head, detail, tail_raw)。
        标记解析走 find_host_marks（纯），库内详情查询在此（I/O）。"""
        for cand, end in reversed(find_host_marks(raw_text)):
            e = entry_detail(ord(cand), store, page=source_page) if len(cand) == 1 else None
            if e is not None:
                return cand, e, raw_text[end:]
        return None, None, ""

    raw = raw_prev
    head, detail, tail_raw = host_in(raw, page - 1)
    info["host_page"] = page - 1
    if detail is None:
        # 前页是纯延续页：逐页向前找宿主页，边回溯边累计纯延续页全文（正序），
        # 尾部 = 宿主页字头后文本 + 其后各页（含前页）全文拼接——支持任意长延续链
        chained: list[str] = [raw]  # 回溯途经的纯延续页（倒序收集，最后正序拼接）
        back = page - 2
        while back >= 1:
            cand_gj = ANNOTATIONS / f"{back:04d}.gj"
            if not cand_gj.exists():
                break  # 数据集不连续，回溯终止
            cand_raw = cand_gj.read_text(encoding="utf-8")
            h, e, t = host_in(cand_raw, back)
            if e is not None:
                head, detail = h, e
                tail_raw = t + "\n" + "\n".join(reversed(chained))
                info["host_page"] = back
                break
            chained.append(cand_raw)
            back -= 1
        if detail is None:
            info["skipped"] = "前页及回溯各页的字头在库中均无详情"
            return [], info
    if detail is None:
        info["skipped"] = "前页字头在库中均无详情"
        return [], info
    info["head"] = head
    if detail.get("selection_note"):
        info["source_note"] = detail["selection_note"]
    tail_raw = strip_guwen_prefix(tail_raw)
    # 剥离注释行与页码/分隔行（伴随字形/归并来源等工具注释、回溯拼接各页
    # 带来的 @页码 行不是页面文本，混进尾部会让锚点在库内段落中找不到起点
    # ——@340 读 @339 丹条尾巴实测踩坑；@329 空白页整页只剩 @页码 行，
    # 不剥离则 locate_tail 覆盖率被 4 个杂字拖垮，其后各页跨空白页续入即断）
    tail_raw = "\n".join(
        l for l in tail_raw.splitlines()
        if l.strip() and not l.strip().startswith("//")
        and not re.fullmatch(r"@\d+|=+", l.strip())
    )
    paragraphs = [p for p in (detail.get("text_paragraphs") or []) if p.strip()]
    if not paragraphs:
        info["skipped"] = f"字头「{head}」无释义段"
        return [], info

    tail_n = _norm(tail_raw)
    # 全量释义拼接（含归一化坐标 → (段序, 段内原文下标) 映射）
    norm_chars: list[str] = []
    idx_map: list[tuple[int, int]] = []
    for pi, para in enumerate(paragraphs):
        for ci, ch in enumerate(para):
            if ch not in PUNCT_STRIP:
                norm_chars.append(ch)
                idx_map.append((pi, ci))
    entry_n = "".join(norm_chars)

    # 定位：先锚定（尾部前缀在库文中找起点），再容差对齐到尾串末尾（locate_tail）
    opening_n = None
    if len(tail_n) < 8:
        md = _ocr_cache_read(page, store)  # 只读有效缓存；查询/重放不提交识别任务
        if md:
            opening_n = _norm("".join(_ocr_groups(md)))
    end, why = locate_tail(entry_n, tail_n, opening_n=opening_n)
    if end is None:
        if why.startswith("short_"):
            reason = {
                "short_prefix": "与词条开头不一致",
                "short_ocr_missing": "本页无有效 OCR，无法确认续文起点",
                "short_ocr_mismatch": "本页 OCR 开头不足以确认紧接的续文",
            }[why]
            info["skipped"] = f"跨页续文待核：前页「{head}」正文仅 {len(tail_n)} 字，{reason}，未自动续入"
        elif why == "anchor":
            info["skipped"] = "前页尾部与库内段落不匹配（可能已大幅校订），未自动续入"
        elif why.startswith("coverage"):
            info["skipped"] = f"前页尾部与库内段落对齐覆盖率 {why.partition(' ')[2]} 过低，未自动续入"
        else:  # fully：前页已收全，余段为空
            info["skipped"] = (
                f"前页 {page - 1} 的 .gj 已完整收录字头「{head}」全部 {len(paragraphs)} 段"
                "，无剩余正文可续入；若本页原图仍有该条续文，请核对前页的物理页界"
            )
            info["fully_included"] = True
        return [], info
    pi0, ci0 = idx_map[end]
    if end == 0 or idx_map[end - 1][0] != pi0:
        ci0 = 0  # 余文从新段开始（含前页仅字头），保留开书名号等前导标点
        if tail_raw.rstrip().endswith(("【", "《")) and paragraphs[pi0].startswith(("【", "《")):
            ci0 = 1  # 开框已排在前页，续页不能再补一次
    out: list[str] = []
    rest = paragraphs[pi0][ci0:].strip()
    if rest:
        out.append(rest)
    out.extend(paragraphs[pi0 + 1:])
    info["paragraphs"] = len(out)
    return out, info


def page_gj(page: int) -> str | None:
    """给定页码 → 该页 .gj 原文（金标标注，人工校订后的真值）；未入库返回 None。

    数据集页的语义真值以本文件为准（page_heads 是站点爬取的原始索引）。"""
    gj = ANNOTATIONS / f"{page:04d}.gj"
    return gj.read_text(encoding="utf-8") if gj.exists() else None


def parse_gj_bands(raw: str) -> tuple[list[str], list[list[str]]]:
    """ .gj 原文 → (头部行（注释 + @页码 行）, 大列带列表)（纯函数）。

    空行分隔 = 大列带（regroup 后的语义）；带内连续非空行 = 折叠小行。
    cmd_ocr_fold 与基准/评估脚本共用的解析口径。"""
    lines = raw.splitlines()
    head: list[str] = []
    body_start = 0
    for i, l in enumerate(lines):
        head.append(l)
        if l.strip().startswith("@"):
            body_start = i + 1
            break
    bands: list[list[str]] = []
    cur: list[str] = []
    for l in lines[body_start:]:
        if l.strip():
            cur.append(l)
        elif cur:
            bands.append(cur)
            cur = []
    if cur:
        bands.append(cur)
    return head, bands


def page_prefetch_state(page: int, store: kangxi_store.KangxiStore | None = None, *, include_markdown: bool = False) -> dict:
    """给定页码 → 预取四步现状（只读，不抓取）：fetch/entries/ocr/svg。

    与 _prefetch_pipeline 四步一一对应，调试视图与 prefetch-status 子命令
    共用。svg 口径 = codepoint 为空的未编码字形（与回补 scope 同口径）。"""
    s = store or kangxi_store.KangxiStore(readonly=True)
    missing = s.page_missing(page, ("reading", "scan"))
    chars = page_heads(page, s)
    miss_entries = s.coded_chars_missing_entries(page)
    snapshot = ocr_cache_snapshot(page, _page_sha(page, s))
    ocr = {k: v for k, v in snapshot.items() if k != "markdown"}
    wanted = [c["svg"] for c in chars if c["codepoint"] is None and c.get("svg")]
    have = sum(1 for rel in wanted if (paths.RAW_KANGXI_SVG / rel).is_file())
    ocr_detail = {
        "valid": f"缓存有效（{ocr['chars']} 字，{ocr['fetched_at']}）",
        "stale": f"缓存失效（图已变或无图可比对，{ocr['chars']} 字）",
        "none": "无 OCR 缓存（需预取）",
        "invalid": ocr["reason"],
    }[ocr["state"]]
    return {
        "page": page,
        "steps": {
            "fetch": {"ok": not missing,
                      "detail": "阅读页+原图齐全" if not missing else f"缺 {sorted(missing)}"},
            "entries": {"ok": not miss_entries,
                        "detail": (f"字头 {len(chars)}，缺详情 {len(miss_entries)}"
                                   + (f"（{''.join(miss_entries[:8])}…）" if miss_entries else ""))},
            "ocr": {"ok": ocr["state"] == "valid", "detail": ocr_detail},
            "svg": {"ok": have == len(wanted),
                    "detail": (f"未编码字形 svg {have}/{len(wanted)}" if wanted
                               else "本页无未编码字形")},
        },
        "ocr": ocr,
        **({"markdown": snapshot["markdown"], "hint": snapshot["reason"] + "；请执行预取"}
           if include_markdown else {}),
    }


_MIN_OCR_CHARS = 20  # 整页 OCR 归一化下限：低于此视为服务残缺结果，不落缓存


def _scan_for(page: int, store: kangxi_store.KangxiStore) -> tuple[Path | None, str]:
    """定位页扫描图：crawl store 的 scan_file 优先；未登记（直接下载入库的
    312–328 等页）回退 kangxi-gold manifest 的 images_dir + sha256。"""
    row = store.get_page(page) or {}
    if row.get("scan_file") and Path(row["scan_file"]).is_file():
        return Path(row["scan_file"]), row.get("scan_sha256") or ""
    m = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {"pages": []}
    for e in m.get("pages", []):
        if e["page"] == page:
            img = Path(m["images_dir"]) / e["image"]
            if img.is_file():
                return img, e.get("sha256") or ""
    return None, ""


def _page_sha(page: int, store: kangxi_store.KangxiStore) -> str:
    """当前图 sha 的两级登记值查找（store 优先，回退 manifest），不查文件存在。

    与 _scan_for 的分工：_scan_for 找「实际可用文件」（img 与 sha 同源返回，
    文件不在则跳过该级），本函数只取登记指纹——图文件被移动/未挂载时缓存
    校验（_ocr_cache_meta 判 stale）仍能拿到归属值。"""
    sha = (store.get_page(page) or {}).get("scan_sha256") or ""
    if sha:
        return sha
    for e in load_manifest().get("pages", []):
        if e["page"] == page:
            return e.get("sha256") or ""
    return ""


# ---- 按页码只读查询 API（供消费者 import；定位/数据口径与 add/OCR 链路一致）----
# store 可选注入共享实例（add 链路逐函数传同一 store）；缺省现开——
# 缺省只读连接，不初始化数据库；循环调用可注入共享 store。


class PageImage(NamedTuple):
    path: Path
    sha256: str


def page_image(page: int, store: kangxi_store.KangxiStore | None = None) -> PageImage | None:
    """给定页码 → 该页扫描图 (path, sha256)；未收录（未爬且不在数据集清单）返回 None。

    定位两级回退同 _scan_for：crawl store 的 scan_file 优先，未登记页
    （如直接下载入库的 312–328）回退 manifest 的 images_dir；sha256 供缓存键。
    """
    img, sha = _scan_for(page, store or kangxi_store.KangxiStore(readonly=True))
    return PageImage(img, sha) if img else None


def page_image_bytes(page: int, store: kangxi_store.KangxiStore | None = None) -> bytes | None:
    """给定页码 → 扫描图字节（直接送 OCR / 预览用）；未收录返回 None。"""
    found = page_image(page, store)
    return found.path.read_bytes() if found else None


def page_heads(page: int, store: kangxi_store.KangxiStore | None = None) -> list[dict]:
    """给定页码 → 该页字头记录（页面顺序；含未编码字形）。

    字段同 page_chars 表：char（未编码字形为 None）、codepoint、k_code、
    svg、page_seq…。快速展示：[c["char"] or "□" for c in page_heads(n)]。
    纯延续页（如 @332）站点不标字头，返回 []；金标页的人工校订以 .gj 为准。
    """
    return (store or kangxi_store.KangxiStore(readonly=True)).get_page_chars(page)


def entry_detail(head: str | int, store: kangxi_store.KangxiStore | None = None,
                 *, page: int | None = None, svg: str | None = None) -> dict | None:
    """字头＋可选来源页位／缩略图 → 卡片详情；未收录返回 None。

    旧缓存从保存的 HTML 按需重解析，查询零网络、零写盘。续文使用宿主页位，
    不使用当前续页。缺 HTML 或卡片归属不明时保留旧文，后者附 selection_note。

    head 收单字（'丹'）或十进制码位（ord，如 20025）；未编码字形无码位不可查。
    记录字段：sword/pinyin/zhuyin/radical/total_strokes/guwen（古文变体，
    「、」分隔）/text_paragraphs（释义段，有序）/juan/unihan/cangjie 等。
    raw_html 不含（体积），需要原始页走 KangxiStore.get_entry。
    """
    s = store or kangxi_store.KangxiStore(readonly=True)
    row = s.get_entry(head) if isinstance(head, int) else s.get_entry_by_char(head)
    if row is None:
        return None
    return resolve_entry(row, head=chr(head) if isinstance(head, int) else head, page=page, svg=svg)


def _page_entry_details(chars: list[dict], page: int, store) -> dict:
    """页内按缩略图取卡片；同码位重复出现时不覆盖不同来源。"""
    return {item.get("svg") or item["codepoint"]:
            entry_detail(item["codepoint"], store, page=page, svg=item.get("svg"))
            for item in chars if item["char"]}


def page_ocr(page: int, model: str = "paddle",
             store: kangxi_store.KangxiStore | None = None, *, force: bool = False) -> str | None:
    """给定页码 → 该页扫描图的 OCR 文本（markdown）；不可得返回 None。

    model 预留换 OCR 引擎，当前仅 "paddle"（本地 paddleocr-baseline 服务，
    http://127.0.0.1:8010），其他值抛 NotImplementedError。
    读取顺序与 add/折行链路一致（_ocr_markdown）：持久缓存
    （sha256 校验，prefetch_ocr.py 预填）→ 服务在线时提交新 job 现算并
    回写缓存；无图 / 服务未运行 / 超时 → None。
    持久缓存同时校验图片指纹、模型和正文完整性。
    """
    if model != "paddle":
        raise NotImplementedError(f"OCR 模型 {model} 暂不可用（当前仅 paddle）")
    return _ocr_markdown(page, store or kangxi_store.KangxiStore(readonly=True), force=force)


def _column_seg():
    """惰性导入列分割模块（EVAL 目录注入 sys.path，幂等）——page_columns
    与 ocr_regroup_bands 共用的唯一入口，避免两处各写一份路径注入。"""
    if str(EVAL) not in sys.path:
        sys.path.insert(0, str(EVAL))
    import kangxi_column_seg  # noqa: E402

    return kangxi_column_seg


def page_columns(page: int, store: kangxi_store.KangxiStore | None = None) -> dict:
    """给定页码 → 列分割坐标（像素绝对坐标，右→左阅读序）。

    直接透传 kangxi_column_seg.segment（单页默认参数，与该脚本 CLI 单页
    调用同口径；多页 pitch 池化是 CLI 批处理行为，不属单页语义）。差异仅
    一处：图定位走 page_image 两级回退（store scan_file → manifest
    images_dir）后显式传 img_path，而非 segment 内部硬拼 IMGDIR——爬取时
    用过别的 --out 的页也能定位；无图返回 {"page", "error"}（不抛
    FileNotFoundError）。返回结构：block [x0,y0,x1,y1] / pitch（列距）/
    majors[8]（大列，每项 kind=pair|wide、x1/x2、minors[2] 小列：
    x1/x2/cx + y1/y2 墨迹范围 + cap/chars_est + bound detected|grid）。
    分割失败时含 "error" 键——判断口径同 ocr_regroup_bands。numpy/Pillow
    惰性导入，即时计算不缓存（单页亚秒级）。
    """
    img = page_image(page, store)
    if img is None:
        return {"page": page, "error": "扫描图不存在（store 与 manifest 均未定位到）"}
    return _column_seg().segment(page, img_path=str(img.path))


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as f:
        tmp = Path(f.name)
        try:
            f.write(json.dumps(value, ensure_ascii=False) + "\n")
            f.close()
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


def _read_cache(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _column_cache_read(page: int, sha: str, model: str = "paddle") -> list[dict] | None:
    entry = _read_cache(paths.OCR_CACHE_DIR / "columns" / f"{page:04d}.json")
    if not entry or not sha or entry.get("sha256") != sha or entry.get("model") != model:
        return None
    cols = entry.get("columns")
    if (not isinstance(cols, list) or len(cols) != 8
            or any(not isinstance(c, dict) or c.get("index") != i + 1
                   or not isinstance(c.get("x1"), (int, float))
                   or not isinstance(c.get("x2"), (int, float))
                   or "markdown" not in c
                   or (c["markdown"] is not None and not isinstance(c["markdown"], str))
                   for i, c in enumerate(cols))):
        return None
    return cols


def column_ocr_complete(columns: list[dict] | None) -> bool:
    # 空串是成功但无文字；None 是提交失败，必须重试。
    return bool(columns and len(columns) == 8
                and all(isinstance(c.get("markdown"), str) for c in columns))


def column_cache_valid(page: int, store: kangxi_store.KangxiStore | None = None) -> bool:
    store = store or kangxi_store.KangxiStore(readonly=True)
    return column_ocr_complete(_column_cache_read(page, _page_sha(page, store)))


def page_column_ocr(page: int, model: str = "paddle",
                    store: kangxi_store.KangxiStore | None = None) -> list[dict] | None:
    """按列识别；持久保存部分成功结果，后续只补失败列。没有进程级负缓存。"""
    if model != "paddle":
        raise NotImplementedError(f"OCR 模型 {model} 暂不可用（当前仅 paddle）")
    store = store or kangxi_store.KangxiStore(readonly=True)
    cached = _column_cache_read(page, _page_sha(page, store), model)
    if column_ocr_complete(cached):
        return cached
    img_found = page_image(page, store)
    if img_found is None or not ocr_service_up():
        return cached
    if img_found.sha256 != _page_sha(page, store):
        cached = None
    seg = page_columns(page, store)
    if "error" in seg or len(seg.get("majors", [])) != 8:
        return None
    from PIL import Image

    out: list[dict] = []
    with Image.open(img_found.path) as g:
        _, by0, _, by1 = seg["block"]
        for j, maj in enumerate(seg["majors"]):
            box = [max(0, maj["x1"] - 4), by0, min(g.width, maj["x2"] + 4), by1]
            old = cached[j] if cached else None
            if old and old.get("box") == box and isinstance(old["markdown"], str):
                out.append(old)
                continue
            buf = io.BytesIO()
            g.crop(box).save(buf, format="JPEG", quality=92)
            md = ocr_submit_markdown(buf.getvalue(), f"{page:04d}-c{j + 1}.jpg")
            out.append({"index": j + 1, "x1": maj["x1"], "x2": maj["x2"],
                        "box": box, "markdown": md})
    if all(c["markdown"] is None for c in out):
        return None
    _atomic_json(paths.OCR_CACHE_DIR / "columns" / f"{page:04d}.json",
                 {"page": page, "sha256": img_found.sha256, "model": model,
                  "columns": out, "fetched_at": date.today().isoformat()})
    return out


def ocr_text_valid(markdown: str) -> bool:
    return len(_norm("".join(_ocr_groups(markdown)))) >= _MIN_OCR_CHARS


def ocr_cache_snapshot(page: int, cur_sha: str) -> dict:
    """所有读侧、状态页、预取共用的有效性判定；旧缓存缺 model 按 paddle 解释。"""
    f = paths.OCR_CACHE_DIR / f"{page:04d}.json"
    entry = _read_cache(f)
    state = "none"
    reason = "尚无 OCR 缓存"
    md = entry.get("markdown") if entry else None
    if f.exists() and entry is None:
        state, reason = "invalid", "OCR 缓存损坏"
    elif entry is not None:
        if not cur_sha or entry.get("sha256") != cur_sha or entry.get("model", "paddle") != "paddle":
            state, reason = "stale", "图片或模型已变化"
        elif not isinstance(md, str) or not ocr_text_valid(md):
            state, reason = "invalid", "OCR 正文不足或结果残缺，需重新预取"
        else:
            state, reason = "valid", "缓存有效"
    return {"state": state, "reason": reason,
            "fetched_at": entry.get("fetched_at") if entry else None,
            "chars": len(md) if isinstance(md, str) else 0,
            "markdown": md if state == "valid" else None}


def _ocr_cache_meta(page: int, cur_sha: str) -> dict:
    return {k: v for k, v in ocr_cache_snapshot(page, cur_sha).items() if k != "markdown"}


def _ocr_cache_read(page: int, store: kangxi_store.KangxiStore) -> str | None:
    return ocr_cache_snapshot(page, _page_sha(page, store))["markdown"]


def ocr_cache_valid(page: int, store: kangxi_store.KangxiStore | None = None) -> bool:
    store = store or kangxi_store.KangxiStore(readonly=True)
    return ocr_cache_snapshot(page, _page_sha(page, store))["state"] == "valid"


def ocr_cache_write(page: int, store: kangxi_store.KangxiStore, markdown: str, *, sha: str | None = None) -> bool:
    sha = sha or _page_sha(page, store)
    if not sha or not ocr_text_valid(markdown):
        return False
    _atomic_json(paths.OCR_CACHE_DIR / f"{page:04d}.json",
                 {"page": page, "sha256": sha, "model": "paddle", "markdown": markdown,
                  "fetched_at": date.today().isoformat()})
    return True


def ocr_service_up() -> bool:
    """本地 paddleocr-baseline 服务是否在线。"""
    import urllib.request

    try:
        with urllib.request.urlopen("http://127.0.0.1:8010/health", timeout=3) as r:
            return json.loads(r.read()).get("service") == "ocr"
    except Exception:
        return False


def ocr_submit_markdown(payload: bytes, filename: str) -> str | None:
    """提交图片字节到本地 OCR 服务（job → 轮询 → 提取 markdown）。

    _ocr_markdown（整页）与 page_column_ocr（大列条带）共用的服务调用段：
    服务未运行 / 提交失败 / 轮询超时 → None；成功终态但无文本 → ""（列条带
    可能整列漏识——确定性结果，与失败区分，调用方按需回退）。
    """
    import urllib.request

    base = "http://127.0.0.1:8010"
    if not ocr_service_up():
        return None
    boundary = uuid.uuid4().hex
    file_field = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{base}/ocr/images",
        data=file_field,
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    view: dict = {}
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            submit = json.loads(r.read())
        image_id = submit.get("image_id")
        if not image_id:
            return None
        deadline = time.time() + 600
        while time.time() < deadline:
            time.sleep(3)
            with urllib.request.urlopen(f"{base}/ocr/images/{image_id}", timeout=30) as r:
                view = json.loads(r.read())
            # weimo 视图：result 非 null 即终态成功；error 非 null 即失败
            if view.get("result") is not None:
                break
            if view.get("error") is not None:
                return None
        else:
            return None
    except Exception:
        return None

    result_view = view.get("result") or {}
    md_text = result_view.get("markdown") or ""
    if not md_text:
        md_text = (
            ((result_view.get("json") or {}).get("result") or {}).get("layoutParsingResults")
            or [{}]
        )[0].get("markdown", {}).get("text", "")
    return md_text


def _ocr_markdown(page: int, store: kangxi_store.KangxiStore, *, force: bool = False) -> str | None:
    """执行路径：先读有效持久缓存，未命中才识别。失败不缓存，下次调用可重试。"""
    if not force:
        cached = _ocr_cache_read(page, store)
        if cached is not None:
            return cached
    img, sha = _scan_for(page, store)
    if img is None:
        return None
    md = ocr_submit_markdown(img.read_bytes(), img.name)
    if not md or not ocr_cache_write(page, store, md, sha=sha):
        return None
    return md


_SIDE_STRIP_RE = re.compile(r"康熙字典|[子丑寅卯辰巳午未申酉戌亥]集[上中下]?")


def _ocr_groups(md_text: str) -> list[str]:
    """OCR markdown 的行组列表，剥掉页缘邊題组。

    邊題（版框外侧的卷次/部首题签，如「子集上·丶部」）物理上是页面最左列，
    OCR 排在末组；其字符（子/集/上/畫…）与词条正文伪匹配会虚增对齐末界
    （@334 实测：末块 (cand 959, ocr 374)「二」来自邊題「四畫 十二」，
    页界被推迟 ~40 字致欠裁）。仅剔除末尾 ≤2 个短组且含题签特征的组，
    正文组不满足「短 + 含卷次标记」不会误伤。
    """
    groups = [g.replace("\n", "") for g in md_text.split("\n\n") if g.strip()]
    dropped = 0
    while groups and dropped < 2:
        tail_n = _norm(groups[-1])
        if len(tail_n) <= 16 and _SIDE_STRIP_RE.search(tail_n):
            groups.pop()
            dropped += 1
        else:
            break
    return groups


_TAIL_WINDOW = 30  # 末段判信窗口（归一化字数）


def _tail_stats(blocks: list, e: int, window: int = _TAIL_WINDOW) -> tuple[int, int, int]:
    """块尾 e 前一窗的 (匹配字数, 窗长, 末端连续匹配长度)。blocks 为归一化
    候选坐标上互不重叠的匹配块（difflib.get_matching_blocks 过滤 0 后天然如此）。"""
    lo = max(0, e - window)
    m = sum(min(b.a + b.size, e) - max(b.a, lo) for b in blocks if b.a < e and b.a + b.size > lo)
    run = 0
    i = e - 1
    while i >= lo and any(b.a <= i < b.a + b.size for b in blocks):
        run += 1
        i -= 1
    return m, e - lo, run


def _align_cut(cand_n: str, ocr_n: str, full_page: bool = False) -> tuple[int | None, str]:
    """归一化双串对齐求裁点（纯函数）：返回 (裁点, 回缩说明) 或 (None, 拒绝原因)。

    裁点是候选坐标里页面的最后一字位置。门槛按「裁点前区域」判信而非
    OCR 全长：页面含新字头时匹配数天然小于 OCR 全文（334：候选末段 375
    字，页面上只有前 ~79 字）。要求裁点区域至少 20 字且其中过半是真实
    匹配（连续性证据），否则放弃裁剪回退全量。
    full_page=True 用于整页草稿候选（含溢出到下页的全量词条）：此时候选天然
    大于页面，判信改按 OCR 侧——页面文本须过半被候选解释（@334 实测：候选
    961 字仅 ~270 字在页上，按候选侧判信会误拒正确裁点 924）。

    末段局部判信（2026-11-14 加）：全局 cover 门槛拦不住「末界后的伪匹配」
    ——库文尾段比书页长时（@331 个条库文多 84 字、@324 丕条多 6 字，站点
    版本差异），真匹配在物理页界处断流，其后是「切集韻韻會正韻」类韻書
    套话碎块（@331 实测 GT 后 13/52 字真匹配）或孤字（山/从不），把末界
    虚增。回缩规则：从最大块尾向左找首个「末窗密度 ≥0.5 且非孤字收尾
    （末端连续匹配 ≥2）」的块尾作裁点；全部不达标 → 不可信不裁。好页实测
    末窗密度 0.83–1.00 且以 ≥2 连续块收尾，不受影响。
    """
    sm = difflib.SequenceMatcher(None, cand_n, ocr_n, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
    if not blocks:
        # 两串非空但零公共块（@358：坏 OCR 单字「寧」与续文无交集）→
        # 判不可信拒绝，而非 max() 空序列崩溃
        return None, "对齐不可信（零匹配块）"
    cover = sum(b.size for b in blocks)
    end0 = max(b.a + b.size for b in blocks)
    # 末段局部判信回缩（见 docstring）
    end, why_tail = end0, ""
    for e in sorted({b.a + b.size for b in blocks}, reverse=True):
        m, wlen, run = _tail_stats(blocks, e)
        if wlen >= 10 and m >= wlen * 0.5 and run >= 2:
            end = e
            break
    else:
        return None, "对齐不可信（末段匹配稀疏）"
    if end < end0:
        why_tail = f"，末段判信回缩 {end0 - end} 字"
    if end < 20:
        return None, f"对齐不可信（裁点 {end} 字过短）"
    span = len(ocr_n) if full_page else end
    if cover < span * 0.5:
        return None, f"对齐不可信（页面 {span} 字中匹配 {cover}）"
    return end, why_tail


_TAIL_REVIEW_MAX = 4
_TAIL_ANCHOR_MIN = 12
_TAIL_REVIEW_MARK = "页尾待核："


def _tail_context(cand_n: str, ocr_n: str, end: int) -> tuple[str, str]:
    """原裁点对应的连续匹配块、其后 OCR 余文；不把后续孤字伪匹配当锚点。"""
    blocks = difflib.SequenceMatcher(None, cand_n, ocr_n, autojunk=False).get_matching_blocks()
    block = next((b for b in blocks if b.size and b.a + b.size == end), None)
    if block is None:
        return "", ""
    return cand_n[block.a:end], ocr_n[block.b + block.size:]


def _prefix_edit_costs(source: str, observed: str) -> list[int]:
    """局部编辑距离：消费全部 observed 时，source 各前缀的代价（含零长度）。"""
    row = list(range(len(source) + 1))
    for i, ch in enumerate(observed, 1):
        nxt = [i]
        for j, src in enumerate(source, 1):
            nxt.append(min(row[j] + 1, nxt[j - 1] + 1, row[j - 1] + (src != ch)))
        row = nxt
    return row


def _review_tail_cut(cand_n: str, ocr_n: str, end: int,
                     column_n: str | None) -> tuple[int, str]:
    """短尾局部复核（纯函数）。原文字不替换，只返回经末列确认的裁点。

    自动延伸要求：唯一的 ≥12 字连续锚点；OCR 余文 1–4 字；候选正长度
    前缀中编辑距离最小的终点唯一且至多 1 次替换；有效末列 OCR 在同一锚点
    后恰好结束于该尾文（库文或整页 OCR 写法）。插入/删除、跨字头及冲突
    均待核。零长度解释（OCR 多识）不能仅靠文本距离排除，必须有末列证据。
    同模型两次识别仍可能共同误识；这是有边界的恢复规则，不是绝对真值。
    """
    anchor, rest = _tail_context(cand_n, ocr_n, end)
    if not rest:
        return end, ""
    preview = rest[:_TAIL_REVIEW_MAX]

    def pending(reason: str) -> tuple[int, str]:
        nearby = cand_n[end:end + _TAIL_REVIEW_MAX] or "（无）"
        return end, (
            f"，{_TAIL_REVIEW_MARK}OCR 余文「{preview}」{len(rest)} 字，库文邻文「{nearby}」，"
            f"{reason}；请核对末列原图"
        )

    if len(rest) > _TAIL_REVIEW_MAX:
        return pending(f"超过 {_TAIL_REVIEW_MAX} 字局部复核范围")
    if len(anchor) < _TAIL_ANCHOR_MIN:
        return pending("连续匹配锚点不足")
    anchor = anchor[-_TAIL_WINDOW:]
    if cand_n.find(anchor) != cand_n.rfind(anchor) or ocr_n.find(anchor) != ocr_n.rfind(anchor):
        return pending("前文定位不唯一")
    # 多看一个源字以检查相邻裁点的插入/删除歧义，不允许越过新字头。
    source = cand_n[end:end + len(rest) + 1].split("#", 1)[0]
    if not source:
        return pending("库文已结束或下一字为新字头，不能推断缺字")
    costs = _prefix_edit_costs(source, rest)
    best = min(costs[1:])
    ends = [i for i in range(1, len(costs)) if costs[i] == best]
    if best > 1:
        return pending("局部差异超过 1 字")
    if len(ends) != 1:
        return pending("局部容错存在多个裁点")
    size = ends[0]
    addition = source[:size]
    if size != len(rest) or sum(a != b for a, b in zip(addition, rest)) != best:
        return pending("需要插入或删除字符，不能自动延伸")
    blocks = difflib.SequenceMatcher(None, cand_n, ocr_n, autojunk=False).get_matching_blocks()
    if any(b.size and b.a >= end + size for b in blocks):
        return pending("OCR 尾文还匹配到更后面的库文，位置存在歧义")
    if column_n is None:
        return pending("无有效末列 OCR 缓存，未自动延伸")
    if anchor not in column_n or column_n.find(anchor) != column_n.rfind(anchor):
        return pending("末列 OCR 无法唯一定位前文，未自动延伸")
    column_tail = column_n.split(anchor, 1)[1]
    if column_tail not in (rest, addition):
        return pending("末列 OCR 与整页尾文不一致，未自动延伸")
    return end + size, (
        f"，末列 OCR 复核通过：局部 {best} 字差异，保留库文尾字「{addition}」"
    )


def ocr_page_cut(
    page: int, text: str, store: kangxi_store.KangxiStore, full_page: bool = False
) -> tuple[int | None, int, str]:
    """OCR 对齐求本页物理末界：返回 (裁点, 候选归一化长度, 说明)。

    裁点是候选文本归一化坐标里页面的最后一字位置；None = 不可信/不可用，
    调用方不应裁剪。文本始终以库内转写为准，OCR 只作范围标尺（全量测试：
    21 页 micro-CER 5.65%；干净链路 @332→333 裁剪与人工初校差 1 字）。
    判信规则见 _align_cut；整页模式还用 _review_tail_cut 检查 OCR 未匹配尾文。
    说明含「页尾待核」时返回的只是暂定裁点，调用方必须保留待核提示，不能
    将裁后全部文字直接宣称为已确认的下页内容。复核只读有效末列 OCR 缓存。
    """
    md_text = _ocr_cache_read(page, store)
    cand_n = _norm(text)
    if md_text is None:
        return None, len(cand_n), "OCR 不可用"
    ocr_n = _norm("".join(_ocr_groups(md_text)))
    if not ocr_n:
        return None, len(cand_n), "OCR 无文本输出"
    if not cand_n:
        return None, 0, "候选文本为空"
    end, why = _align_cut(cand_n, ocr_n, full_page)
    if end is None:
        return None, len(cand_n), why
    if full_page:
        # 查询/回放保持只读：只在末端尚有 OCR 余文时读同一扫描图的末列缓存。
        # 缺失/过期/冲突均显式待核，不启动整页或分列识别，不按余文长度补字。
        _, rest = _tail_context(cand_n, ocr_n, end)
        if rest:
            columns = _column_cache_read(page, _page_sha(page, store))
            last_md = columns[-1]["markdown"] if columns else None
            column_n = _norm("".join(_ocr_groups(last_md))) if last_md else None
            end, review = _review_tail_cut(cand_n, ocr_n, end, column_n)
            why += review
    return end, len(cand_n), why


_OPEN_BRACKETS = "【《"


def _strip_dangling_open(seg: str) -> str:
    """页界括号贴字：孤悬页尾的开书名号属下页（同折行 ⑩ 规则「【 须与书名
    首字同行」的页界版）。归一化剥掉【《后页界裁点不可见，映射回原文时会把
    下页书名的开括号遗留为本页末字（@347 实测尾巴「…共三乏。【」）。闭括号
    相反——闭的是本页所开书名，留在页尾是正确语义（跨页书名渲染为下开口）。"""
    while seg and seg[-1] in _OPEN_BRACKETS:
        seg = seg[:-1].rstrip()
    return seg


def _flatten_parts(band: list[str]) -> list[tuple[str, int]]:
    """Keep boundaries on either side of a # scope; ordinary small text can be refolded."""
    parts: list[tuple[str, int]] = []
    pos = 0
    keep_all = any("//" in line for line in band)
    previous = ""
    for i, raw in enumerate(band):
        line = raw.strip(" \t")
        separator = i > 0 and (keep_all or "#" in previous or "#" in line)
        if separator: pos += 1
        parts.append((line, pos))
        pos += len(line)
        previous = line
    return parts


def _flatten_band(band: list[str]) -> str:
    parts = _flatten_parts(band)
    result = ""
    for line, offset in parts:
        result += "\n" * (offset - len(result)) + line
    return result


def _structural_spans(bands: list[list[str]]) -> list[tuple[int, int]]:
    """Protect large scopes and comments from OCR cuts, including a mid-line #."""
    spans: list[tuple[int, int]] = []
    base = 0
    for band in bands:
        for line, offset in _flatten_parts(band):
            starts = [i for i in (line.find("#"), line.find("//")) if i >= 0]
            if starts: spans.append((base + offset + min(starts), base + offset + len(line)))
        base += len(_flatten_band(band)) + 1
    return spans


def _map_group_offsets(blocks: list, ocr_off: list[int]) -> list[int]:
    """OCR 组界（归一化偏移）经匹配块反向映射到草稿归一化坐标（纯函数）。

    组界落在块间隙（无块覆盖）时该组界被丢弃。"""
    positions = []
    for o in ocr_off:
        for b in blocks:
            if b.b <= o <= b.b + b.size:
                positions.append(b.a + (o - b.b))
                break
    return positions


def _apply_folds(full: str, cut_norm: list[int], structural: list[tuple[int, int]]) -> list[str] | None:
    """折点游标切分拼接原文（纯函数）：返回 pieces；折点全未生效返回 None。

    规则（实测踩坑逐条入档）：
    - \\u0001 带界与 PUNCT_STRIP 字符不计归一化序号（对齐空间已剔除）
    - 结构行内部不折（整点丢弃——少折一处可见可补）；起点放行——把字头行
      与前行分开不破坏头本身，若连起点都挡，字头行与前行融合后不再以 #
      起始 → 下一击失去保护 → 周期 2 振荡（@313 实测 16→18→16 行）
    - 括号贴字：【】与《》均不计归一化序号；切点前的剥离带含【或《时，
      移到最左开书名号之前（随下文起行）；闭书名号随上文收尾；
      普通句读仍留行尾
    - 折点须先去重：OCR 组界经反向映射可坍缩到同一位点（@334 实测 24 个
      映射组界含 2 组重复），等值游标在重复位点后永不前进 → 其后折点全部
      静默丢失（整页只插 2 处、应插 20+）
    """
    def _structural_at(i: int) -> bool:
        return any(s < i < e for s, e in structural)

    norm_idx = 0
    pieces: list[str] = []
    last = 0
    cuts = sorted(set(cut_norm))
    ci = 0
    for i, ch in enumerate(full):
        if ch in PUNCT_STRIP or ch == "\u0001":
            continue
        if ci < len(cuts) and norm_idx == cuts[ci]:
            if not _structural_at(i):
                cut = i
                j = cut
                while j < len(full) and full[j] in PUNCT_STRIP and full[j] not in _OPEN_BRACKETS:
                    if full[j] in "】》":
                        cut = j + 1
                    j += 1
                j = cut
                while j > last and full[j - 1] in PUNCT_STRIP:
                    if full[j - 1] in _OPEN_BRACKETS:
                        cut = j - 1
                    j -= 1
                pieces.append(full[last:cut])
                last = cut
            ci += 1
        norm_idx += 1
    pieces.append(full[last:])
    if len(pieces) <= 1:
        return None
    return pieces


def _rebuild_bands(pieces: list[str]) -> list[list[str]]:
    """pieces 重组为 band 列表（纯函数）：\\u0001 分隔切带、空带丢弃、带首尾
    换行剥离——切点贴带界时 piece 尾/首携带裸 \\u0001，与 \\n 连接叠加成空行
    带或带内前导空行（@339 注释带后双空行实测）。"""
    flat = "\n".join(pieces)
    return [
        [line for line in b.strip("\n").split("\n") if line]
        for b in flat.split("\u0001")
        if b.strip("\n")
    ]


def ocr_fold_page_lines(page: int, bands: list[list[str]], store: kangxi_store.KangxiStore) -> tuple[list[list[str]], str]:
    """按 OCR 行组在草稿大行内插入折行（小行换行）——编排层。

    行组界即物理行界：25 页初校真值对照（2026-11-14）组界 91.5% 为真行界，
    短行组（书名堆叠「廣韻集/韻韻會」逐行、短行接书证）同样是真实断行，
    不做短片段合并（原 <8 合并规则误删 63% 真界——书名堆叠/短行接书证都
    是真实物理短行；过分裂折点保留在稿中可见即删，误折删除无风险，漏折
    补行才是隐性成本）。
    大字作用域两侧的换行必须保留，作用域内禁止 OCR 插入换行；
    仅在小字区域重折，避免把古文标签/释文并入大字。
    纯逻辑在 _flatten_band/_structural_spans/_map_group_offsets/_apply_folds/
    _rebuild_bands（可单测），本函数只做 OCR 读取、对齐判信与组装。
    """
    md_text = _ocr_cache_read(page, store)
    if md_text is None:
        return bands, "OCR 不可用，未折行"
    groups = _ocr_groups(md_text)
    if len(groups) < 2:
        return bands, "OCR 行组不足，未折行"
    ocr_n = _norm("".join(groups))
    if not ocr_n:
        return bands, "OCR 无文本，未折行"

    full = "\u0001".join(_flatten_band(b) for b in bands)
    structural = _structural_spans(bands)
    # 对齐空间剔除 \u0001 带界符：它永远匹配不上 OCR 文本，只会把匹配块
    # 打碎；且其数量随分带布局变化（regroup 后带界移动）→ 同一字符内容
    # 的折点映射随布局漂移 → 按钮不幂等（@313 实测周期 2 摆动 16→18→16）。
    full_n = "".join(ch for ch in full if ch not in PUNCT_STRIP and ch != "\u0001")
    sm = difflib.SequenceMatcher(None, full_n, ocr_n, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
    cover = sum(b.size for b in blocks)
    # 判信两侧过半。重尾溢出页（全量词条未裁/裁剪回退）full_n 远大于页面，
    # 草稿侧按「页内可比长度」衡量（取两者较小者），页面侧仍须过半——
    # 否则 @334 类页面（候选 961 字仅 ~270 字在页）永远折不了行
    if cover < len(ocr_n) * 0.5 or cover < min(len(full_n), len(ocr_n)) * 0.5:
        return bands, f"OCR 与草稿对齐不可信（{cover} 字匹配），未折行"

    ocr_off, acc = [], 0
    for g in groups[:-1]:
        acc += len(_norm(g))
        ocr_off.append(acc)
    full_positions = _map_group_offsets(blocks, ocr_off)
    if not full_positions:
        return bands, "OCR 组界无法映射，未折行"

    pieces = _apply_folds(full, full_positions, structural)
    if pieces is None:
        return bands, "折点未落在草稿内，未折行"
    result = _rebuild_bands(pieces)
    inserted = len(pieces) - 1
    return result, f"OCR 折行：插入 {inserted} 处换行"


def _is_section_header(line: str) -> bool:
    return section_heading(line) is not None


def _regroup_body(body: list[str], line_major: dict[int, int]) -> list[list[str]]:
    """按行→大列归属重组带（纯函数）。body = 展平的非空行序列；
    line_major = 正文行序号 → 大列号（// 注释与部题行不在其中）。

    规则：// 注释行不参与分配但必须保留（附着到其前一个正文行所在的大列
    带）——早期版本直接丢弃会破坏字符流（草稿 #□ 占位常带 //未编码字
    说明）；部题行永远独立成带且不参与分配——它们不是列内容，并进大列
    带后会被下一击 flatten 融合（部题间无 OCR 折点支持，@312 实测
    「## 子集上### 一部」周期 2 振荡）。"""
    groups: list[list[str]] = []
    buf: list[str] = []
    buf_major = -1
    seen = 0
    for l in body:
        ls = l.strip()
        if _is_section_header(l):
            if buf:
                groups.append(buf)
                buf = []
            groups.append([l])
            continue
        if ls.startswith("//"):
            if buf or seen < len(line_major):
                buf.append(l)
            continue
        m = line_major[seen]
        seen += 1
        if buf and m != buf_major:
            groups.append(buf)
            buf = []
        buf_major = m
        buf.append(l)
    if buf:
        groups.append(buf)
    return groups


def ocr_regroup_bands(page: int, bands: list[list[str]]) -> tuple[list[list[str]], str]:
    """按大列重排已折行的带：.gj 空行 = 大列界（空行分隔的带 = 大列）。

    依据 evidence/2026-11-14-colseg-regroup-feasibility.json：初校带法是
    机械的大列物理分组（23 页带数=覆盖大列数、金标带界 ⊆ 大列界、
    141/142 带界无字头标记），oracle F1 0.913 / 端到端 0.797、11/23 页
    零修正。实现：折叠行按归一字数 DP 单调分配到 16 小列槽
    （kangxi_column_seg.assign_lines），槽 2k/2k+1 并为大列 k——
    只重新划分行→带归属，字符流逐字不变；分割失败/退化时原样返回。
    幂等性（2026-11-14 修复，全库 28 页实测）：fold∘regroup 二击内必达
    不动点（14 页严格幂等 + 14 页二击收敛），字符流恒不变。三处根因
    修复见 ocr_fold_page_lines 的结构保护注释与本文 // 附着/部题行独立
    成带逻辑（_regroup_body）；旧的「重折个别折点偏移」限制已随
    \u0001 对齐剔除消除。
    """
    kangxi_column_seg = _column_seg()

    body = [l for b in bands for l in b if l.strip()]
    lines = [l for l in body
             if not l.strip().startswith("//") and not _is_section_header(l)]
    if len(lines) < 2:
        return bands, "行数不足，未按大列重组"
    res = page_columns(page)  # 图定位/失败口径与查询 API 统一（error 键不抛异常）
    if "error" in res:
        return bands, f"大列分割不可用（{res['error']}），未重组"
    ests = [m["chars_est"] for maj in res["majors"] for m in maj["minors"]]
    lens = [len("".join(ch for ch in l if ch not in PUNCT_STRIP)) for l in lines]
    ranges = kangxi_column_seg.assign_lines(lens, ests)
    # 每个正文行（lines 序）→ 大列号
    line_major: dict[int, int] = {}
    for j in range(len(res["majors"])):
        for rng in (ranges[2 * j], ranges[2 * j + 1]):
            if rng and rng[1] > rng[0]:
                for k in range(rng[0], rng[1]):
                    line_major[k] = j
    if len(line_major) != len(lines):
        return bands, "大列分配退化，未重组"
    groups = _regroup_body(body, line_major)
    if len(groups) < 2:
        return bands, "大列分配退化，未重组"
    sizes = ",".join(str(len(g)) for g in groups)
    return groups, f"大列重组：{len(groups)} 带（各行数 {sizes}）"


def _guwen_list(detail: dict | None) -> list[str]:
    """词条的站点古文变体列表（guwen 字段按「、」分隔）；吃 entry_detail 的结构化记录。"""
    if not detail:
        return []
    return [g for g in (detail.get("guwen") or "").split("、") if g]


def _classify_unencoded(chars: list[dict]) -> tuple[dict[int, dict], list[dict]]:
    """把 page_chars 的未编码字形归属到主字头（ord 顺序单遍扫描）。

    全库实测语义（5,143 字形，2026-11-14）：2 段名 svg（k_code 空、无 char）
    7/7 与主字头同 page_seq = 字头旁的伴随字形；K 码字形 226/226 无词条号、
    128/136 簇与前主字头站点 guwen 数量精确一致 = 古文变体（人工先例
    @331/@334：K 码归并为「#头 / 古文 / #AB」字头行，伴随字形删除）。
    返回 (归属表 主字头ord→{companions,kcodes}, 无前邻主字头的孤儿列表)。
    """
    extra: dict[int, dict] = {}
    orphans: list[dict] = []
    last_main_ord = None
    for item in chars:
        if item["char"]:
            last_main_ord = item["ord"]
            continue
        if last_main_ord is None:
            orphans.append(item)  # 页首孤例（全库 3 例：@1002/@4043/@6179）
            continue
        bucket = extra.setdefault(last_main_ord, {"companions": [], "kcodes": []})
        (bucket["kcodes"] if item.get("k_code") else bucket["companions"]).append(item)
    return extra, orphans


def _locate_band_cut(bands: list[list[str]], end: int) -> tuple[int, int, int] | None:
    """归一化裁点 end → (band_idx, line_idx, char_idx)（纯函数）。

    注释行（//）不计归一化序号（svg 路径等非页面文本）；裁点落在注释行
    之间的缝隙时返回 None（调用方保守不裁）。"""
    kept = 0
    for bi, band in enumerate(bands):
        for li, line in enumerate(band):
            if line.strip().startswith("//"):
                continue
            for ci, ch in enumerate(line):
                if ch in PUNCT_STRIP:
                    continue
                if kept == end:
                    return bi, li, ci
                kept += 1
    return None


def _cut_bands_at(bands: list[list[str]], cut: tuple[int, int, int]) -> list[list[str]]:
    """按 (bi, li, ci) 裁剪 band 序列（纯函数）。

    裁点落在字头行上时整行保留、其后裁去——末界恰在新字头处的罕见情形，
    宁少裁不误删字头（错留的字头行校对中一眼可见，下页 page_chars 亦会
    收录）。裁点所在 band 的前行属本页（@338 实测踩坑：裁在大行第二行
    行首时，首行曾被误丢）；行首/行尾悬挂的开书名号随段剥除（下页续入
    时由库文补全）。"""
    bi, li, ci = cut
    if bands[bi][li].lstrip().startswith("#"):
        return [list(b) for b in bands[: bi + 1]]  # 字头行整行保留
    head_bands = [list(b) for b in bands[:bi]]
    band_cut = list(bands[bi][:li])
    line_cut = _strip_dangling_open(bands[bi][li][:ci].rstrip())
    if line_cut:
        band_cut.append(line_cut)
    if band_cut:
        band_cut[-1] = _strip_dangling_open(band_cut[-1])  # 裁点落行首时前行整行保留，同样剥
        if band_cut[-1]:
            head_bands.append(band_cut)
    return head_bands


def _trim_bands_to_page(
    page: int, bands: list[list[str]], store: kangxi_store.KangxiStore
) -> tuple[list[list[str]], str]:
    """把完整续文与新词条组装后的草稿裁剪到本页物理末界——编排层。

    注释行不参与对齐（svg 路径等非页面文本会污染归一化候选）。定位/裁剪
    规则在 _locate_band_cut / _cut_bands_at（可单测）。"""
    flat = "\n".join(
        line for band in bands for line in band if not line.strip().startswith("//")
    )
    end, total, why = ocr_page_cut(page, flat, store, full_page=True)
    if end is None:
        return bands, (
            f"OCR 尾裁未执行：{why}——本页草稿含全量词条，"
            "添加下页前请先手工裁剪到物理页界"
        )
    review = why.partition(_TAIL_REVIEW_MARK)[2]
    if end >= total:
        if review:
            return [*bands, [f"// {_TAIL_REVIEW_MARK}{review}"]], f"OCR 尾裁：保留全部 {total} 字{why}"
        return bands, f"OCR 尾裁：本页内容未溢出页界{why}"
    cut = _locate_band_cut(bands, end)
    if cut is None:  # 裁点在注释行之间的缝隙：保守不裁
        return bands, "OCR 尾裁：裁点未落定，保守保留全量"
    trimmed = _cut_bands_at(bands, cut)
    if review:
        trimmed.append([f"// {_TAIL_REVIEW_MARK}{review}"])
        return trimmed, (
            f"OCR 尾裁暂保留 {end}/{total} 字{why}；裁后 {total - end} 字的归页尚未确认"
        )
    return trimmed, (
        f"OCR 尾裁：保留 {end}/{total} 字（页面物理末界{why}），"
        f"溢出 {total - end} 字留给下页自动续入"
    )


def _draft_bands(
    chars: list[dict],
    details: dict[int | str, dict | None],
    continuation: list[str] | None = None,
    skip_head: str | None = None,
) -> tuple[list[list[str]], dict]:
    """chars + 预取注入的字头详情 → band 序列（纯函数，可单测）。

    details 键为缩略图路径（兼容 codepoint；值 = entry_detail 结果）——数据
    获取由调用方完成，组装逻辑零 I/O。continuation 为前页未完字头的续文行
    （置于新字头之前，符合阅读顺序）；skip_head 防重复收录延续字头。
    未编码字形按 _classify_unencoded 的归属生成：K 码簇与前主字头 guwen
    数量精确一致时并入字头行（#头 / 古文 / #AB），否则 #□ 占位紧跟主字头行；
    2 段名伴随字形只留注释（人工先例是删除）。"""
    bands: list[list[str]] = []  # 每项 = 一个大行（未折行时单元素）
    counts = {"chars": 0, "unencoded": 0, "with_text": 0}
    if continuation:
        for para in continuation:
            bands.append([para])
        counts["with_text"] += 1  # 续文计入有释文字头
    extra, orphans = _classify_unencoded(chars)
    for item in chars:
        if skip_head and item["char"] == skip_head:
            counts["skipped_dup"] = counts.get("skipped_dup", 0) + 1
            continue
        if not item["char"]:
            continue  # 未编码字形经 _classify_unencoded 归属，不独立生成
        head_band = [f"#{item['char']}"]
        bands.append(head_band)
        counts["chars"] += 1
        detail = details.get(item.get("svg")) or details.get(item["codepoint"])
        ex = extra.get(item["ord"]) or {}
        for c in ex.get("companions") or []:
            bands.append([f"// 站点伴随字形（{c['svg']}）：非词条，确认后删除本行"])
            counts["companions"] = counts.get("companions", 0) + 1
        kcodes = ex.get("kcodes") or []
        if kcodes:
            gw = _guwen_list(detail)
            if len(gw) == len(kcodes):
                # 数量精确匹配才归并（128/136 簇）；字头行同人工校对风格
                head_band.extend(["古文：", "#" + "".join(gw)])
                svgs = "、".join(k["svg"] for k in kcodes)
                bands.append([f"// 古文变体归并自站点 guwen 元数据（{svgs}），请对照原图核对"])
                counts["guwen_merged"] = counts.get("guwen_merged", 0) + 1
            else:
                for kcitem in kcodes:
                    bands.append(["#□"])
                    bands.append([
                        f"// 未编码字（{kcitem['k_code']}，{kcitem['svg']}）："
                        "疑似前字头变体（guwen 缺失/数量不符），请对照原图补录"
                    ])
                    counts["unencoded"] += 1
        if detail:
            paragraphs = [p for p in detail.get("text_paragraphs") or [] if p.strip()]
            if paragraphs:
                counts["with_text"] += 1
                bands.extend([p] for p in paragraphs)
    for item in orphans:
        k = f"{item.get('k_code') or '？'}，{item['svg']}"
        bands.append(["#□"])
        bands.append([f"// 未编码字（{k}）：本页无前邻主字头，请对照原图补录"])
        counts["unencoded"] += 1
    return bands, counts


def build_draft_gj(
    page: int,
    store: kangxi_store.KangxiStore,
    continuation: list[str] | None = None,
    skip_head: str | None = None,
    fold: bool = True,
) -> tuple[str, dict]:
    """由库内 page_chars + entries 生成 .gj 草稿与统计——编排层。

    continuation 必须是未裁剪的完整续文，与本页新字头一起交给 _draft_bands
    组装；只执行一次整页 OCR 尾裁（_trim_bands_to_page）。单独拿续文匹配
    整页 OCR 会把页中漏识误作页界（@406「辨」），并误中后续词条的同文。
    整页尾裁把溢出到下页的尾段裁掉——库内全量在，添加下页时自动续入；OCR 不可用
    时回退全量并在 notes 警告。fold=True 且 OCR 服务可用时，按 OCR 行组
    在大行内插入折行（只插入换行不改字符）并按大列重组带；不可用/不可信
    时草稿为未折行的平铺段——校对者回退到手工折行。
    空白页（无字头索引且无前页续文，@329/@337）：草稿仅保留 @页码 行、
    正文留空，尾裁/折行/重组跳过（零内容无作用对象，提示语反会误导）。
    """
    chars = page_heads(page, store)
    if not chars and not continuation:
        counts = {
            "blank": True, "chars": 0, "unencoded": 0, "with_text": 0,
            "ocr_notes": ["空白页：无字头索引且无前页续文，正文留空；"
                          "若原图实际有内容，请对照原图手工补录"],
        }
        return f"@{page}\n", counts

    details = _page_entry_details(chars, page, store)
    bands, counts = _draft_bands(chars, details, continuation, skip_head)
    notes = [d["selection_note"] for d in details.values() if d and d.get("selection_note")]

    bands, note = _trim_bands_to_page(page, bands, store)
    notes.append(note)

    if fold:
        bands, note = ocr_fold_page_lines(page, bands, store)
        notes.append(note)
        bands, note = ocr_regroup_bands(page, bands)
        notes.append(note)

    # 不写首行草稿注释：页状态以 manifest status 为准，且人工校对页同样
    # 直接以 @页码 开头（若日后加回头注，注释与 @页码 间必须空行，否则
    # 并入同一大行致页声明不解析）
    parts = [f"@{page}"]
    for band in bands:
        parts.append("")
        parts.extend(band)
    counts["ocr_notes"] = notes
    return "\n".join(parts) + "\n", counts


def cmd_ocr_fold(page: int, fold: bool = True) -> dict:
    """对已入库页的 .gj 执行 OCR 折行（CLI 兜底：添加时 OCR 服务不可用、
    草稿未折行，服务恢复后补折；前端工具栏按钮已删，添加流程在
    build_draft_gj 内自动折行）。

    读取该页 .gj 的现有大行结构，按 OCR 行组插入换行——只插入换行、不改字符；
    页面已有折行会被先去掉再按 OCR 重折（幂等）。只写回 .gj，按需派生。
    """
    gj_path = ANNOTATIONS / f"{page:04d}.gj"
    raw = page_gj(page)
    if raw is None:
        raise RuntimeError(f"页 {page} 不在数据集中")
    store = kangxi_store.KangxiStore()

    head, bands = parse_gj_bands(raw)  # 头部（注释 + @页码 行）与正文大列带

    page_ocr(page, store=store)
    folded, note = ocr_fold_page_lines(page, bands, store)
    if folded is not bands and fold:
        folded, rnote = ocr_regroup_bands(page, folded)
        note = f"{note}；{rnote}"
    if fold and folded is bands:
        return {"ok": True, "page": page, "note": note, "changed": False}

    # 过滤空 band / 空行成员，避免连续空行（空行是 .gj 的大行分隔，连续会成空大行）
    parts = list(head)
    for band in folded:
        lines = [l.rstrip() for l in band if l.strip()]
        if not lines:
            continue
        parts.append("")
        parts.extend(lines)
    gj_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")

    return {"ok": True, "page": page, "note": note, "changed": True}


def cmd_ocr_view(page: int) -> dict:
    """只读 OCR 缓存。打开弹窗不提交识别任务。"""
    store = kangxi_store.KangxiStore(readonly=True)
    snapshot = ocr_cache_snapshot(page, _page_sha(page, store))
    return {"ok": True, "page": page, "markdown": snapshot["markdown"],
            "hint": f"{snapshot['reason']}；请在 OCR 预取页执行预取" if snapshot["state"] != "valid" else None}


def cmd_ocr_pages() -> dict:
    """各页 OCR/预取浅状态清单（预取调试视图数据源）。

    页集合 = 数据集页 ∪ 库内已爬页 ∪ OCR 缓存页。每页不含 markdown 本身
    （体积控制，详情走 ocr-view / prefetch-status）。当前图 sha 库内优先，
    未爬但有缓存的页回退 manifest（同 _scan_for 口径）。
    """
    store = kangxi_store.KangxiStore(readonly=True)
    rows = {r["page"]: r for r in store.page_rows()}
    manifest = load_manifest()
    ds_status = {p["page"]: p.get("status", "first") for p in manifest.get("pages", [])}
    ds_sha = {p["page"]: p.get("sha256") or "" for p in manifest.get("pages", [])}
    cached_pages: set[int] = set()
    if paths.OCR_CACHE_DIR.is_dir():
        for f in paths.OCR_CACHE_DIR.glob("*.json"):
            if f.stem.isdigit():
                cached_pages.add(int(f.stem))
    pages = []
    for page in sorted(set(rows) | set(ds_status) | cached_pages):
        r = rows.get(page) or {}
        cur_sha = r.get("scan_sha256") or ds_sha.get(page) or ""
        ocr = _ocr_cache_meta(page, cur_sha)
        pages.append({
            "page": page,
            "dataset_status": ds_status.get(page),
            "has_reading": bool(r.get("has_reading")),
            "has_scan": bool(r.get("scan_sha256") and r.get("scan_file")),
            "chars_n": r.get("chars_n", 0),
            "entries_missing_n": r.get("entries_missing_n", 0),
            "ocr_state": ocr["state"],
            "ocr_fetched_at": ocr["fetched_at"],
            "ocr_chars": ocr["chars"],
        })
    return {"ok": True, "pages": pages, "total": len(pages)}


def cmd_prefetch_status(page: int) -> dict:
    """单页预取四步深查（只读现状，不执行任何抓取）——薄壳，逻辑在 page_prefetch_state。"""
    return {"ok": True, **page_prefetch_state(page, include_markdown=True)}


def cmd_prefetch_run(page: int) -> dict:
    """手动执行单页预取链路（同 add 后台预取的四步，同步等待完成）。

    调试用：不依赖真实 add 即可验证 prefetch_next_page 行为。未爬页会
    联网爬取（fetch 自带限速），OCR 需本地服务在线。
    """
    if not 1 <= page <= 7738:
        raise RuntimeError(f"页码 {page} 超出站点范围 1-7738")
    steps = _prefetch_pipeline(page)
    return {"ok": True, "completed": all(s["ok"] for s in steps), "page": page, "steps": steps}


def cmd_prefetch_log(tail_n: int = 50) -> dict:
    """prefetch.log 尾部行（时间线展示）。"""
    f = paths.OCR_CACHE_DIR / "prefetch.log"
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines() if f.exists() else []
    return {"ok": True, "total": len(lines), "lines": lines[-tail_n:]}


def cmd_replay_pages() -> dict:
    """流程演示样例集：manifest 中所有初校（first）页 + 金标带/行数。"""
    pages = []
    for p in load_manifest().get("pages", []):
        if p.get("status") != "first":
            continue
        raw = page_gj(p["page"])
        _, bands = parse_gj_bands(raw) if raw else ([], [])
        pages.append({
            "page": p["page"],
            "bands_n": len(bands),
            "lines_n": sum(len(b) for b in bands),
        })
    return {"ok": True, "pages": pages, "total": len(pages)}


def _compare_bands(auto: list[list[str]], gold: list[list[str]]) -> dict:
    """自动带 vs 金标带（找错核心）：字符流一致性 + 行界/带界 F1 + 差集 + 首分歧。

    指标口径复用 eval_pipeline_replay（norm_offsets/f1/stream），函数体内
    延迟 import 避免循环依赖（该模块 import 本模块）。差集为精确集合差
    （f1 的 ±tol 匹配只作分数），偏移均为归一化字符坐标。"""
    if str(EVAL) not in sys.path:
        sys.path.insert(0, str(EVAL))
    from eval_pipeline_replay import f1, norm_offsets, stream

    a_stream, g_stream = stream(auto), stream(gold)
    _, al, ab = norm_offsets(auto)
    _, gl, gb = norm_offsets(gold)
    # 首分歧（逐位比对，直观入口）
    first_diff = None
    for i, (x, y) in enumerate(zip(a_stream, g_stream)):
        if x != y:
            first_diff = {"offset": i,
                          "auto_ctx": a_stream[max(0, i - 20):i + 20],
                          "gold_ctx": g_stream[max(0, i - 20):i + 20]}
            break
    if first_diff is None and len(a_stream) != len(g_stream):
        i = min(len(a_stream), len(g_stream))
        first_diff = {"offset": i, "auto_ctx": a_stream[i:i + 20], "gold_ctx": g_stream[i:i + 20]}
    # 分歧块（SequenceMatcher 对齐后的非 equal 区间）：replace/delete/insert
    # 三型 + 两侧上下文——字符流有差时漏/多折清单的偏移空间会错位，块列表
    # 是更可靠的找错入口（金标含人工校订/标题/注释，与库内重建天然有差）
    sm = difflib.SequenceMatcher(None, a_stream, g_stream, autojunk=False)
    diff_blocks = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        diff_blocks.append({
            "tag": tag,
            "auto": a_stream[i1:i2][:60],
            "gold": g_stream[j1:j2][:60],
            "ctx": g_stream[max(0, j1 - 10):j1] + "▸" + g_stream[j1:j2][:30] + "◂" + g_stream[j2:j2 + 10],
        })
        if len(diff_blocks) >= 20:
            break
    return {
        "ok_stream": a_stream == g_stream,
        "lf1": round(f1(al, gl), 3),
        "bf1": round(f1(ab, gb), 3),
        "auto": {"bands": len(auto), "lines": sum(len(b) for b in auto),
                 "chars": len(a_stream)},
        "gold": {"bands": len(gold), "lines": sum(len(b) for b in gold),
                 "chars": len(g_stream)},
        # 漏/多以金标为基准命名：missing = 金标有自动无（欠折/欠带）
        "missing_line_breaks": sorted(gl - al),
        "extra_line_breaks": sorted(al - gl),
        "missing_band_breaks": sorted(gb - ab),
        "extra_band_breaks": sorted(ab - gb),
        "first_diff": first_diff,
        "diff_blocks": diff_blocks,
        "diff_blocks_total": len([1 for t, *_ in sm.get_opcodes() if t != "equal"]),
    }


def cmd_pipeline_replay(page: int) -> dict:
    """单页全管线只读重放（流程演示视图数据源）：逐步骤中间结果 + 金标对照。

    零写盘：不爬取、不落 .gj/manifest、不触发预取；数据补齐步只报现状。
    前页 .gj 用初校版（人工校订后的真值）——与当年 add 时的草稿前页不同，
    重放结果代表「管线对干净输入的行为」，供观察/调试/找错。"""
    store = kangxi_store.KangxiStore(readonly=True)

    # ① 数据现状（add 的补齐步只读版）
    chars = page_heads(page, store)
    data = {
        "heads": [c["char"] for c in chars if c["char"]],
        "unencoded_n": sum(1 for c in chars if not c["char"]),
        "missing_entries": store.coded_chars_missing_entries(page),
    }

    # ② 完整前页续入：与新词条一起组装后才裁页尾，不能独立裁续文。
    cont, info = continuation_from_prev(page, store)
    continuation = {"info": info, "rest_paragraphs": cont}

    # ③ 草稿构建四态演化（拆开 build_draft_gj 内部调用以保留中间产物；
    # 空白页同 build_draft_gj 跳过尾裁/折行/重组——零内容提示语反会误导）
    details = _page_entry_details(chars, page, store)
    bands0, counts = _draft_bands(chars, details, cont or None, info.get("head"))
    if not chars and not cont:
        counts["blank"] = True
        note = "空白页：正文留空"
        bands1, cut_note = bands0, note
        bands2, fold_note = bands0, note
        bands3, regroup_note = bands0, note
    else:
        bands1, cut_note = _trim_bands_to_page(page, bands0, store)
        bands2, fold_note = ocr_fold_page_lines(page, bands1, store)
        bands3, regroup_note = ocr_regroup_bands(page, bands2)
    draft = {
        "counts": counts,
        "stages": [
            {"name": "raw", "label": "原始带", "bands": bands0,
             "note": f"_draft_bands：字头 {counts.get('chars', 0)}、含释义 {counts.get('with_text', 0)}"},
            {"name": "tail_cut", "label": "尾裁后", "bands": bands1, "note": cut_note},
            {"name": "fold", "label": "折行后", "bands": bands2, "note": fold_note},
            {"name": "regroup", "label": "重组后", "bands": bands3, "note": regroup_note},
        ],
    }

    # ④⑤ 金标对照 + 原文
    raw = page_gj(page)
    _, gold_bands = parse_gj_bands(raw) if raw else ([], [])
    return {
        "ok": True,
        "page": page,
        "data": data,
        "continuation": continuation,
        "draft": draft,
        "compare": _compare_bands(bands3, gold_bands),
        "gold": raw,
    }


def cmd_ocr_skeleton_replay(page: int) -> dict:
    """新版流程实验（只读演示，评估用）：OCR 为骨架、库文为校对蓝本。

    与生产流程（库文字符 + OCR 标尺）相反的范式——各步骤：
      ① 整页 OCR = 文字底稿；② 分列 OCR = 分段（列界=带界）；
      ③ 蓝本（完整前页续文 + 本页字头详情，统一组装并尾裁的库文流）
        对底稿做对齐替换（SequenceMatcher 非等块：replace=错字改库文、
        insert=OCR 伪读删去、delete=OCR 漏识补入）；
      ④ 终稿 = 纠错后字符流按列字符量切段（每列一带）。
    演示要点（评估实证）：替换完全的终稿字符≡蓝本（殊途同归）；分段为
    累计偏移推断，空列/漏识会雪崩（后续列界全错）；折行证据缺位
    （分列行组真值率仅 32%，见实验记录）。"""
    store = kangxi_store.KangxiStore(readonly=True)

    # ① 底稿：整页 OCR（剥邊題）
    md = _ocr_cache_read(page, store)
    if md is None:
        raise RuntimeError(f"@{page} 整页 OCR 缓存不可用，请先执行预取")
    groups = _ocr_groups(md)
    ocr_n = _norm("".join(groups))

    # ② 分段：分列 OCR（列界 = 带界）
    cols = _column_cache_read(page, _page_sha(page, store))
    if not column_ocr_complete(cols):
        raise RuntimeError(f"@{page} 分列 OCR 缓存不完整，请先执行列级预取")
    _, gold_bands = parse_gj_bands(page_gj(page) or "")
    col_infos = []
    for j, c in enumerate(cols):
        cn = len(_norm(c["markdown"] or ""))
        gn = (sum(len(_norm(l)) for l in gold_bands[j])
              if j < len(gold_bands) else None)
        col_infos.append({
            "index": c["index"], "norm_len": cn,
            "groups_n": len([g for g in (c["markdown"] or "").split("\n\n") if g.strip()]),
            "markdown": c["markdown"] or "",
            "empty": cn == 0,
            "gold_band_chars": gn,
            "gold_band_lines": len(gold_bands[j]) if j < len(gold_bands) else None,
        })

    # ②' 归列重排：整页行组按分列证据归列（同列聚合一段、列间空行）。
    # 实测（37 初校页）：整页行组 100% 可子串定位到唯一列且列聚簇（竖排
    # OCR 按列扫描输出）；分列正常页的重排结构与金标带逐字吻合（@332 类
    # bf1 0.86+），失败模式明确可判——首尾大字列漏识产生无主行组
    # （@356：19 组）、列分割坐标崩页列字符分布畸形（@336）。
    col_norms = [_norm(c["markdown"] or "") for c in cols]
    # 严格约束版：不修改文字/文字顺序/行组顺序，只重排空行——行组按原顺序
    # 遍历归列，列号变化处开新段（\n\n），同列内组间用 \n；组原文保留
    # （含组内换行，不剥邊題组——邊題归 None 段独立成节）。误判最多导致
    # 段界位置偏移，永不重排内容。
    raw_groups = [g for g in md.split("\n\n") if g.strip()]
    col_of: list[int | None] = []
    stray_n = 0
    last_col: int | None = None
    for g in raw_groups:
        gn = _norm(g)
        hits = [j for j, cn in enumerate(col_norms) if gn and gn in cn]
        if hits:
            last_col = hits[0] if len(hits) == 1 else max(
                hits, key=lambda k: difflib.SequenceMatcher(None, gn, col_norms[k]).ratio())
        # 无主（分列漏识区）：沿用前一组列号（阅读序连续）；页首无主 → None
        col_of.append(last_col)
    parts: list[str] = []
    seg_lines: list[int] = []
    buf: list[str] = []
    prev: int | None = None
    for g, c in zip(raw_groups, col_of):
        if c != prev:
            if buf:
                parts.append("\n".join(buf))
                seg_lines.append(len(buf))
                buf = []
        buf.append(g.rstrip("\n"))
        prev = c
    if buf:
        parts.append("\n".join(buf))
        seg_lines.append(len(buf))
    regrouped_md = "\n\n".join(parts)
    stray = sum(1 for c in col_of if c is None)

    # ③ 蓝本纠错：库文流（同生产流程字符源）对底稿整页对齐
    chars = page_heads(page, store)
    cont, info = continuation_from_prev(page, store)
    details = _page_entry_details(chars, page, store)
    bands0, _ = _draft_bands(chars, details, cont or None, info.get("head"))
    bp_bands, bp_note = _trim_bands_to_page(page, bands0, store)
    bp_n = _norm("".join(l.strip(" \t") for b in bp_bands for l in b
                        if not l.lstrip().startswith("//")))
    sm = difflib.SequenceMatcher(None, bp_n, ocr_n, autojunk=False)
    n_replace = n_ocr_only = n_bp_only = 0
    diff_blocks = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            n_replace += i2 - i1
        elif tag == "insert":
            n_ocr_only += j2 - j1
        else:
            n_bp_only += i2 - i1
        diff_blocks.append({
            "tag": tag,
            "blueprint": bp_n[i1:i2][:40],
            "ocr": ocr_n[j1:j2][:40],
        })
        if len(diff_blocks) >= 30:
            break

    # ④ 终稿：蓝本字符流按列 norm 长度切段（每列一带；折行证据缺位，平铺）
    result_bands: list[list[str]] = []
    pos = 0
    for c in col_infos:
        seg = bp_n[pos:pos + c["norm_len"]]
        pos += c["norm_len"]
        result_bands.append([seg] if seg else [])
    result_bands = [b for b in result_bands if b]
    residual = bp_n[pos:]  # 蓝本剩余（列字符总量 < 蓝本时）

    empty_cols = sum(1 for c in col_infos if c["empty"])
    return {
        "ok": True,
        "page": page,
        "draft_ocr": {"markdown": md, "norm_len": len(ocr_n), "groups_n": len(groups)},
        "columns": col_infos,
        "blueprint": {"norm_len": len(bp_n), "source": f"完整续文与本页字头详情统一尾裁；{bp_note}"},
        "fix": {
            "replace_chars": n_replace,
            "ocr_only_chars": n_ocr_only,
            "blueprint_only_chars": n_bp_only,
            "diff_blocks": diff_blocks,
            "diff_blocks_total": sum(1 for t, *_ in sm.get_opcodes() if t != "equal"),
        },
        "result": {"bands": result_bands, "residual_chars": len(residual)},
        "regrouped_ocr": {
            "markdown": regrouped_md,
            "seg_lines": seg_lines,
            "gold_band_lines": [len(b) for b in gold_bands],
            "stray": stray,
        },
        "compare": _compare_bands(result_bands, gold_bands),
        "verdict": {
            "empty_cols": empty_cols,
            "cols_n": len(col_infos),
            "gold_bands_n": len(gold_bands),
        },
    }


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _index_from_manifest(manifest: dict) -> dict:
    """manifest → 前端页清单结构（纯函数）。"""
    return {
        "source": "kangxi-gold",
        "images_dir": manifest["images_dir"],
        "pages": [
            {
                "page": p["page"],
                "image": p["image"],
                "gj": p.get("annotations", {}).get("gj", f"{p['page']:04d}.gj"),
                "width": p.get("width"),
                "height": p.get("height"),
                "status": p.get("status", "first"),
            }
            for p in manifest.get("pages", [])
        ],
    }


def cmd_dataset_index() -> dict:
    """直接读取当前清单和配置；没有需要随写的前端快照。"""
    config = json.loads((MANIFEST.parent / "dataset-config.json").read_text(encoding="utf-8"))
    return {"ok": True, **_index_from_manifest(load_manifest()), "config": config}


def _prefetch_pipeline(nxt: int) -> list[dict]:
    """对单页执行完整预取链路：爬取 → 字头详情 → OCR → svg 回补。

    add 后台预取（prefetch_next_page）与 prefetch-run 子命令共用本函数——
    调试视图据此逐步核验链路是否正确。每步结果 {step, ok, detail}；
    日志行为不变：失败写 var/ocr-cache/prefetch.log，③④ 完成各写一行汇总。
    """
    import logging

    logging.basicConfig(
        filename=paths.OCR_CACHE_DIR / "prefetch.log", filemode="a",
        level=logging.INFO, format="%(asctime)s %(message)s",
    )
    steps: list[dict] = []
    step_marks = [time.monotonic()]

    def done(step: str, ok: bool, detail: str) -> None:
        now = time.monotonic()
        steps.append({"step": step, "ok": ok, "detail": detail,
                      "secs": round(now - step_marks[-1], 1)})
        step_marks.append(now)
        # 成功也写一行带耗时（原版只写失败）——prefetch-log 时间线数据源
        if ok:
            logging.info(f"@{nxt} {step} 完成 ({now - step_marks[-2]:.1f}s): {detail}")
        else:
            logging.info(f"@{nxt} {step} 失败: {detail}")

    try:
        # ① 爬取（库里有则零网络；fetch 脚本自带 robots/限速/重试）
        fetch = subprocess.run(
            [sys.executable, str(CRAWL / "fetch_kangxi_page.py"), "--pages", str(nxt)],
            capture_output=True, text=True, timeout=600,
        )
        if fetch.returncode != 0:
            done("fetch", False, f"退出码 {fetch.returncode}: {fetch.stderr[-200:]}")
            return steps
        store = kangxi_store.KangxiStore()
        missing = store.coded_chars_missing_entries(nxt)
        done("fetch", True, "阅读页+原图已就绪（库内有则零网络）")
        # ② 字头详情（增量；page_chars 为空时 skip）
        if missing:
            e = subprocess.run(
                [sys.executable, str(CRAWL / "fetch_kangxi_entry.py"), "--pages", str(nxt)],
                capture_output=True, text=True, timeout=900,
            )
            if e.returncode != 0:
                done("entries", False, f"退出码 {e.returncode}: {e.stderr[-200:]}")
            else:
                rest = store.coded_chars_missing_entries(nxt)
                done("entries", not rest, f"补抓 {len(missing)} 个字头详情，余缺 {len(rest)}")
        else:
            done("entries", True, "字头详情齐全（或该页无字头）")
        # ③ 直接复用识别入口，不再启动批量 CLI 子进程。
        try:
            markdown = page_ocr(nxt, store=store)
            done("ocr", markdown is not None,
                 f"正文 {len(markdown)} 字符" if markdown is not None else "识别失败或正文残缺，可重试")
        except Exception as e:
            done("ocr", False, f"异常 {type(e).__name__}: {e}")
        # ④ 字头 svg 回补（未编码字形图；缓存命中则零网络，失败仅记日志）
        try:
            import kangxi_svg_cache

            stat = kangxi_svg_cache.cache_page_svgs(
                store, nxt, kangxi_svg_cache.pick_svg_dir(None)
            )
            if any(stat.values()):
                logging.info(f"@{nxt} svg 缓存: {stat}")
            done("svg", stat["error"] == 0,
                 f"命中 {stat['hit']} 采纳 {stat['adopt']} 抓取 {stat['fetch']} 失败 {stat['error']}")
        except (Exception, SystemExit) as e:  # noqa: BLE001 —— SystemExit：外置盘未挂载
            logging.info(f"@{nxt} svg 缓存异常: {e}")
            done("svg", False, f"异常 {type(e).__name__}: {e}")
    except Exception as e:  # noqa: BLE001 —— 预取绝不影响 add
        logging.info(f"@{nxt} prefetch 异常: {e}")
        steps.append({"step": "pipeline", "ok": False, "detail": f"异常 {type(e).__name__}: {e}"})
    return steps


def prefetch_next_page(page: int) -> None:
    """后台预取 page+1：以独立进程运行 prefetch-run（爬取→字头→OCR→svg）。

    添加第 n 页后自动调用，用户校对完第 n 页再添加 n+1 时 OCR 已就绪。
    独立进程（start_new_session 脱离进程组）：add 子进程 print 结果后立即
    退出，HTTP 响应不被 N+1 预取拖延（曾实测被 OCR 现算拖 16s+）；预取
    链路自身失败只写 prefetch.log，不影响 add 结果。
    """
    nxt = page + 1
    if not 1 <= nxt <= 7738:
        return
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "prefetch-run", "--page", str(nxt)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, cwd=str(REPO),
    )
    _log_ts(f"预取 @{nxt} 已移交独立进程（prefetch-run）")


def cmd_add(page: int) -> dict:
    global _ADD_T0
    _ADD_T0 = time.monotonic()
    _log_ts(f"add @{page} 开始")
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
    chars = page_heads(page, store)
    missing_entries = [
        c["char"] for c in chars
        if c["char"] and entry_detail(c["codepoint"], store) is None
    ]
    if chars and missing_entries:
        summaries.append(run_fetch("fetch_kangxi_entry.py", page, "字头详情"))
    elif chars:
        summaries.append(f"字头详情：库中已有 {len(chars) - len(missing_entries)}/{len(chars)}，未联网")

    # 字头 svg 回补：未编码字形图随加随缓存（校对时可离线对照原图）；
    # 失败降级为一句话，绝不杀 add 流程（同 kangxi_crawl_next 的挂钩韧性）
    try:
        import kangxi_svg_cache

        svg_stat = kangxi_svg_cache.cache_page_svgs(
            store, page, kangxi_svg_cache.pick_svg_dir(None)
        )
        if any(svg_stat.values()):
            summaries.append(
                f"字头 svg：命中 {svg_stat['hit']} 采纳 {svg_stat['adopt']}"
                f" 抓取 {svg_stat['fetch']} 失败 {svg_stat['error']}"
            )
    except Exception as e:  # noqa: BLE001
        summaries.append(f"字头 svg 缓存异常已跳过（{type(e).__name__}）")
    _log_ts("页数据/字头详情/svg 补齐完成")

    row = store.get_page(page)
    if not row or not row.get("scan_sha256") or not row.get("scan_file"):
        raise RuntimeError(f"页 {page} 原图数据仍缺失")
    scan_file = Path(row["scan_file"])
    if not scan_file.is_file():
        # 库内路径失效（如外置盘目录重排后未迁移）——别让 read_bytes 抛裸 Errno
        raise RuntimeError(
            f"页 {page} 库内原图路径已失效：{scan_file}\n"
            f"图片实际位置若为 {paths.RAW_KANGXI_PAGES}，迁移 crawl 库："
            f"UPDATE pages SET scan_file = replace(scan_file, '<旧目录>/', "
            f"'{paths.RAW_KANGXI_PAGES}/') WHERE scan_file LIKE '%<旧目录>/%'"
        )
    images_dir = Path(manifest["images_dir"])
    if scan_file.parent != images_dir:
        # 爬取时用了别的 --out：把图复制到数据集图片目录
        images_dir.mkdir(parents=True, exist_ok=True)
        target = images_dir / f"{page:04d}.jpg"
        target.write_bytes(scan_file.read_bytes())
        scan_file = target

    # 前页未完字头续入（只读前页 .gj，不回写；站点 page_chars 不标延续字头）
    page_ocr(page, store=store)
    continuation, cont_info = continuation_from_prev(page, store)
    if cont_info.get("source_note"):
        summaries.append(cont_info["source_note"])
    if cont_info.get("skipped"):
        summaries.append(f"前页续入跳过：{cont_info['skipped']}")
    else:
        summaries.append(
            f"前页续入：@{cont_info['prev_page']} 字头「{cont_info['head']}」余 {cont_info['paragraphs']} 段"
        )

    draft, counts = build_draft_gj(
        page, store, continuation=continuation or None, skip_head=cont_info.get("head")
    )
    summaries.extend(counts.pop("ocr_notes", []))
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
    _log_ts(f"草稿+manifest 写盘完成（{gj_path.name}）")

    # 后台预取 n+1：独立进程，不阻塞本进程退出（HTTP 响应 ~1s 内返回）
    prefetch_next_page(page)

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
    return {"ok": True, "page": page, "status": to, "label": STATUS_LABELS[to]}


def cmd_crawl_heads(page: int, *, db_path: Path | None = None) -> dict:
    """校对字头栏按页查库；不依赖 manifest，不触发抓取或数据库初始化。"""
    if not 1 <= page <= 7738:
        raise ValueError(f"页码 {page} 超出站点范围 1-7738")
    store = kangxi_store.KangxiStore(db_path or kangxi_store.DEFAULT_DB, readonly=True)
    # 缺阅读页不能解释为零字头；纯续文页已采集但 page_chars 为空，返回 []。
    row = store.get_page(page)
    heads = page_heads(page, store) if row and row.get("reading_html") else None
    return {"ok": True, "page": page, "heads": heads}


def cmd_crawl_entry(codepoint: int, *, db_path: Path | None = None) -> dict:
    """校对弹窗按码位查库；只返回解析后的词条，无 raw_html 或网络补抓。"""
    if not 1 <= codepoint <= 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
        raise ValueError(f"无效 Unicode 码位：{codepoint}")
    store = kangxi_store.KangxiStore(db_path or kangxi_store.DEFAULT_DB, readonly=True)
    return {"ok": True, "codepoint": codepoint, "entry": entry_detail(codepoint, store)}


def cmd_crawl_glyphs(codepoints: list[int], *, db_path: Path | None = None) -> dict:
    if len(codepoints) > 64 or any(not 1 <= cp <= 0x10FFFF or 0xD800 <= cp <= 0xDFFF for cp in codepoints):
        raise ValueError("无效 SVG 查询码位（最多 64 字）")
    from crawl_glyphs import glyph_urls
    store = kangxi_store.KangxiStore(db_path or kangxi_store.DEFAULT_DB, readonly=True)
    return {"ok": True, "glyphs": glyph_urls(codepoints, store)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dataset-index")
    cg = sub.add_parser("crawl-glyphs")
    cg.add_argument("--codepoints", type=int, nargs="+", required=True)
    a = sub.add_parser("add")
    a.add_argument("--page", type=int, required=True)
    s = sub.add_parser("status")
    s.add_argument("--page", type=int, required=True)
    s.add_argument("--to", required=True)
    ch = sub.add_parser("crawl-heads")
    ch.add_argument("--page", type=int, required=True)
    ce = sub.add_parser("crawl-entry")
    ce.add_argument("--codepoint", type=int, required=True)
    f = sub.add_parser("ocr-fold")
    f.add_argument("--page", type=int, required=True)
    v = sub.add_parser("ocr-view")
    v.add_argument("--page", type=int, required=True)
    sub.add_parser("ocr-pages")
    ps = sub.add_parser("prefetch-status")
    ps.add_argument("--page", type=int, required=True)
    pr = sub.add_parser("prefetch-run")
    pr.add_argument("--page", type=int, required=True)
    pl = sub.add_parser("prefetch-log")
    pl.add_argument("--tail", type=int, default=50)
    sub.add_parser("replay-pages")
    rp = sub.add_parser("pipeline-replay")
    rp.add_argument("--page", type=int, required=True)
    sk = sub.add_parser("ocr-skeleton-replay")
    sk.add_argument("--page", type=int, required=True)
    args = ap.parse_args()

    try:
        if args.cmd == "dataset-index":
            result = cmd_dataset_index()
        elif args.cmd == "add":
            result = cmd_add(args.page)
        elif args.cmd == "crawl-heads":
            result = cmd_crawl_heads(args.page)
        elif args.cmd == "crawl-entry":
            result = cmd_crawl_entry(args.codepoint)
        elif args.cmd == "crawl-glyphs":
            result = cmd_crawl_glyphs(args.codepoints)
        elif args.cmd == "ocr-fold":
            result = cmd_ocr_fold(args.page)
        elif args.cmd == "ocr-view":
            result = cmd_ocr_view(args.page)
        elif args.cmd == "ocr-pages":
            result = cmd_ocr_pages()
        elif args.cmd == "prefetch-status":
            result = cmd_prefetch_status(args.page)
        elif args.cmd == "prefetch-run":
            result = cmd_prefetch_run(args.page)
        elif args.cmd == "prefetch-log":
            result = cmd_prefetch_log(args.tail)
        elif args.cmd == "replay-pages":
            result = cmd_replay_pages()
        elif args.cmd == "pipeline-replay":
            result = cmd_pipeline_replay(args.page)
        elif args.cmd == "ocr-skeleton-replay":
            result = cmd_ocr_skeleton_replay(args.page)
        else:
            result = cmd_status(args.page, args.to)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if args.cmd == "add":
            # 计时打点仅 add 链路输出，避免轮询类子命令（ocr-pages 等）刷日志
            _log_ts("结果 JSON 已 print——add 进程即将退出（预取已在独立进程）")
        return 0
    except Exception as e:  # noqa: BLE001 —— 桥接给 HTTP 层
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
