#!/usr/bin/env python3
"""康熙字典爬取功能演示服务器：网页展示「按页抓原图 + 按字头抓全文详情」。

复用同目录爬虫原语，不重复实现爬取礼仪：
- fetch_kangxi_page.py：阅读页解析（extract_scan_url）、JPEG 校验与缓存
- fetch_kangxi_entry.py：字头详情解析（parse_detail）、阅读页字头提取、robots 核查

流程：浏览器输入页码 → GET /api/page/N（抓阅读页 HTML 解析字头 + 下载原图入缓存）
→ <img> 经 /api/scan/N 展示缓存原图 → 点字头 → GET /api/entry/{字} 抓详情卡，
结构化展示元数据与分段释文；每次请求的轨迹（缓存命中/下载/限速）返回前端展示。

用法：
  python3 kangxi_crawl_demo.py [--port 8318] [--cache datasets/kangxi-demo-cache]
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
  footer { padding: 8px 22px 16px; font-size: 11px; color: #a09378; }
</style>
</head>
<body>
<header>
  <h1>康熙字典爬取演示 <b>｜按页抓原图 · 按字抓全文</b></h1>
  <p>guji-ocr · scripts/fetch_kangxi_page.py + fetch_kangxi_entry.py · 数据源 kangxizidian.com（武英殿版）· 限速 ≥1.2s/请求 · 本地缓存</p>
</header>

<div class="controls">
  <label>页码 <input id="pageNo" type="text" value="313"></label>
  <button id="fetchPage">抓取本页</button>
  <span class="hint">或直接查字</span>
  <input id="charBox" type="text" placeholder="如 丁" maxlength="2" style="width:70px">
  <button id="fetchChar" class="ghost">查字头详情</button>
  <span class="hint" id="pageRange"></span>
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

$('fetchPage').addEventListener('click', fetchPage);
$('fetchChar').addEventListener('click', () => {
  const ch = $('charBox').value.trim();
  if ([...ch].length !== 1) return alert('请输入单个汉字');
  fetchChar(ch);
});
$('charBox').addEventListener('keydown', e => { if (e.key === 'Enter') $('fetchChar').click(); });
fetchPage();
</script>
</body>
</html>
"""


class DemoHandler(BaseHTTPRequestHandler):
    cache: Path = DEFAULT_CACHE
    pages_dir: Path = DEFAULT_CACHE / "pages"
    entries_dir: Path = DEFAULT_CACHE / "entries"

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
        """输出缓存的整页原图（由 /api/page 预先抓取）。"""
        jpg_path = DemoHandler.pages_dir / f"{page:04d}.jpg"
        if not fp.valid_cached_image(jpg_path):
            self._json({"error": f"第 {page} 页原图未缓存，请先请求 /api/page/{page}"}, 404)
            return
        self._send(200, jpg_path.read_bytes(), "image/jpeg")

    def do_GET(self):
        try:
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE_HTML.encode("utf-8"), "text/html; charset=utf-8")
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


def _thumb_items(page_html: str) -> list[dict]:
    """配对阅读页缩略图的 (sword 实体, svg 文件名)，产出前端字头条目。"""
    items = []
    for m in re.finditer(
        r"sword=&#x([0-9A-Fa-f]*)['\"][^>]*>\s*<img[^>]*?src=['\"]?([^'\"\s>]+\.svg)", page_html
    ):
        hexcode, svg = m.group(1), m.group(2).split("/")[-1]
        stem = svg[:-4].split("-")
        k_code = stem[2] if stem[2].startswith("K") else None
        items.append({
            "char": chr(int(hexcode, 16)) if hexcode else None,
            "k_code": k_code,
            "entry_no": stem[2] if len(stem) == 4 and not k_code else (k_code or stem[2]),
            "page_seq": int(stem[1]),
            "svg": svg,
            "thumb_url": THUMB_URL_PREFIX + svg,
        })
    return items


def api_page(page: int) -> dict:
    trace = []
    page_html_path = DemoHandler.pages_dir / f"{page:04d}.html"
    if page_html_path.exists():
        page_html = page_html_path.read_text(encoding="utf-8-sig")
        trace.append(f"阅读页 index2.php?page={page}：本地缓存命中（{page_html_path.name}）")
    else:
        with NET_LOCK:
            fp.polite_sleep()
            body, ctype = fp.http_get(fe.READING_PAGE_TEMPLATE.format(page=page))
        page_html = body.decode("utf-8-sig", "replace")
        page_html_path.parent.mkdir(parents=True, exist_ok=True)
        page_html_path.write_bytes(body)
        trace.append(f"阅读页 index2.php?page={page}：已下载 {len(body) // 1024}KB（Content-Type {ctype}），缓存为 {page_html_path.name}")

    scan_url = fp.extract_scan_url(page_html, fe.READING_PAGE_TEMPLATE.format(page=page))
    if not scan_url:
        raise RuntimeError("阅读页未解析到 center-fit 扫描图，站点结构可能变化")

    jpg_path = DemoHandler.pages_dir / f"{page:04d}.jpg"
    if fp.valid_cached_image(jpg_path):
        source = "cached"
        trace.append(f"原图 {scan_url.rsplit('/', 1)[-1]}：本地缓存命中")
    else:
        with NET_LOCK:
            fp.polite_sleep()
            data, ctype = fp.http_get(scan_url)
        if fp.jpeg_size(data) is None:
            raise RuntimeError(f"原图响应非有效 JPEG（{ctype}，{len(data)}B）")
        jpg_path.parent.mkdir(parents=True, exist_ok=True)
        jpg_path.write_bytes(data)
        source = "download"
        trace.append(f"原图 {scan_url}：已下载 {len(data) // 1024}KB，校验 JPEG 通过，缓存为 {jpg_path.name}")

    data = jpg_path.read_bytes()
    w, h = fp.jpeg_size(data)
    import hashlib
    thumbs = _thumb_items(page_html)
    broken = sum(1 for t in thumbs if t["char"] is None)
    trace.append(f"字头索引：解析出 {len(thumbs)} 个字头（{broken} 个未编码灰显）")
    return {
        "page": page,
        "scan_url": scan_url,
        "scan_meta": {"bytes": len(data), "width": w, "height": h,
                      "sha256": hashlib.sha256(data).hexdigest(), "source": source},
        "thumbs": thumbs,
        "total_pages": fp.TOTAL_PAGES,
        "trace": trace,
    }


def api_entry(sword: str) -> dict:
    trace = []
    if len(sword) != 1:
        raise RuntimeError(f"sword 须为单字，收到 {sword!r}")
    rec_path = DemoHandler.entries_dir / f"{ord(sword):04X}.json"
    if rec_path.exists():
        try:
            rec = json.loads(rec_path.read_text(encoding="utf-8"))
            if rec.get("text_paragraphs"):
                trace.append(f"字头 {sword} 详情：本地缓存命中（{rec_path.name}）")
                rec["trace"] = trace
                return rec
        except (OSError, json.JSONDecodeError):
            pass
    url = fe.DETAIL_TEMPLATE.format(sword=urllib.parse.quote(sword))
    with NET_LOCK:
        fp.polite_sleep()
        body, ctype = fe.http_get(url)
    trace.append(f"详情页 {url}：已下载 {len(body) // 1024}KB（Content-Type {ctype}）")
    rec = fe.parse_detail(body.decode("utf-8-sig", "replace"), sword)
    if rec is None:
        raise RuntimeError(f"详情页未命中（无「字頭：」卡片），站点可能不收录 {sword!r}")
    rec_path.parent.mkdir(parents=True, exist_ok=True)
    rec_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    trace.append(f"解析成功：{rec['text_chars']} 字 / {len(rec['text_paragraphs'])} 段，缓存为 {rec_path.name}")
    rec["trace"] = trace
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8318)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help=f"缓存目录（默认 {DEFAULT_CACHE}）")
    args = ap.parse_args()

    DemoHandler.pages_dir = args.cache / "pages"
    DemoHandler.entries_dir = args.cache / "entries"
    DemoHandler.pages_dir.mkdir(parents=True, exist_ok=True)
    DemoHandler.entries_dir.mkdir(parents=True, exist_ok=True)

    print("核查 robots.txt …", flush=True)
    fe.check_robots()  # 禁止即 sys.exit(2)
    print(f"缓存目录：{args.cache}", flush=True)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), DemoHandler)
    print(f"演示页：http://127.0.0.1:{args.port}/  （Ctrl+C 退出）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
