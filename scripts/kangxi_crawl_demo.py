#!/usr/bin/env python3
"""康熙字典爬取功能演示服务器：网页展示「按页抓原图 + 按字头抓全文详情」。

复用同目录爬虫原语与存储层，不重复实现爬取礼仪：
- fetch_kangxi_page.py：阅读页解析（extract_scan_url）、JPEG 校验
- fetch_kangxi_entry.py：字头详情解析（parse_detail）、robots 核查
- kangxi_store.py：SQLite 存储（原始 HTML/记录/页→字头索引），字段级去重，
  库中已有数据零网络请求，磁盘旧缓存自动采纳

流程：浏览器输入页码 → GET /api/page/N（缺什么补什么：阅读页 HTML/原图，
入库后展示）→ <img> 经 /api/scan/N 展示原图 → 点字头 → GET /api/entry/{字}
（库命中或抓取详情页入库）；每次请求的轨迹（数据库命中/采纳/下载）返回前端展示。

用法：
  python3 kangxi_crawl_demo.py [--port 8318] [--cache datasets/kangxi-demo-cache] [--db PATH]
然后浏览器打开 http://127.0.0.1:8318/ 。仅依赖标准库。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_kangxi_entry as fe  # noqa: E402
import fetch_kangxi_page as fp  # noqa: E402
import kangxi_store  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = REPO_ROOT / "datasets" / "kangxi-demo-cache"
THUMB_URL_PREFIX = "https://www.kangxizidian.com/kxzt/0000s/"
NET_LOCK = threading.Lock()  # 串行化网络请求，保持限速礼仪

PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<title>康熙字典爬取演示 · guji-ocr</title>
<style>
  :root {
    --paper: #f6f1e4; --card: #fffdf6; --line: #d9cba8; --ink: #3b3226;
    --accent: #8b2f2f; --tan: #daba94; --pale: #fef2e3; --ok: #4a7c3f;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--paper); color: var(--ink);
    font-family: "Songti SC", "Noto Serif CJK SC", "Microsoft YaHei", serif;
  }
  header { padding: 14px 22px; border-bottom: 2px solid var(--line);
    background: linear-gradient(#fffdf6, #f9f4e6); }
  header h1 { font-size: 19px; letter-spacing: 2px; }
  header h1 b { color: var(--accent); }
  header p { font-size: 12px; color: #7a6f5c; margin-top: 4px; }
  .controls { display: flex; gap: 10px; align-items: center; padding: 12px 22px; flex-wrap: wrap; }
  input[type=text] { width: 110px; padding: 6px 10px; font-size: 15px;
    border: 1px solid var(--line); border-radius: 6px; background: var(--card); }
  button { padding: 6px 16px; font-size: 14px; cursor: pointer; border-radius: 6px;
    border: 1px solid var(--accent); background: var(--accent); color: #fff; }
  button.ghost { background: var(--card); color: var(--accent); }
  button:disabled { opacity: .45; cursor: wait; }
  .hint { font-size: 12px; color: #7a6f5c; }
  main { display: flex; gap: 16px; padding: 0 22px 16px; align-items: flex-start; }
  #scanPane { flex: 1 1 58%; min-width: 0; }
  #rightPane { flex: 1 1 42%; min-width: 380px; display: flex; flex-direction: column; gap: 12px; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
    box-shadow: 2px 2px 6px #0001; padding: 14px 16px; }
  .card h2 { font-size: 14px; color: var(--accent); letter-spacing: 1px; margin-bottom: 10px; }
  #scanImg { width: 100%; border-radius: 8px; border: 3px solid #6666; display: block; }
  #scanMeta { font-size: 12px; color: #7a6f5c; margin-top: 8px; line-height: 1.7; }
  #thumbs { display: flex; flex-wrap: wrap; gap: 8px; }
  .chip { display: flex; flex-direction: column; align-items: center; gap: 2px;
    border: 2px solid var(--tan); border-radius: 8px; background: var(--pale);
    padding: 5px 7px 3px; cursor: pointer; width: 86px; }
  .chip:hover { border-color: var(--accent); }
  .chip.sel { border-color: var(--accent); background: #fdeede; }
  .chip img { width: 56px; height: 56px; border-radius: 5px; background: var(--tan); }
  .chip .no { font-size: 10px; color: #8a7c62; font-family: monospace; }
  .chip.k { opacity: .75; cursor: not-allowed; }
  .badge { font-size: 10px; color: var(--accent); border: 1px solid var(--accent);
    border-radius: 4px; padding: 0 4px; }
  #detail .head-line { display: flex; align-items: baseline; gap: 12px; margin-bottom: 8px; }
  #detail .big { font-size: 44px; color: var(--accent); line-height: 1; }
  #detail .gw { font-size: 15px; }
  #detail table { width: 100%; border-collapse: collapse; font-size: 13px; margin: 6px 0 10px; }
  #detail td { padding: 3px 6px; border-bottom: 1px dashed #e4d9bd; }
  #detail td:first-child { color: #7a6f5c; width: 5.5em; white-space: nowrap; }
  #detail .editions td:first-child { width: 7em; }
  #detail .text { max-height: 46vh; overflow: auto; font-size: 14.5px; line-height: 1.95;
    white-space: pre-wrap; padding-right: 6px; }
  #detail .pua { font-size: 12px; color: var(--accent); margin-top: 8px; }
  #log { font-size: 12px; line-height: 1.8; font-family: ui-monospace, monospace;
    color: #5c5342; max-height: 150px; overflow: auto; }
  #log .t { color: #a09378; margin-right: 6px; }
  .state { padding: 30px; text-align: center; color: #8a7c62; font-size: 14px; }
  .err { color: var(--accent); }
  #gallery { margin: 0 22px 14px; }
  .pbar { height: 8px; background: #e9dfc6; border-radius: 4px; overflow: hidden; margin: 6px 0 12px; }
  #pbarFill { height: 100%; background: var(--accent); width: 0; transition: width .4s; }
  #pgGrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(96px, 1fr)); gap: 8px;
    max-height: 264px; overflow: auto; padding: 2px; }
  .pgc { border: 1px solid var(--line); border-radius: 8px; padding: 8px 4px 6px; text-align: center;
    cursor: pointer; background: var(--card); }
  .pgc:hover { border-color: var(--accent); }
  .pgc.cur { border-color: var(--accent); background: #fdeede; }
  .pgc .n { font-size: 19px; font-weight: 700; }
  .pgc .m { font-size: 10.5px; color: #8a7c62; font-family: ui-monospace, monospace; line-height: 1.5; }
  .pgNav { display: flex; align-items: center; gap: 12px; justify-content: center; margin-top: 10px; }
  .pgNav button { padding: 3px 12px; }
  footer { padding: 8px 22px 16px; font-size: 11px; color: #a09378; }
</style>
</head>
<body>
<header>
  <h1>康熙字典爬取演示 <b>｜按页抓原图 · 按字抓全文</b></h1>
  <p>guji-ocr · fetch_kangxi_page + fetch_kangxi_entry + kangxi_store(SQLite) · 数据源 kangxizidian.com（武英殿版）· 限速 ≥1.2s/请求 · 库中已有零网络</p>
</header>

<div class="controls">
  <label>页码 <input id="pageNo" type="text" value="313"></label>
  <button id="fetchPage">抓取本页</button>
  <span class="hint">或直接查字</span>
  <input id="charBox" type="text" placeholder="如 丁" maxlength="2" style="width:70px">
  <button id="fetchChar" class="ghost">查字头详情</button>
  <span class="hint" id="pageRange"></span>
</div>

<div class="card" id="gallery">
  <h2>已爬取页面 <span id="pgProgress" class="hint"></span></h2>
  <div class="pbar"><div id="pbarFill"></div></div>
  <div id="pgGrid" class="state">载入中…</div>
  <div class="pgNav">
    <button id="pgPrev" class="ghost">‹ 上一页</button>
    <span id="pgInfo" class="hint"></span>
    <button id="pgNext" class="ghost">下一页 ›</button>
  </div>
</div>

<main>
  <div id="scanPane" class="card">
    <h2>整页扫描（爬取原图）</h2>
    <div id="scanBox" class="state">输入页码，点「抓取本页」——将抓阅读页 HTML 解析原图 URL 后下载</div>
    <div id="scanMeta"></div>
  </div>
  <div id="rightPane">
    <div class="card">
      <h2>本页字头（缩略图索引）</h2>
      <div id="thumbs" class="state">—</div>
    </div>
    <div class="card" id="detail">
      <h2>字头详情（爬取全文文本）</h2>
      <div id="detailBox" class="state">点击左侧字头缩略图，或直接查字</div>
    </div>
  </div>
</main>

<div class="card" style="margin: 0 22px;">
  <h2>请求轨迹</h2>
  <div id="log"></div>
</div>

<footer>演示用途；站点内容版权归 kangxizidian.com / 原书相关方，仅限内部研究评测。未编码字（缩略图 K 码、链接为破损实体）无法经详情端点查询，灰显不可点。</footer>

<script>
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function log(lines) {
  for (const line of lines ?? []) {
    const t = new Date().toLocaleTimeString('zh-CN', {hour12: false});
    $('log').insertAdjacentHTML('beforeend', `<div><span class="t">${t}</span>${esc(line)}</div>`);
    $('log').scrollTop = 1e9;
  }
}

async function api(path) {
  const res = await fetch(path);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  log(data.trace);
  return data;
}

async function fetchPage() {
  const n = $('pageNo').value.trim();
  if (!/^\\d{1,4}$/.test(n)) return alert('页码须为 1–7738 的数字');
  $('fetchPage').disabled = true;
  $('scanBox').innerHTML = '<div class="state">抓取中…（阅读页 + 原图，含限速间隔约 3–5 秒）</div>';
  try {
    const d = await api(`/api/page/${n}`);
    $('scanBox').innerHTML =
      `<img id="scanImg" src="/api/scan/${n}" alt="第 ${n} 页扫描" onclick="window.open(this.src)">`;
    const m = d.scan_meta;
    $('scanMeta').innerHTML =
      `直链 <code>${esc(d.scan_url)}</code><br>` +
      `${m.width}×${m.height} · ${(m.bytes / 1024).toFixed(0)} KB · ${m.source === 'cached' ? '本地缓存命中' : '本次下载'} · sha256 <code>${m.sha256.slice(0, 16)}…</code>`;
    $('pageRange').textContent = `全书 1–${d.total_pages} 页`;
    const chips = d.thumbs.map(t => t.char
      ? `<div class="chip" data-char="${esc(t.char)}" title="${esc(t.svg)}">
           <img src="${esc(t.thumb_url)}" loading="lazy" alt="${esc(t.char)}">
           <span class="no">#${esc(t.entry_no)}</span></div>`
      : `<div class="chip k" title="真·未编码字，详情端点不可查（${esc(t.svg)}）">
           <img src="${esc(t.thumb_url)}" loading="lazy">
           <span class="no"><span class="badge">未编码</span> ${esc(t.k_code)}</span></div>`
    ).join('');
    $('thumbs').innerHTML = chips || '<div class="state">本页无字头</div>';
    document.querySelectorAll('.chip[data-char]').forEach(el =>
      el.addEventListener('click', () => fetchChar(el.dataset.char, el)));
    if (d.thumbs.find(t => t.char)) fetchChar(d.thumbs.find(t => t.char).char);
    loadGallery();
  } catch (e) {
    $('scanBox').innerHTML = `<div class="state err">抓取失败：${esc(e.message)}</div>`;
  } finally { $('fetchPage').disabled = false; }
}

async function fetchChar(ch, chipEl) {
  document.querySelectorAll('.chip.sel').forEach(el => el.classList.remove('sel'));
  if (chipEl) chipEl.classList.add('sel');
  $('detailBox').innerHTML = '<div class="state">抓取详情中…</div>';
  try {
    const r = await api(`/api/entry/${encodeURIComponent(ch)}`);
    const ed = (name, e) => e ? `<tr><td>${name}</td><td>第 ${e.page} 頁，第 ${e.nth_char} 字</td></tr>` : '';
    $('detailBox').innerHTML = `
      <div class="head-line">
        <span class="big">${esc(r.head ?? ch)}</span>
        <span class="gw">${r.guwen ? '古文 ' + esc(r.guwen) : ''}</span>
        <span style="font-size:13px;color:#7a6f5c">${esc(r.juan ?? '')}</span>
        <code style="font-size:12px;color:#8a7c62">${esc(r.unicode)}</code>
      </div>
      <table>
        <tr><td>部首</td><td>${esc(r.radical) ?? ''}（部首 ${r.radical_strokes} 畫，部外 ${r.extra_strokes} 畫，共 ${r.total_strokes} 畫）</td></tr>
        <tr><td>拼音 / 注音</td><td>${(r.pinyin ?? []).join('，') || '—'} ／ ${(r.zhuyin ?? []).join('，') || '—'}</td></tr>
        <tr><td>倉頡 · 統一碼</td><td>${esc(r.cangjie) ?? '—'} · ${esc(r.unihan) ?? '—'}</td></tr>
      </table>
      <table class="editions">
        ${ed('同文書局本', r.tongwen_edition)}${ed('武英殿本', r.wuying_edition)}
      </table>
      <div class="text">${esc((r.text_paragraphs ?? []).join('\\n'))}</div>
      ${r.pua_other?.length ? `<div class="pua">⚠ 释文含疑似 kxfont 字形的私用区字符：${r.pua_other.map(esc).join(' ')}，需人工定字</div>` : ''}`;
  } catch (e) {
    $('detailBox').innerHTML = `<div class="state err">抓取失败：${esc(e.message)}</div>`;
  }
}

const PG_SIZE = 60;
let pgOffset = 0, pgTotal = 0;

async function loadGallery() {
  try {
    const d = await api(`/api/pages?offset=${pgOffset}&limit=${PG_SIZE}`);
    pgTotal = d.total;
    $('pgProgress').textContent = `${d.total} / ${d.total_pages} 页（${(d.total / d.total_pages * 100).toFixed(1)}%）`;
    $('pbarFill').style.width = `${d.total / d.total_pages * 100}%`;
    $('pgGrid').innerHTML = d.items.map(it => `
      <div class="pgc" data-p="${it.page}" title="${(it.scan_width || '?')}×${(it.scan_height || '?')}，抓于 ${esc(it.scan_fetched_at ?? '')}">
        <div class="n">${it.page}</div>
        <div class="m">字头 ${it.chars}（码 ${it.coded}）</div>
        <div class="m">${((it.scan_bytes || 0) / 1024).toFixed(0)}KB · ${esc((it.scan_fetched_at ?? '').slice(5, 10))}</div>
      </div>`).join('') || '<div class="state">尚无已爬取页面——输入页码点「抓取本页」开始</div>';
    const pages = Math.max(1, Math.ceil(pgTotal / PG_SIZE));
    $('pgInfo').textContent = `第 ${pgOffset / PG_SIZE + 1} / ${pages} 页`;
    const cur = String(+$('pageNo').value);
    document.querySelectorAll('.pgc').forEach(el => {
      el.classList.toggle('cur', el.dataset.p === cur);
      el.addEventListener('click', () => { $('pageNo').value = el.dataset.p; fetchPage(); });
    });
  } catch (e) {
    $('pgGrid').innerHTML = `<div class="state err">页面库载入失败：${esc(e.message)}</div>`;
  }
}

function pgTurn(delta) {
  const pages = Math.max(1, Math.ceil(pgTotal / PG_SIZE));
  pgOffset = Math.min(Math.max(0, pgOffset + delta * PG_SIZE), (pages - 1) * PG_SIZE);
  loadGallery();
}
$('pgPrev').addEventListener('click', () => pgTurn(-1));
$('pgNext').addEventListener('click', () => pgTurn(1));

$('fetchPage').addEventListener('click', fetchPage);
$('fetchChar').addEventListener('click', () => {
  const ch = $('charBox').value.trim();
  if ([...ch].length !== 1) return alert('请输入单个汉字');
  fetchChar(ch);
});
$('charBox').addEventListener('keydown', e => { if (e.key === 'Enter') $('fetchChar').click(); });

(async () => {
  await loadGallery();
  const first = document.querySelector('.pgc');   // 默认展示已爬的最小页码
  if (first) { $('pageNo').value = first.dataset.p; fetchPage(); }
  else fetchPage();                                // 空库时按输入框默认页码抓取
})();
</script>
</body>
</html>
"""


class DemoHandler(BaseHTTPRequestHandler):
    store: kangxi_store.KangxiStore  # main() 注入
    img_dir: Path = DEFAULT_CACHE / "pages"  # 本演示的原图落盘目录（路径同时入库）

    def log_message(self, fmt, *args):  # 静默默认访问日志，轨迹走 /api 响应
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _serve_scan(self, page: int):
        """输出库中登记的整页原图（由 /api/page 预先抓取/采纳）。"""
        row = DemoHandler.store.get_page(page)
        if not row or not row.get("scan_file"):
            self._json({"error": f"第 {page} 页原图未入库，请先请求 /api/page/{page}"}, 404)
            return
        path = Path(row["scan_file"])
        if not path.exists():
            self._json({"error": f"原图文件不可达（{path}；外置盘未挂载？）"}, 404)
            return
        self._send(200, path.read_bytes(), "image/jpeg")

    def do_GET(self):
        try:
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif m := re.fullmatch(r"/api/pages\?offset=(\d+)&limit=(\d+)", self.path):
                total, items = DemoHandler.store.list_pages(
                    limit=int(m.group(2)), offset=int(m.group(1)))
                self._json({"total": total, "total_pages": fp.TOTAL_PAGES, "items": items})
            elif m := re.fullmatch(r"/api/page/(\d{1,4})", self.path):
                self._json(api_page(int(m.group(1))))
            elif m := re.fullmatch(r"/api/scan/(\d{1,4})", self.path):
                self._serve_scan(int(m.group(1)))
            elif m := re.fullmatch(r"/api/entry/([^/]+)", self.path):
                self._json(api_entry(urllib.parse.unquote(m.group(1))))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:  # 面向演示页面回显错误
            self._json({"error": f"{type(e).__name__}: {e}"}, 502)


def _ui_thumbs(items: list[dict]) -> list[dict]:
    """page_chars 行 → 前端字头条目（附缩略图直链）。"""
    return [{**it, "thumb_url": THUMB_URL_PREFIX + it["svg"]} for it in items]


def api_page(page: int) -> dict:
    trace = []
    store = DemoHandler.store
    page_url = fe.READING_PAGE_TEMPLATE.format(page=page)
    html_path = DemoHandler.img_dir / f"{page:04d}.html"
    jpg_path = DemoHandler.img_dir / f"{page:04d}.jpg"
    missing = store.page_missing(page, ("reading", "scan"))

    if not missing:
        trace.append(f"页 {page:04d}：数据库命中（阅读页 + 原图），零网络请求")
    else:
        if "reading" in missing:
            if html_path.exists():  # 磁盘旧缓存采纳，不联网
                body = html_path.read_bytes()
                store.save_reading(page, body)
                store.log("page", page, "adopt-reading")
                trace.append(f"阅读页：磁盘旧缓存采纳入库（{html_path.name}）")
            else:
                with NET_LOCK:
                    fp.polite_sleep()
                    body, ctype = fp.http_get(page_url)
                store.save_reading(page, body)
                trace.append(f"阅读页 index2.php?page={page}：已下载 {len(body) // 1024}KB 入库")
        row = store.get_page(page)
        html = row["reading_html"] if row else None
        if not html:
            raise RuntimeError("阅读页入库失败，结构异常")
        scan_url = fp.extract_scan_url(html, page_url)
        if not scan_url:
            raise RuntimeError("阅读页未解析到 center-fit 扫描图，站点结构可能变化")
        if "scan" in missing:
            if fp.valid_cached_image(jpg_path):  # 磁盘旧缓存采纳，不联网
                store.adopt_scan(page, jpg_path, scan_url, fp.jpeg_size(jpg_path.read_bytes()))
                trace.append(f"原图 {jpg_path.name}：磁盘旧图采纳入库")
            else:
                with NET_LOCK:
                    fp.polite_sleep()
                    data, ctype = fp.http_get(scan_url)
                dims = fp.jpeg_size(data)
                if dims is None:
                    raise RuntimeError(f"原图响应非有效 JPEG（{ctype}，{len(data)}B）")
                jpg_path.parent.mkdir(parents=True, exist_ok=True)
                jpg_path.write_bytes(data)
                store.save_scan(page, data, jpg_path, scan_url, dims)
                trace.append(f"原图 {scan_url}：已下载 {len(data) // 1024}KB，JPEG 校验通过，入库")

    row = store.get_page(page) or {}
    html = row.get("reading_html") or ""
    scan_url = row.get("scan_url") or fp.extract_scan_url(html, page_url) or ""
    items = kangxi_store.parse_thumb_items(html)
    if items:
        store.save_page_chars(page, items)
    broken = sum(1 for it in items if it["char"] is None)
    trace.append(f"页→字头索引：{len(items)} 个字头（{broken} 个未编码灰显）已入库")
    return {
        "page": page,
        "scan_url": scan_url,
        "scan_meta": {"bytes": row.get("scan_bytes"), "width": row.get("scan_width"),
                      "height": row.get("scan_height"), "sha256": row.get("scan_sha256"),
                      "source": "db" if not missing else "fetched"},
        "thumbs": _ui_thumbs(items),
        "total_pages": fp.TOTAL_PAGES,
        "trace": trace,
    }


def api_entry(sword: str) -> dict:
    trace = []
    store = DemoHandler.store
    if len(sword) != 1:
        raise RuntimeError(f"sword 须为单字，收到 {sword!r}")
    row = store.get_entry_by_char(sword)
    if row and row.get("record_json"):
        rec = json.loads(row["record_json"])
        trace.append(f"字头 {sword} 详情：数据库命中（entries U+{ord(sword):04X}），零网络请求")
    else:
        url = fe.DETAIL_TEMPLATE.format(sword=urllib.parse.quote(sword))
        with NET_LOCK:
            fp.polite_sleep()
            body, ctype = fe.http_get(url)
        trace.append(f"详情页 {url}：已下载 {len(body) // 1024}KB（Content-Type {ctype}）")
        rec = fe.parse_detail(body.decode("utf-8-sig", "replace"), sword)
        if rec is None:
            raise RuntimeError(f"详情页未命中（无「字頭：」卡片），站点可能不收录 {sword!r}")
        store.save_entry(sword, rec, raw_html=body.decode("utf-8-sig", "replace"), source_url=url)
        trace.append(f"解析成功：{rec['text_chars']} 字 / {len(rec['text_paragraphs'])} 段，已入库")
    rec["trace"] = trace
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8318)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help=f"原图落盘目录（默认 {DEFAULT_CACHE}）")
    ap.add_argument("--db", type=Path, default=kangxi_store.DEFAULT_DB,
                    help=f"SQLite 库路径（默认 {kangxi_store.DEFAULT_DB}，与爬取器共用）")
    args = ap.parse_args()

    DemoHandler.img_dir = args.cache / "pages"
    DemoHandler.img_dir.mkdir(parents=True, exist_ok=True)
    DemoHandler.store = kangxi_store.KangxiStore(args.db)

    print("核查 robots.txt …", flush=True)
    fe.check_robots()  # 禁止即 sys.exit(2)
    print(f"SQLite：{args.db}")
    print(f"原图目录：{DemoHandler.img_dir}", flush=True)
    print(json.dumps(DemoHandler.store.stats(), ensure_ascii=False), flush=True)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), DemoHandler)
    print(f"演示页：http://127.0.0.1:{args.port}/  （Ctrl+C 退出）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
