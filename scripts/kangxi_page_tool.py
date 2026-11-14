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
_PREFETCH_THREADS: list = []


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


_OCR_CACHE: dict[int, str] = {}
_OCR_CACHE_DIR = REPO / "paddleocr-baseline" / "data" / "ocr-markdown"


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


def _ocr_cache_read(page: int, store: kangxi_store.KangxiStore) -> str | None:
    """持久缓存命中（sha256 与扫描图一致）→ markdown；空串哨兵=None；未命中=None。"""
    f = _OCR_CACHE_DIR / f"{page:04d}.json"
    if not f.exists():
        return None
    try:
        entry = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    _, cur_sha = _scan_for(page, store)
    if not entry.get("sha256") or entry["sha256"] != cur_sha:
        return None  # 图已变（重爬），缓存失效
    md = entry.get("markdown") or ""
    return md or None


def _ocr_cache_write(page: int, store: kangxi_store.KangxiStore, markdown: str) -> None:
    _, sha = _scan_for(page, store)
    if not sha:
        return
    _OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (_OCR_CACHE_DIR / f"{page:04d}.json").write_text(
        json.dumps({"page": page, "sha256": sha, "markdown": markdown,
                    "fetched_at": date.today().isoformat()}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _ocr_markdown(page: int, store: kangxi_store.KangxiStore) -> str | None:
    """取该页扫描图的 OCR markdown（本地 paddleocr-baseline 服务）。

    读取顺序：进程内缓存 → 本地持久缓存（scripts/prefetch_ocr.py 预填，
    sha256 校验）→ 提交新 job（成功后回写持久缓存）。全程 ~0 网络等待当缓存命中。
    服务未运行 / 提交失败 / 轮询超时 / 无文本 → 返回 None（调用方按需回退）。
    """
    import urllib.request

    cached = _OCR_CACHE.get(page)
    if cached is not None:
        return cached if cached != "" else None
    persistent = _ocr_cache_read(page, store)
    if persistent is not None:
        _OCR_CACHE[page] = persistent
        return persistent
    base = "http://127.0.0.1:8010"
    img, sha = _scan_for(page, store)
    if img is None:
        _OCR_CACHE[page] = ""
        return None
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=3) as r:
            if json.loads(r.read()).get("service") != "ocr":
                _OCR_CACHE[page] = ""
                return None
    except Exception:
        _OCR_CACHE[page] = ""
        return None

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
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            submit = json.loads(r.read())
        image_id = submit.get("image_id")
        if not image_id:
            _OCR_CACHE[page] = ""
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
                _OCR_CACHE[page] = ""
                return None
        else:
            _OCR_CACHE[page] = ""
            return None
    except Exception:
        _OCR_CACHE[page] = ""
        return None

    result_view = view.get("result") or {}
    md_text = result_view.get("markdown") or ""
    if not md_text:
        md_text = (
            ((result_view.get("json") or {}).get("result") or {}).get("layoutParsingResults")
            or [{}]
        )[0].get("markdown", {}).get("text", "")
    if not md_text:
        _OCR_CACHE[page] = ""
        return None
    _OCR_CACHE[page] = md_text
    _ocr_cache_write(page, store, md_text)
    return md_text




def ocr_trim_continuation(
    page: int, continuation: list[str], store: kangxi_store.KangxiStore
) -> tuple[list[str], str]:
    """用 PaddleOCR 基线服务把续文裁剪到页面物理范围（删头去尾）。

    文本始终以库内转写为准，OCR 只作范围标尺（全量测试：21 页 micro-CER
    5.65%；干净链路 @332→333 裁剪与人工初校差 1 字）。服务不可用或对齐
    不可信时原样返回并说明（回退全量灌入）。
    """
    md_text = _ocr_markdown(page, store)
    if md_text is None:
        return continuation, "OCR 不可用，未裁剪"

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


def ocr_fold_page_lines(page: int, bands: list[list[str]], store: kangxi_store.KangxiStore) -> tuple[list[list[str]], str]:
    """按 OCR 行组在草稿大行内插入折行（小行换行）。

    行组界即物理行界：25 页初校真值对照（2026-11-14）组界 91.5% 为真行界，
    短行组（书名堆叠「廣韻集/韻韻會」逐行、短行接书证）同样是真实断行，
    不做短片段合并（原 <8 合并规则误删 63% 真界，详见下方实测注释）。
    安全性：只插入换行、不改任何字符——最坏情况折点偏移 1-2 字或过分裂
    多折一处，对照页中即刻可见、拖动即可；库内转写文本永不因折行改动。
    """
    md_text = _ocr_markdown(page, store)
    if md_text is None:
        return bands, "OCR 不可用，未折行"
    groups = [g.replace("\n", "") for g in md_text.split("\n\n") if g.strip()]
    if len(groups) < 2:
        return bands, "OCR 行组不足，未折行"
    ocr_n = _norm("".join(groups))
    if not ocr_n:
        return bands, "OCR 无文本，未折行"

    # 全页草稿文本（按 band 拼接）与 OCR 对齐；fold 边界 = OCR 组界映射到草稿。
    # 输入大行先压平：旧折行换行不再泄漏进新片段（重折幂等；含 // 注释行的
    # 大行保持原样——行内注释截断语义不能被并入单行）
    def _flatten(band: list[str]) -> str:
        if any("//" in l for l in band):
            return "\n".join(band)
        return "".join(l.strip() for l in band)

    full = "\u0001".join(_flatten(b) for b in bands)
    full_n = _norm(full)
    sm = difflib.SequenceMatcher(None, full_n, ocr_n, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
    cover = sum(b.size for b in blocks)
    if cover < len(ocr_n) * 0.5 or cover < len(full_n) * 0.5:
        return bands, f"OCR 与草稿对齐不可信（{cover} 字匹配），未折行"

    # OCR 组界（归一化偏移）→ 草稿归一化坐标（经匹配块反向映射）
    ocr_off, acc = [], 0
    for g in groups[:-1]:
        acc += len(_norm(g))
        ocr_off.append(acc)
    full_positions = []
    for o in ocr_off:
        pos = None
        for b in blocks:
            if b.b <= o <= b.b + b.size:
                pos = b.a + (o - b.b)
                break
        if pos is not None:
            full_positions.append(pos)
    if not full_positions:
        return bands, "OCR 组界无法映射，未折行"

    # 不做短片段合并。原 <8 合并规则的实测（25 页初校真值对照，2026-11-14）：
    # 被删组界 213 个中 135 个（63%）是真行界——书名堆叠（廣韻集/韻韻會逐行）、
    # 短行接书证（。【說文】|）等都是真实物理短行；真正的过分裂集中在个别页
    # （@320 样式）。OCR-VL 行组本身 91.5% 可信，过分裂折点保留在稿中可见即删
    # （本函数只插换行、永不改字，误折删除无风险，漏折补行才是隐性成本）。
    merged = full_positions

    buf_lines: list[str] = []
    kept = 0
    cut_set = set()
    pos_in_full = 0
    # 重新走 full 原文（含 \u0001 与换行），把 merged 折点（归一化序号）转为原文切点
    norm_idx = 0
    pieces: list[str] = []
    last = 0
    cut_norm = sorted(merged)
    ci = 0
    for i, ch in enumerate(full):
        if ch in PUNCT_STRIP:
            continue
        if ci < len(cut_norm) and norm_idx == cut_norm[ci]:
            # 括号贴字：归一化剥掉【】，切点可能落在书名号内侧。判定须越过剥离带
            # （句读/空格/旧折行换行）扫描：带内含【则 cut 移到最左【之前（开书名
            # 号随下文起行），带内含】则 cut 移到最右】之后（闭书名号随上文收尾）；
            # 只有书名号触发移动，普通句读仍留行尾。j 走剥离字符，不越 \u0001 带界。
            cut = i
            j = cut
            while j < len(full) and full[j] in PUNCT_STRIP and full[j] != "【":
                if full[j] == "】":
                    cut = j + 1
                j += 1
            j = cut
            while j > last and full[j - 1] in PUNCT_STRIP:
                if full[j - 1] == "【":
                    cut = j - 1
                j -= 1
            pieces.append(full[last:cut])
            last = cut
            ci += 1
        norm_idx += 1
    pieces.append(full[last:])
    if len(pieces) <= 1:
        return bands, "折点未落在草稿内，未折行"
    # pieces 按原文切分；把 \u0001 分隔的 band 重组
    flat = "\n".join(pieces)
    result = [b.split("\n") for b in flat.split("\u0001")]
    inserted = len(pieces) - 1
    return result, f"OCR 折行：插入 {inserted} 处换行"


def build_draft_gj(
    page: int,
    store: kangxi_store.KangxiStore,
    continuation: list[str] | None = None,
    skip_head: str | None = None,
    fold: bool = True,
) -> tuple[str, dict]:
    """由库内 page_chars + entries 生成 .gj 草稿与统计。

    continuation 为前页未完字头的续文行（置于新字头之前，符合阅读顺序）；
    skip_head 防重复收录延续字头（站点 page_chars 通常不标延续，此为保险）。
    fold=True 且 OCR 服务可用时，按 OCR 行组在大行内插入折行（只插入换行
    不改字符；不可用/不可信时草稿为未折行的平铺段——校对者回退到手工折行）。
    """
    chars = store.get_page_chars(page)
    if not chars and not continuation:
        raise RuntimeError(
            f"页 {page} 无字头索引（page_chars 为空）且无前页续文——"
            "阅读页数据不完整或该页既无新字头也无延续内容"
        )

    bands: list[list[str]] = []  # 每项 = 一个大行（未折行时单元素）
    counts = {"chars": 0, "unencoded": 0, "with_text": 0}
    notes: list[str] = []
    if continuation:
        for para in continuation:
            bands.append([para])
        counts["with_text"] += 1  # 续文计入有释文字头
    for item in chars:
        if skip_head and item["char"] == skip_head:
            counts["skipped_dup"] = counts.get("skipped_dup", 0) + 1
            continue
        if item["char"]:
            bands.append([f"#{item['char']}"])
            counts["chars"] += 1
            entry = store.get_entry(item["codepoint"])
            if entry:
                record = json.loads(entry["record_json"])
                paragraphs = [p for p in record.get("text_paragraphs") or [] if p.strip()]
                if paragraphs:
                    counts["with_text"] += 1
                    bands.extend([p] for p in paragraphs)
        else:
            k = item.get("k_code") or item.get("svg", "?")
            bands.append(["#□"])
            bands.append([f"// 未编码字（{k}）：站点无 Unicode 映射，请对照原图补录"])
            counts["unencoded"] += 1

    if fold:
        bands, note = ocr_fold_page_lines(page, bands, store)
        notes.append(note)

    parts = [
        f"// 草稿：kangxizidian.com 爬取生成 {date.today()}，未经人工校对（状态：草稿）",
        "",  # 注释与 @页码 之间必须空行，否则并入同一大行致页声明不解析
        f"@{page}",
    ]
    for band in bands:
        parts.append("")
        parts.extend(band)
    counts["ocr_notes"] = notes
    return "\n".join(parts) + "\n", counts


def cmd_ocr_fold(page: int, fold: bool = True) -> dict:
    """对已入库页的 .gj 执行 OCR 折行（用户在编辑器工具栏手动触发）。

    读取该页 .gj 的现有大行结构，按 OCR 行组插入换行——只插入换行、不改字符；
    页面已有折行会被先去掉再按 OCR 重折（幂等）。写回 .gj 并刷新 json/txt。
    """
    gj_path = ANNOTATIONS / f"{page:04d}.gj"
    if not gj_path.exists():
        raise RuntimeError(f"页 {page} 不在数据集中")
    store = kangxi_store.KangxiStore()
    raw = gj_path.read_text(encoding="utf-8")

    # 保留头部（注释 + @页码 行）与正文大行
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

    folded, note = ocr_fold_page_lines(page, bands, store)
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

    # 同步 json/txt（build 的运行时断言管 IR 口径）
    import subprocess as sp

    r = sp.run(
        ["npx", "-y", "tsx", str(REPO / "kangxi-gold/scripts/build_annotations.ts"), "--allow-drift"],
        capture_output=True, text=True, timeout=900,
        cwd=str(REPO),
    )
    if r.returncode != 0:
        raise RuntimeError(f"build 同步失败：{r.stderr[-300:]}")
    return {"ok": True, "page": page, "note": note, "changed": True}


def cmd_ocr_view(page: int) -> dict:
    """返回该页的 OCR markdown（供前端弹窗展示）。"""
    store = kangxi_store.KangxiStore()
    img, sha = _scan_for(page, store)
    if img is None or not sha:
        raise RuntimeError(f"页 {page} 无扫描图（crawl store 与数据集清单均未登记）")
    entry = _ocr_cache_read(page, store)
    if entry is None:
        entry = _ocr_markdown(page, store)
    if entry is None:
        return {"ok": True, "page": page, "markdown": None,
                "hint": "OCR 缓存未命中且服务未运行——先跑 scripts/prefetch_ocr.py 或启动服务"}
    return {"ok": True, "page": page, "markdown": entry}


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


def prefetch_next_page(page: int) -> None:
    """后台预取 page+1：爬取（阅读页+图）→ OCR → 持久缓存。

    添加第 n 页后自动调用，用户校对完第 n 页再添加 n+1 时 OCR 已就绪。
    全部静默：失败只写日志文件不影响 add 结果；进程退出前等待完成（最长
    ~10 分钟），add 本身的返回不被拖延。
    """
    import logging

    nxt = page + 1
    if not 1 <= nxt <= 7738:
        return
    log_path = REPO / "paddleocr-baseline" / "data" / "ocr-markdown" / "prefetch.log"
    logging.basicConfig(
        filename=log_path, filemode="a", level=logging.INFO,
        format="%(asctime)s %(message)s",
    )
    try:
        # ① 爬取（库里有则零网络；fetch 脚本自带 robots/限速/重试）
        fetch = subprocess.run(
            [sys.executable, str(SCRIPTS / "fetch_kangxi_page.py"), "--pages", str(nxt)],
            capture_output=True, text=True, timeout=600,
        )
        if fetch.returncode != 0:
            logging.info(f"@{nxt} fetch 退出码 {fetch.returncode}: {fetch.stderr[-200:]}")
            return
        # ② 字头详情（增量；page_chars 为空时 skip）
        store = kangxi_store.KangxiStore()
        chars = store.get_page_chars(nxt)
        missing = [c["char"] for c in chars if c["char"] and store.get_entry(c["codepoint"]) is None]
        if missing:
            e = subprocess.run(
                [sys.executable, str(SCRIPTS / "fetch_kangxi_entry.py"), "--pages", str(nxt)],
                capture_output=True, text=True, timeout=900,
            )
            if e.returncode != 0:
                logging.info(f"@{nxt} entry 退出码 {e.returncode}: {e.stderr[-200:]}")
        # ③ OCR 预取（服务可用才跑；缓存命中则秒过）
        pre = subprocess.run(
            [sys.executable, str(SCRIPTS / "prefetch_ocr.py"), "--pages", str(nxt), "--limit", "1"],
            capture_output=True, text=True, timeout=900,
        )
        logging.info(f"@{nxt} prefetch 完成: {pre.stdout.strip().splitlines()[-1] if pre.stdout.strip() else pre.stderr[-200:]}")
    except Exception as e:  # noqa: BLE001 —— 预取绝不影响 add
        logging.info(f"@{nxt} prefetch 异常: {e}")


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
    write_index(manifest)

    # 后台预取 n+1（爬取+OCR+缓存）；不阻塞返回，进程退出前自然等待完成
    import threading

    t = threading.Thread(target=prefetch_next_page, args=(page,), daemon=True)
    t.start()
    _PREFETCH_THREADS.append(t)

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
    f = sub.add_parser("ocr-fold")
    f.add_argument("--page", type=int, required=True)
    v = sub.add_parser("ocr-view")
    v.add_argument("--page", type=int, required=True)
    args = ap.parse_args()

    try:
        if args.cmd == "add":
            result = cmd_add(args.page)
        elif args.cmd == "ocr-fold":
            result = cmd_ocr_fold(args.page)
        elif args.cmd == "ocr-view":
            result = cmd_ocr_view(args.page)
        else:
            result = cmd_status(args.page, args.to)
        print(json.dumps(result, ensure_ascii=False))
        # add 触发的后台预取（爬取+OCR）在此等待完成（不拖慢上面的结果输出）
        for t in _PREFETCH_THREADS:
            t.join()
        return 0
    except Exception as e:  # noqa: BLE001 —— 桥接给 HTTP 层
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
