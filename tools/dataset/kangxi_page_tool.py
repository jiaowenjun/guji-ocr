#!/usr/bin/env python3
"""数据集对照页「添加新页」的桥接工具：补爬数据 → 生成 .gj 草稿 → 更新金标清单。

数据优先级（不重复爬虫）：kangxi-crawl.sqlite3 已有的页数据/字头详情直接用；
缺什么由 scripts/fetch_kangxi_page.py / fetch_kangxi_entry.py 增量补抓
（两者自身即「库里有则零网络请求」，页码页 2 个请求、字头详情每字 1 个请求）。

动作：
  add --page N          补数据 → 生成 kangxi-gold/annotations/NNNN.gj 草稿
                        （字头行 + 释义段落带；未编码字形按全库实测语义归并：
                        K 码＝前字头古文变体——guwen 数量精确匹配时并入字头行
                        「#头古文#A#B」，不匹配时 #□ 占位紧跟主字头；2 段名伴随
                        字形只留注释；OCR 标尺把溢出到下页的尾段裁掉，下页添加
                        时自动续入）→ 回补本页未编码字形 svg 缓存 →
                        manifest.json 追加该页（status=draft）→ 重写
                        guji-preview-grid/public/dataset/index.json
                        → 后台预取 N+1（独立进程 prefetch-run，不阻塞 add 退出）
  status --page N --to draft|first|final
                        改页标签（草稿/初校/精校）并同步 manifest 与 index.json
  ocr-pages             各页 OCR/预取浅状态清单（预取调试视图数据源）：
                        数据集页 ∪ 已爬页 ∪ OCR 缓存页，每页含采集完整度、
                        OCR 缓存三态（valid/stale/none）与元数据
  prefetch-status --page N
                        单页预取四步深查（只读现状，不抓取）：爬取/字头详情/
                        OCR/svg 存在性
  prefetch-run --page N
                        手动执行单页预取链路（同 add 后台预取的四步，同步等待；
                        未爬页会联网爬取）——独立验证 prefetch_next_page 行为
  prefetch-log --tail 50
                        var/ocr-cache/prefetch.log 尾部行（时间线展示）

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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "crawl"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kangxi_store  # noqa: E402
import paths  # noqa: E402

HERE = Path(__file__).resolve().parent          # tools/dataset
CRAWL = HERE.parent / "crawl"
EVAL = HERE.parent / "eval"
REPO = HERE.parents[1]
MANIFEST = REPO / "kangxi-gold" / "manifest.json"
ANNOTATIONS = REPO / "kangxi-gold" / "annotations"
INDEX_JSON = REPO / "guji-preview-grid" / "public" / "dataset" / "index.json"

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


def run_fetch(script: str, page: int, label: str) -> str:
    """复用既有爬取 CLI 增量补数据（库里有则零网络）。

    末行是全库 stats JSON（两个 fetch 脚本打印同一份），原样入 summaries 会让
    前端状态栏出现两段重复长 JSON——转为一句带 label 的人话摘要。
    """
    r = subprocess.run(
        [sys.executable, str(CRAWL / script), "--pages", str(page)],
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
        """在单页文本中找最后一个有库内详情的主字头；返回 (head, entry, tail_raw)。

        字头行的两种实存格式都要认（@313–336 实测混用）：
          行内式 #(注)#頭古文#變1#變2（如 @331「#(三)#中古文#𠁧#𠁩」）
          独占式 #頭古文 一行、变体各自成 #行（如 @313 丁/𠆤）
        糖写法（2026-11-14 语法扩展）同样要认：簇内 token 的 # 可省——
          #(三)丹，古文：𠁿㣋 / #(五)(增)𠂂。圈注前缀随字头一并匹配
          （#(?:圈)*頭）；裸字变体不产生 # 标记，天然不是宿主候选。
        古文变体不是宿主候选（@331 #𠁩 自带详情曾被误选为宿主致锚定失败）：
        上一标记到本标记之间只有「古文」或空白（变体链）即判变体；紧贴本
        字头的 #(注) 前缀（(增)/(二)/(三)…）先剥掉再判。
        """
        _circ = r"\([^)#\n]{1,2}\)?"
        marks = list(re.finditer(rf"#(?:{_circ})*([^#(\s【□])", raw_text))
        heads: list[tuple[str, int]] = []  # (主字头, 尾部起点)
        guwen_open = False  # 上一主字头带「古文」，紧随的 # 段是变体链
        for i, m in enumerate(marks):
            seg = raw_text[marks[i - 1].end() if i else 0: m.start()]
            seg = re.sub(r"\s*#\([^)]*\)\s*$", "", seg)  # 剥紧贴的 #(注)
            seg_cmp = re.sub(r"\s+", "", seg)  # 竖排会把「古文」拆成两行（@320 不）
            if guwen_open and re.fullmatch(r"[、，,]*", seg_cmp):
                continue  # 变体链上的 #段（#𠁧#𠁩 / #𠀚、#𠙐 / 独占式 #𠆤 行）
            if re.fullmatch(r"古文[：:]?", seg_cmp):
                guwen_open = True
                continue  # 「#頭古文(：)」后的首个变体
            # 糖写法标记可带「，」前缀（#(三)丹，古文：…）
            guwen_open = re.match(r"[，\s]*古文", raw_text[m.end():]) is not None
            heads.append((m.group(1), m.end()))
        for cand, end in reversed(heads):
            e = store.get_entry(ord(cand)) if len(cand) == 1 else None
            if e is not None:
                return cand, e, raw_text[end:]
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
    # 剥离尾部的「古文#变体…」前缀：变体字头是词条页元数据，不在释义段文本内。
    # 兼容实存格式全家（@312–336 实测）：行内 顿号分隔（古文#丄、#𠄞）、
    # 冒号（古文：#𠀇、#𠀃）、变体独占成行（古文\n#𠆤）、竖排把「古文」
    # 拆成两行（古\n文\n#𠀚、#𠙐）——旧正则逐一失配致锚定失败。
    # 糖写法（2026-11-14）：标记前可带「，」、变体的 # 可省（，古文：𠁿㣋）。
    # 裸字变体须紧跟非空白（同行紧贴，不跨行）——与释义首字区分；# 式变体
    # 仍可跨行（古文\n#𠆤）；变体字符类排除句读（，。）防误吞释义
    tail_raw = re.sub(
        r"^[，\s]*古\s*文[\s：:、，,]*"
        r"(?:#[^#\s【(，。][\s：:、，,]*|(?<=\S)[^#\s【(，。][：:、，]*){1,6}",
        "",
        tail_raw,
    )
    # 剥离注释行（伴随字形/归并来源等工具注释不是页面文本，混进尾部会让
    # 锚点在库内段落中找不到起点——@340 读 @339 丹条尾巴实测踩坑）
    tail_raw = "\n".join(
        l for l in tail_raw.splitlines() if l.strip() and not l.strip().startswith("//")
    )
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
            f"（前页添加时 OCR 不可用未做页尾裁剪）——请先在校对中把前页裁剪到"
            f"其物理页界，再添加本页，余段将自动续入"
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
_OCR_CACHE_DIR = paths.OCR_CACHE_DIR


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


def _ocr_cache_meta(page: int, cur_sha: str) -> dict:
    """缓存三态与元数据（预取调试视图）：state ∈ valid|stale|none。

    判据同 _ocr_cache_read（sha256 与当前图一致才 valid）；markdown 本身
    不返回（体积），详情展示走 ocr-view。
    """
    f = paths.OCR_CACHE_DIR / f"{page:04d}.json"
    if not f.exists():
        return {"state": "none", "fetched_at": None, "chars": 0}
    try:
        entry = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"state": "none", "fetched_at": None, "chars": 0}
    state = "valid" if (entry.get("sha256") and cur_sha and entry["sha256"] == cur_sha) else "stale"
    return {
        "state": state,
        "fetched_at": entry.get("fetched_at"),
        "chars": len(entry.get("markdown") or ""),
    }


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


def ocr_page_cut(
    page: int, text: str, store: kangxi_store.KangxiStore, full_page: bool = False
) -> tuple[int | None, int, str]:
    """OCR 对齐求本页物理末界：返回 (裁点, 候选归一化长度, 说明)。

    裁点是候选文本归一化坐标里页面的最后一字位置；None = 不可信/不可用，
    调用方不应裁剪。文本始终以库内转写为准，OCR 只作范围标尺（全量测试：
    21 页 micro-CER 5.65%；干净链路 @332→333 裁剪与人工初校差 1 字）。
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
    md_text = _ocr_markdown(page, store)
    cand_n = _norm(text)
    if md_text is None:
        return None, len(cand_n), "OCR 不可用"
    ocr_n = _norm("".join(_ocr_groups(md_text)))
    if not ocr_n:
        return None, len(cand_n), "OCR 无文本输出"
    if not cand_n:
        return None, 0, "候选文本为空"
    sm = difflib.SequenceMatcher(None, cand_n, ocr_n, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
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
        return None, len(cand_n), "对齐不可信（末段匹配稀疏）"
    if end < end0:
        why_tail = f"，末段判信回缩 {end0 - end} 字"
    # 门槛按「裁点前区域」判信而非 OCR 全长：页面含新字头时匹配数天然小于
    # OCR 全文（334：候选末段 375 字，页面上只有前 ~79 字）。要求裁点区域
    # 至少 20 字且其中过半是真实匹配（连续性证据），否则放弃裁剪回退全量
    if end < 20:
        return None, len(cand_n), f"对齐不可信（裁点 {end} 字过短）"
    span = len(ocr_n) if full_page else end
    if cover < span * 0.5:
        return None, len(cand_n), f"对齐不可信（页面 {span} 字中匹配 {cover}）"
    return end, len(cand_n), why_tail


def _cut_mapped(paragraphs: list[str], end: int) -> list[str]:
    """归一化裁点 end 映射回段落列表：裁点前整段全留，裁点所在段取前半。"""
    kept = 0
    cut_para, cut_idx = len(paragraphs) - 1, len(paragraphs[-1])
    for pi, para in enumerate(paragraphs):
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
    trimmed = list(paragraphs[:cut_para])  # 裁点前的整段全部保留
    if cut_idx > 0:
        trimmed.append(paragraphs[cut_para][:cut_idx].rstrip())  # 裁点所在段取前半
    return trimmed


def ocr_trim_to_page(
    page: int, paragraphs: list[str], store: kangxi_store.KangxiStore, what: str = "续文"
) -> tuple[list[str], str]:
    """把段落列表裁剪到本页物理范围（删尾）。

    裁掉的内容物理上属于后续页，无需保留——库内词条是全量转写，添加后续页
    时 continuation_from_prev 自动从库内补回余段。对齐不可信时原样返回并
    说明（回退全量灌入）。
    """
    text = "\n".join(paragraphs)
    end, total, why = ocr_page_cut(page, text, store)
    if end is None:
        return paragraphs, f"{what}未裁剪：{why}"
    if end >= total:
        return paragraphs, f"{what}已在页面范围内，无需裁剪{why}"
    trimmed = _cut_mapped(paragraphs, end)
    return trimmed, (
        f"OCR 裁剪：保留 {end}/{total} 字（页面物理末界{why}），溢出 {total - end} 字留给下页"
    )


def ocr_trim_continuation(
    page: int, continuation: list[str], store: kangxi_store.KangxiStore
) -> tuple[list[str], str]:
    """(兼容旧名) 把前页续文裁剪到页面物理范围（删尾）。"""
    return ocr_trim_to_page(page, continuation, store, what="续文")


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
    groups = _ocr_groups(md_text)
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
        # 只剥半角空白：全角空格 U+3000 是内容字符（空字格 ≡*），
        # @312 老样式行尾「入聲。　/【說文】」经 strip 丢字实测（331→330）
        return "".join(l.strip(" \t") for l in band)

    full = "\u0001".join(_flatten(b) for b in bands)
    # 结构大行（字头行 # / 注释行 //）不可被折行打断：折点落其内则整点丢弃
    # ——少折一处可见可补，拆断字头行/注释行则破坏语义（@339 丹字头行实测
    # 被 OCR 变体字形组界拆成 #\n丹\n古文\n#𠁿#㣋#𠕑）。字头簇在页面上是
    # 一列，人工校对惯例也是整行不折。
    # 行级保护（与分带布局无关）：任何 # / // 起始的行保护其自身跨度。
    # 旧的「带首行 # → 整带保护」对分带布局敏感——同一字符内容在
    # 「字头行居带中」时无保护（一击拆成 #丁/古文/#𠆤…），regroup 把
    # 字头行挪到带首后又有保护（二击并回）→ 按钮不幂等、行数逐击递减
    # （@313 实测 17→15；全库 12/28 页不收敛）。
    structural: list[tuple[int, int]] = []
    _pos = 0
    for b in bands:
        _fb = _flatten(b)
        _has_comment = any("//" in l for l in b)
        _off = 0
        for l in b:
            _ls = l.lstrip(" \t")
            if _ls.startswith("#") or _ls.startswith("//"):
                structural.append((_pos + _off, _pos + _off + len(_ls)))
            _off += len(_ls) + (1 if _has_comment else 0)
        _pos += len(_fb) + 1  # \u0001 分隔符

    def _structural_at(i: int) -> bool:
        # 只挡结构行内部（s < i < e）：i == s（头的首字符）放行——把字头行
        # 与前行分开不破坏头本身；若连起点都挡，字头行会与前行融合成
        # 「…正文。#丁古文」，该行不再以 # 起始 → 下一击失去保护被拆开
        # → 周期 2 振荡（@313 实测 16→18→16 行）。
        return any(s < i < e for s, e in structural)

    # 对齐空间剔除 \u0001 带界符：它永远匹配不上 OCR 文本，只会把匹配块
    # 打碎；且其数量随分带布局变化（regroup 后带界移动）→ 同一字符内容
    # 的折点映射随布局漂移 → 按钮不幂等（@313 实测周期 2 摆动 16→18→16）。
    # 下方折点游标同样跳过 \u0001 不计数。
    full_n = "".join(ch for ch in full if ch not in PUNCT_STRIP and ch != "\u0001")
    sm = difflib.SequenceMatcher(None, full_n, ocr_n, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
    cover = sum(b.size for b in blocks)
    # 判信两侧过半。重尾溢出页（全量词条未裁/裁剪回退）full_n 远大于页面，
    # 草稿侧按「页内可比长度」衡量（取两者较小者），页面侧仍须过半——
    # 否则 @334 类页面（候选 961 字仅 ~270 字在页）永远折不了行
    if cover < len(ocr_n) * 0.5 or cover < min(len(full_n), len(ocr_n)) * 0.5:
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
    # 重新走 full 原文（含 \u0001 与换行），把 merged 折点（归一化序号）转为原文切点。
    # 折点先去重：OCR 侧相邻组界间有误读缺口（b 侧 gap）而草稿侧连续（a 侧
    # 相邻块）时，两个组界经匹配块反向映射坍缩到同一位点（@334 实测 24 个
    # 映射组界含 2 组重复）——下方等值游标在重复位点后永不前进，其后折点
    # 全部静默丢失（整页只插 2 处、应插 20+，eval_ocr_fold_replay 抓到）
    norm_idx = 0
    pieces: list[str] = []
    last = 0
    cut_norm = sorted(set(merged))
    ci = 0
    for i, ch in enumerate(full):
        if ch in PUNCT_STRIP or ch == "\u0001":
            continue  # \u0001 不计入 norm 序号（对齐空间已剔除，见上）
        if ci < len(cut_norm) and norm_idx == cut_norm[ci]:
            # 结构行内不折（整点丢弃——少折一处可见可补，拆断字头行破坏语义）
            if not _structural_at(i):
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
    # pieces 按原文切分；把 \u0001 分隔的 band 重组。空串带丢弃、带首尾换行
    # 剥离：切点贴带界时 piece 尾部/首部携带裸 \u0001，与 pieces 的 \n 连接
    # 叠加成空行带或带内前导空行（@339 注释带后双空行实测）
    flat = "\n".join(pieces)
    result = [
        b.strip("\n").split("\n")
        for b in flat.split("\u0001")
        if b.strip("\n")
    ]
    inserted = len(pieces) - 1
    return result, f"OCR 折行：插入 {inserted} 处换行"


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
    成带逻辑；旧的「重折个别折点偏移」限制已随 \u0001 对齐剔除消除。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
    import kangxi_column_seg  # noqa: E402

    # // 注释行不参与分配，但必须保留（附着到其前一个正文行所在的大列带）
    # ——早期版本直接丢弃会破坏字符流（草稿 #□ 占位常带 //未编码字 说明）。
    # 部题行（## / ### / 「# 」带空格）永远独立成带且不参与分配：它们不是
    # 列内容，并进大列带后会被下一击 flatten 融合（部题间无 OCR 折点支持，
    # @312 实测「## 子集上### 一部」周期 2 振荡）。
    def _is_section_header(l: str) -> bool:
        ls = l.lstrip(" \t")
        return ls.startswith("##") or ls.startswith("# ")

    body = [l for b in bands for l in b if l.strip()]
    lines = [l for l in body
             if not l.strip().startswith("//") and not _is_section_header(l)]
    if len(lines) < 2:
        return bands, "行数不足，未按大列重组"
    res = kangxi_column_seg.segment(page)
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
            if buf or seen < len(lines):
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
    if len(groups) < 2:
        return bands, "大列分配退化，未重组"
    sizes = ",".join(str(len(g)) for g in groups)
    return groups, f"大列重组：{len(groups)} 带（各行数 {sizes}）"


def _guwen_list(entry) -> list[str]:
    """词条的站点古文变体列表（guwen 字段按「、」分隔）。"""
    if not entry:
        return []
    gw = json.loads(entry["record_json"]).get("guwen")
    return [g for g in (gw or "").split("、") if g]


def _classify_unencoded(chars: list[dict]) -> tuple[dict[int, dict], list[dict]]:
    """把 page_chars 的未编码字形归属到主字头（ord 顺序单遍扫描）。

    全库实测语义（5,143 字形，2026-11-14）：2 段名 svg（k_code 空、无 char）
    7/7 与主字头同 page_seq = 字头旁的伴随字形；K 码字形 226/226 无词条号、
    128/136 簇与前主字头站点 guwen 数量精确一致 = 古文变体（人工先例
    @331/@334：K 码归并为「#头古文#A#B」字头行，伴随字形删除）。
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


def _trim_bands_to_page(
    page: int, bands: list[list[str]], store: kangxi_store.KangxiStore
) -> tuple[list[list[str]], str]:
    """把草稿大行裁剪到本页物理末界（band 感知版 ocr_trim_to_page）。

    注释行不参与对齐（svg 路径等非页面文本会污染归一化候选）。裁点落在
    字头行上时整行保留、其后裁去——末界恰在新字头处的罕见情形，宁少裁
    不误删字头（错留的字头行校对中一眼可见，下页 page_chars 亦会收录）。
    """
    flat = "\n".join(
        line for band in bands for line in band if not line.strip().startswith("//")
    )
    end, total, why = ocr_page_cut(page, flat, store, full_page=True)
    if end is None:
        return bands, (
            f"OCR 尾裁未执行：{why}——本页草稿含全量词条，"
            "添加下页前请先手工裁剪到物理页界"
        )
    if end >= total:
        return bands, "OCR 尾裁：本页内容未溢出页界"
    kept = 0
    cut = None  # (band_idx, line_idx, char_idx)
    for bi, band in enumerate(bands):
        for li, line in enumerate(band):
            if line.strip().startswith("//"):
                continue
            for ci, ch in enumerate(line):
                if ch in PUNCT_STRIP:
                    continue
                if kept == end:
                    cut = (bi, li, ci)
                    break
                kept += 1
            if cut:
                break
        if cut:
            break
    if cut is None:  # 裁点在注释行之间的缝隙：保守不裁
        return bands, "OCR 尾裁：裁点未落定，保守保留全量"
    bi, li, ci = cut
    if bands[bi][li].lstrip().startswith("#"):
        trimmed = [list(b) for b in bands[: bi + 1]]  # 字头行整行保留
    else:
        head_bands = [list(b) for b in bands[:bi]]
        band_cut = list(bands[bi][:li])  # 裁点所在 band 的前行属本页（@338 实测踩坑：
        line_cut = bands[bi][li][:ci].rstrip()  # 裁在大行第二行行首时，首行曾被误丢）
        if line_cut:
            band_cut.append(line_cut)
        if band_cut:
            head_bands.append(band_cut)
        trimmed = head_bands
    return trimmed, (
        f"OCR 尾裁：保留 {end}/{total} 字（页面物理末界{why}），"
        f"溢出 {total - end} 字留给下页自动续入"
    )


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
    未编码字形按 _classify_unencoded 的归属生成：K 码簇与前主字头 guwen 数量
    精确一致时并入字头行（#头古文#A#B），否则 #□ 占位紧跟主字头行；2 段名
    伴随字形只留注释（人工先例是删除）。
    页尾 OCR 裁剪（_trim_bands_to_page）把溢出到下页的尾段裁掉——库内全量
    在，添加下页时自动续入；OCR 不可用时回退全量并在 notes 警告。
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
        entry = store.get_entry(item["codepoint"])
        ex = extra.get(item["ord"]) or {}
        for c in ex.get("companions") or []:
            bands.append([f"// 站点伴随字形（{c['svg']}）：非词条，确认后删除本行"])
            counts["companions"] = counts.get("companions", 0) + 1
        kcodes = ex.get("kcodes") or []
        if kcodes:
            gw = _guwen_list(entry)
            if len(gw) == len(kcodes):
                # 数量精确匹配才归并（128/136 簇）；字头行同人工校对风格
                head_band[0] = f"#{item['char']}古文" + "".join(f"#{g}" for g in gw)
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
        if entry:
            record = json.loads(entry["record_json"])
            paragraphs = [p for p in record.get("text_paragraphs") or [] if p.strip()]
            if paragraphs:
                counts["with_text"] += 1
                bands.extend([p] for p in paragraphs)
    for item in orphans:
        k = f"{item.get('k_code') or '？'}，{item['svg']}"
        bands.append(["#□"])
        bands.append([f"// 未编码字（{k}）：本页无前邻主字头，请对照原图补录"])
        counts["unencoded"] += 1

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
                "hint": "OCR 缓存未命中且服务未运行——先跑 tools/eval/prefetch_ocr.py 或启动服务"}
    return {"ok": True, "page": page, "markdown": entry}


def cmd_ocr_pages() -> dict:
    """各页 OCR/预取浅状态清单（预取调试视图数据源）。

    页集合 = 数据集页 ∪ 库内已爬页 ∪ OCR 缓存页。每页不含 markdown 本身
    （体积控制，详情走 ocr-view / prefetch-status）。当前图 sha 库内优先，
    未爬但有缓存的页回退 manifest（同 _scan_for 口径）。
    """
    store = kangxi_store.KangxiStore()
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
    """单页预取四步深查（只读现状，不执行任何抓取）。

    四步与 _prefetch_pipeline 一一对应：fetch（阅读页+原图）/ entries
    （字头详情）/ ocr（缓存三态）/ svg（未编码字形 svg 存在性——与回补
    scope 同口径，只查 codepoint 为空者）。
    """
    store = kangxi_store.KangxiStore()
    row = store.get_page(page) or {}
    missing = store.page_missing(page, ("reading", "scan"))
    chars = store.get_page_chars(page)
    miss_entries = store.coded_chars_missing_entries(page)
    cur_sha = row.get("scan_sha256") or ""
    if not cur_sha:
        for e in load_manifest().get("pages", []):
            if e["page"] == page:
                cur_sha = e.get("sha256") or ""
                break
    ocr = _ocr_cache_meta(page, cur_sha)
    wanted = [c["svg"] for c in chars if c["codepoint"] is None and c.get("svg")]
    have = sum(1 for rel in wanted if (paths.RAW_KANGXI_SVG / rel).is_file())
    ocr_detail = {
        "valid": f"缓存有效（{ocr['chars']} 字，{ocr['fetched_at']}）",
        "stale": f"缓存失效（图已变或无图可比对，{ocr['chars']} 字）",
        "none": "无 OCR 缓存（需预取或启动服务现算）",
    }[ocr["state"]]
    return {
        "ok": True,
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
    }


def cmd_prefetch_run(page: int) -> dict:
    """手动执行单页预取链路（同 add 后台预取的四步，同步等待完成）。

    调试用：不依赖真实 add 即可验证 prefetch_next_page 行为。未爬页会
    联网爬取（fetch 自带限速），OCR 需本地服务在线。
    """
    if not 1 <= page <= 7738:
        raise RuntimeError(f"页码 {page} 超出站点范围 1-7738")
    steps = _prefetch_pipeline(page)
    return {"ok": all(s["ok"] for s in steps), "page": page, "steps": steps}


def cmd_prefetch_log(tail_n: int = 50) -> dict:
    """prefetch.log 尾部行（时间线展示）。"""
    f = paths.OCR_CACHE_DIR / "prefetch.log"
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines() if f.exists() else []
    return {"ok": True, "total": len(lines), "lines": lines[-tail_n:]}


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
                done("entries", True, f"补抓 {len(missing)} 个字头详情，余缺 {len(rest)}")
        else:
            done("entries", True, "字头详情齐全（或该页无字头）")
        # ③ OCR 预取（服务可用才跑；缓存命中则秒过）
        pre = subprocess.run(
            [sys.executable, str(EVAL / "prefetch_ocr.py"), "--pages", str(nxt), "--limit", "1"],
            capture_output=True, text=True, timeout=900,
        )
        last = pre.stdout.strip().splitlines()[-1] if pre.stdout.strip() else pre.stderr[-200:]
        logging.info(f"@{nxt} prefetch 完成: {last}")
        done("ocr", pre.returncode == 0, last)
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
    chars = store.get_page_chars(page)
    missing_entries = [
        c["char"] for c in chars
        if c["char"] and store.get_entry(c["codepoint"]) is None
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
    _log_ts(f"草稿+manifest+index 写盘完成（{gj_path.name}）")

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
    sub.add_parser("ocr-pages")
    ps = sub.add_parser("prefetch-status")
    ps.add_argument("--page", type=int, required=True)
    pr = sub.add_parser("prefetch-run")
    pr.add_argument("--page", type=int, required=True)
    pl = sub.add_parser("prefetch-log")
    pl.add_argument("--tail", type=int, default=50)
    args = ap.parse_args()

    try:
        if args.cmd == "add":
            result = cmd_add(args.page)
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
