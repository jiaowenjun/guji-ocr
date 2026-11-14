#!/usr/bin/env python3
"""列分割可视化服务器：扫描图 + 大列/小列叠加 + 金标行分配对照。

用法：python3 scripts/kangxi_column_seg_server.py [port]   # 默认 8319，仅本机
页面：
  - 扫描图为底，画布叠加：绿=正文块、红=大列界、蓝实=有谷值证据小列、
    蓝虚=网格补位小列、紫标 chars_est/cap
  - 侧栏：pitch/证据率/wide 统计 + 逐小列表（含金标分配行区间与首行文本）
  - 图上悬停/点表行联动高亮；图层开关、缩放
数据按需计算（kangxi_column_seg.segment + eval_column_seg.assign_lines），进程内缓存。
"""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from kangxi_column_seg import segment, IMGDIR          # noqa: E402
from eval_column_seg import assign_lines               # noqa: E402
from eval_ocr_fold import gj_bands, norm               # noqa: E402

GJ_DIR = HERE.parents[1] / "kangxi-gold/annotations"
_CACHE: dict[int, dict] = {}


def seg_with_gold(page: int) -> dict:
    if page in _CACHE:
        return _CACHE[page]
    res = segment(page)
    gold = None
    gj = GJ_DIR / f"{page:04d}.gj"
    if "error" not in res and gj.exists():
        lines = [l for b in gj_bands(gj) for l in b]
        lens = [len(norm(l)) for l in lines]
        ests = [m["chars_est"] for maj in res["majors"] for m in maj["minors"]]
        ranges = assign_lines(lens, ests)
        gold = dict(lines=lines, lens=lens, ranges=ranges)
    out = dict(seg=res, gold=gold)
    _CACHE[page] = out
    return out


HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>康熙字典 · 列分割可视化</title>
<style>
  :root { --bg:#14161a; --panel:#1d2026; --line:#2c313a; --fg:#d8dce4; --dim:#8b93a1;
          --red:#ff4d4d; --blue:#4d7dff; --green:#2ecc71; --purple:#d38bff; --gold:#ffd166; }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--fg); font:14px/1.5 -apple-system,"PingFang SC",sans-serif;
         display:flex; flex-direction:column; height:100vh; }
  header { display:flex; align-items:center; gap:14px; padding:8px 14px; background:var(--panel);
           border-bottom:1px solid var(--line); flex-wrap:wrap; }
  header h1 { font-size:15px; font-weight:600; color:var(--gold); }
  select, button { background:#262a32; color:var(--fg); border:1px solid var(--line);
                   border-radius:6px; padding:4px 8px; font-size:13px; cursor:pointer; }
  label.tog { display:flex; align-items:center; gap:4px; color:var(--dim); font-size:13px; cursor:pointer; }
  #hoverbar { margin-left:auto; font-size:12px; color:var(--dim); max-width:46vw;
              white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  main { display:flex; flex:1; min-height:0; }
  #viewer { flex:1; overflow:auto; position:relative; background:#0d0e11; }
  #wrap { position:relative; transform-origin:0 0; }
  #wrap img, #wrap canvas { position:absolute; left:0; top:0; display:block; }
  aside { width:430px; background:var(--panel); border-left:1px solid var(--line);
          overflow:auto; padding:10px 12px; }
  aside h2 { font-size:13px; color:var(--dim); font-weight:600; margin:8px 0 4px; }
  #stats { font-size:13px; }
  #stats b { color:var(--gold); font-weight:600; }
  table { border-collapse:collapse; width:100%; font-size:12.5px; }
  td, th { padding:3px 6px; border-bottom:1px solid var(--line); text-align:left;
           white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:190px; }
  th { color:var(--dim); font-weight:500; }
  tr.major-row td { background:#232730; color:var(--red); font-weight:600; cursor:pointer; }
  tr.minor-row { cursor:pointer; }
  tr.minor-row:hover, tr.minor-row.sel { background:#2a3040; }
  tr.major-row:hover { background:#2c313c; }
  .k { color:var(--gold); } .dim { color:var(--dim); } .bad { color:var(--red); }
  .sw { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:4px; vertical-align:-1px; }
</style>
</head>
<body>
<header>
  <h1>列分割可视化</h1>
  <select id="page"></select>
  <button id="prev">◀</button><button id="next">▶</button>
  <span id="pitch" class="dim"></span>
  <label class="tog"><input type="checkbox" id="t-major" checked><span class="sw" style="background:var(--red)"></span>大列界</label>
  <label class="tog"><input type="checkbox" id="t-minor" checked><span class="sw" style="background:var(--blue)"></span>小列</label>
  <label class="tog"><input type="checkbox" id="t-ink"><span class="sw" style="background:rgba(77,125,255,.35)"></span>墨迹范围</label>
  <label class="tog"><input type="checkbox" id="t-label" checked><span class="sw" style="background:var(--purple)"></span>标签</label>
  <select id="zoom">
    <option value="fit">适宽</option><option value="0.5">50%</option>
    <option value="0.75">75%</option><option value="1" selected>100%</option>
    <option value="1.5">150%</option><option value="2">200%</option>
  </select>
  <span id="hoverbar">悬停小列查看详情</span>
</header>
<main>
  <div id="viewer"><div id="wrap"><img id="scan"><canvas id="cv"></canvas></div></div>
  <aside>
    <h2>统计</h2><div id="stats"></div>
    <h2>大列 → 小列（阅读序，右→左；含金标行分配）</h2>
    <table id="tbl"><thead><tr>
      <th>小列</th><th>chars/cap</th><th>界</th><th>金标</th><th>首行</th>
    </tr></thead><tbody></tbody></table>
  </aside>
</main>
<script>
let DATA = null, sel = null, slots = [];
const $ = id => document.getElementById(id);
const cv = $("cv"), ctx = cv.getContext("2d");

async function loadPages() {
  const r = await (await fetch("/api/pages")).json();
  const selEl = $("page");
  selEl.innerHTML = "";
  for (const p of r.pages) {
    const o = document.createElement("option");
    o.value = p; o.textContent = "@" + p;
    selEl.appendChild(o);
  }
  selEl.value = 333;
  if (!r.pages.includes(333) && r.pages.length) selEl.value = r.pages[Math.floor(r.pages.length/2)];
  if (!r.mounted || !r.pages.length)
    $("hoverbar").textContent = "WD-2T 未挂载或 " + r.imgdir + " 无扫描图";
  selEl.onchange = () => load(+selEl.value);
  $("prev").onclick = () => { const i = r.pages.indexOf(+selEl.value); if (i>0){selEl.value=r.pages[i-1]; load(r.pages[i-1]);} };
  $("next").onclick = () => { const i = r.pages.indexOf(+selEl.value); if (i<r.pages.length-1){selEl.value=r.pages[i+1]; load(r.pages[i+1]);} };
  load(+selEl.value);
}

async function load(page) {
  let d = null;
  try {
    const r = await fetch("/api/seg?page=" + page);
    d = await r.json();
    if (!r.ok || !d || !d.seg || !d.seg.majors)
      throw new Error((d && (d.error || d.seg && d.seg.error)) || ("HTTP " + r.status));
  } catch (e) {
    DATA = null; sel = null; slots = [];
    $("pitch").textContent = "加载失败";
    $("hoverbar").textContent = "@" + page + " 分割失败：" + e.message +
      "（检查 WD-2T 挂载 / raw/kangxizidian/pages 有无该页图）";
    $("stats").innerHTML = "<span class='bad'>分割失败：" + e.message + "</span>";
    $("tbl").tBodies[0].innerHTML = "";
    $("scan").removeAttribute("src");
    return;
  }
  DATA = d;
  sel = null;
  const s = DATA.seg;
  $("pitch").textContent = `pitch ${s.pitch} · 证据 ${s.lines_evidence} · 大列 ${s.n_majors} 小列 ${s.n_minors}`;
  const img = $("scan");
  img.onerror = () => {
    $("hoverbar").textContent = "@" + page + " 扫描图加载失败（/image/NNNN.jpg 404）";
  };
  img.onload = () => { $("hoverbar").textContent = "悬停小列查看详情"; layout(); draw(); };
  img.src = `/image/${String(page).padStart(4,"0")}.jpg?${Date.now()}`;
  buildSlots();
  renderStats();
  renderTable();
}

function buildSlots() {
  slots = []; let mi = 0;
  DATA.seg.majors.forEach((maj, j) => {
    maj.minors.forEach((m, k) => {
      const rng = DATA.gold && DATA.gold.ranges ? DATA.gold.ranges[mi] : null;
      const gl = rng && rng[1] > rng[0] ? rng : null;
      slots.push({ ...m, major: j, kind: maj.kind, idx: mi,
        gold: gl, goldN: gl ? gl[1]-gl[0] : 0,
        goldChars: gl ? DATA.gold.lens.slice(gl[0], gl[1]).reduce((a,b)=>a+b,0) : 0,
        goldText: gl ? DATA.gold.lines[gl[0]] : "" });
      mi++;
    });
  });
}

function renderStats() {
  const s = DATA.seg;
  const wide = s.majors.filter(m => m.kind === "wide").length;
  const est = slots.reduce((a,x)=>a+x.chars_est,0);
  const goldTot = DATA.gold ? DATA.gold.lens.reduce((a,b)=>a+b,0) : null;
  $("stats").innerHTML =
    `块 <b>[${s.block.join(", ")}]</b> · pitch <b>${s.pitch}</b> · 线证据 <b>${s.lines_evidence}</b><br>` +
    `大列 <b>${s.n_majors}</b>（wide <b>${wide}</b>）小列 <b>${s.n_minors}</b> · Σchars_est <b>${est}</b>` +
    (DATA.gold ? `<br>金标行 <b>${DATA.gold.lines.length}</b> Σ字 <b>${goldTot}</b>` : `<br><span class="dim">无金标 .gj</span>`);
}

function renderTable() {
  const tb = $("tbl").tBodies[0];
  tb.innerHTML = "";
  let mi = 0;
  DATA.seg.majors.forEach((maj, j) => {
    const tr = document.createElement("tr");
    tr.className = "major-row";
    tr.innerHTML = `<td colspan="5">大列${j} ${maj.kind} x[${maj.x1},${maj.x2}]</td>`;
    tr.onclick = () => highlight(slots.find(s=>s.major===j));
    tb.appendChild(tr);
    maj.minors.forEach(m => {
      const s = slots[mi];
      const tr2 = document.createElement("tr");
      tr2.className = "minor-row"; tr2.dataset.idx = mi;
      const dev = s.gold ? s.chars_est - s.goldChars : null;
      const devCls = dev === null ? "" : (Math.abs(dev) <= 2 ? "" : Math.abs(dev) <= 4 ? "k" : "bad");
      tr2.innerHTML =
        `<td>${mi}</td><td class="${devCls}">${s.chars_est}/${s.cap}${dev!==null?" ("+(dev>0?"+":"")+dev+")":""}</td>` +
        `<td class="${s.bound==="detected"?"":"dim"}">${s.bound==="detected"?"谷值":"网格"}</td>` +
        `<td class="k">${s.gold ? s.goldN+"行/"+s.goldChars+"字" : "—"}</td>` +
        `<td class="dim" title="${s.goldText}">${s.goldText.slice(0,14)}</td>`;
      tr2.onclick = () => { highlight(s); tr2.scrollIntoView({block:"nearest"}); };
      tb.appendChild(tr2);
      mi++;
    });
  });
}

function layout() {
  const img = $("scan");
  const w = img.naturalWidth, h = img.naturalHeight;
  const dpr = window.devicePixelRatio || 1;
  cv.width = w * dpr; cv.height = h * dpr;
  cv.style.width = w + "px"; cv.style.height = h + "px";
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  applyZoom();
}

function applyZoom() {
  const img = $("scan");
  const z = $("zoom").value;
  const v = $("viewer");
  const s = z === "fit" ? (v.clientWidth - 8) / img.naturalWidth : +z;
  $("wrap").style.transform = `scale(${s})`;
  $("wrap").style.width = img.naturalWidth + "px";
  $("wrap").style.height = img.naturalHeight + "px";
  v.scrollLeft = 0; v.scrollTop = 0;
}

function draw() {
  const img = $("scan");
  const s = DATA.seg, W = img.naturalWidth, H = img.naturalHeight;
  ctx.clearRect(0, 0, W, H);
  const [bx0, by0, bx1, by1] = s.block;
  ctx.strokeStyle = getCSS("--green"); ctx.lineWidth = 2;
  ctx.strokeRect(bx0, by0, bx1-bx0, by1-by0);
  if ($("t-major").checked) {
    ctx.strokeStyle = getCSS("--red"); ctx.lineWidth = 2;
    s.majors.forEach(m => {
      line(m.x2, by0, m.x2, by1); line(m.x1, by0, m.x1, by1);
      if (m.kind === "wide") {
        ctx.fillStyle = getCSS("--red"); ctx.font = "bold 15px sans-serif";
        ctx.fillText("W", (m.x1+m.x2)/2-4, by0-6);
      }
    });
  }
  if ($("t-minor").checked) {
    slots.forEach(m => {
      ctx.beginPath();
      ctx.setLineDash(m.bound === "detected" ? [] : [6,6]);
      ctx.strokeStyle = m === sel ? "#fff" : getCSS("--blue");
      ctx.lineWidth = m === sel ? 2.5 : 1;
      const y0 = m.y1 ?? by0+8, y1 = m.y2 ?? by1-8;
      ctx.rect(m.x1+.5, y0+.5, m.x2-m.x1-1, y1-y0-1);
      ctx.stroke(); ctx.setLineDash([]);
      if ($("t-ink").checked) {
        ctx.fillStyle = "rgba(77,125,255,.14)";
        ctx.fillRect(m.x1, y0, m.x2-m.x1, y1-y0);
      }
    });
  }
  if ($("t-label").checked) {
    ctx.fillStyle = getCSS("--purple"); ctx.font = "11px sans-serif";
    slots.forEach(m => {
      ctx.fillText(`${m.chars_est}/${m.cap}`, m.x1 + 4, (m.y1 ?? by0) + 12);
    });
  }
}
function line(x1,y1,x2,y2){ ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke(); }
function getCSS(v){ return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }

function highlight(s) {
  sel = s; draw();
  document.querySelectorAll("tr.minor-row").forEach(tr =>
    tr.classList.toggle("sel", s && +tr.dataset.idx === s.idx));
  $("hoverbar").textContent = s
    ? `大列${s.major}(${s.kind}) 小列${s.idx} x[${s.x1},${s.x2}] y[${s.y1},${s.y2}] cap${s.cap} chars${s.chars_est} ${s.bound==="detected"?"谷值":"网格"}` +
      (s.gold ? ` | 金标 ${s.goldN}行/${s.goldChars}字『${s.goldText.slice(0,18)}…』` : "")
    : "";
}

cv.addEventListener("mousemove", e => {
  if (!DATA) return;
  const r = cv.getBoundingClientRect();
  const mx = (e.clientX - r.left) * cv.width / r.width / (window.devicePixelRatio||1);
  const s = slots.find(x => mx >= x.x1 && mx <= x.x2);
  if (s) highlight(s);
});
cv.addEventListener("mouseleave", () => { sel = null; draw(); document.querySelectorAll("tr.minor-row").forEach(t=>t.classList.remove("sel")); });

["t-major","t-minor","t-ink","t-label"].forEach(id => $(id).onchange = draw);
$("zoom").onchange = applyZoom;
window.addEventListener("resize", applyZoom);
window.addEventListener("keydown", e => {
  if (e.key === "ArrowLeft") $("prev").click();
  if (e.key === "ArrowRight") $("next").click();
});
loadPages();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/":
                self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif u.path == "/api/pages":
                ps = sorted(int(p.stem) for p in IMGDIR.glob("[0-9][0-9][0-9][0-9].jpg")) \
                    if IMGDIR.is_dir() else []
                self._send(200, json.dumps(
                    dict(pages=ps, imgdir=str(IMGDIR), mounted=IMGDIR.is_dir()),
                    ensure_ascii=False).encode(), "application/json")
            elif u.path == "/api/seg":
                page = int(q["page"][0])
                out = seg_with_gold(page)
                if "error" in out["seg"]:
                    self._send(404, json.dumps(out["seg"], ensure_ascii=False).encode(),
                               "application/json")
                else:
                    self._send(200, json.dumps(out, ensure_ascii=False).encode(),
                               "application/json")
            elif m := re.fullmatch(r"/image/(\d{4})\.jpg", u.path):
                f = IMGDIR / f"{m.group(1)}.jpg"
                if f.is_file():
                    self._send(200, f.read_bytes(), "image/jpeg")
                else:
                    self._send(404, b"not found", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")
        except Exception as e:  # noqa: BLE001
            self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")

    def log_message(self, fmt, *args):  # 静默常规日志
        if "/api/seg" in (args[0] if args else ""):
            sys.stderr.write(f"seg {fmt % args}\n")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8319
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"列分割可视化：http://127.0.0.1:{port}（图片目录 {IMGDIR}）")
    srv.serve_forever()


if __name__ == "__main__":
    main()
