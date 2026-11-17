#!/usr/bin/env python3
"""Build a self-contained HTML page comparing local ONNX PP-OCRv6 vs online PaddleOCR-VL.

Data: var/scratch/receval_onnx.json + receval_sample.json + pageeval_report.json and the
service DB cache (online whole-page results incl. layout polygons). Output: pagecmp.html.
"""
import base64
import difflib
import hashlib
import io
import json
import sqlite3

from PIL import Image

PAGES = [312, 318, 328, 342, 349, 358]
SCAN = '/Volumes/WD-2T/guji-ocr/raw/kangxizidian/pages/%04d.jpg'
GOLD = '/Users/jwj/workspace/guji-ocr/kangxi-gold/annotations/%04d.txt'
CROP_ROOT = '/Users/jwj/workspace/guji-ocr/var/datasets/kangxi-ocr/'
DB = '/Users/jwj/workspace/guji-ocr/paddleocr-baseline/data/ocr/ocr.sqlite3'
OUT = '/Users/jwj/workspace/guji-ocr/var/scratch/pagecmp.html'
DISPLAY_W = 760


def norm(s):
    return ''.join((s or '').split())


NL = '⏎'


def normD(s):
    """Whitespace-stripped but newlines preserved as NL marker chars for display diff."""
    return ''.join(NL if ch == '\n' else ch for ch in (s or '') if ch == '\n' or not ch.isspace())


def b64img(path, width=None, quality=82):
    im = Image.open(path)
    if width and im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.convert('RGB').save(buf, 'JPEG' if width else 'PNG', quality=quality)
    return base64.b64encode(buf.getvalue()).decode(), im.width, im.height


def assemble(crops):
    bands = {}
    for c in crops:
        bands.setdefault(c['id'].split('-')[1], []).append(c)
    ordered = []
    for b in sorted(bands, key=lambda b: -min(c['bbox_in_page'][0] for c in bands[b])):
        group = bands[b]
        if len(group) == 1:
            ordered += group
            continue
        xs = sorted(c['bbox_in_page'][0] + c['bbox_in_page'][2] for c in group)
        split = (xs[0] + xs[-1]) / 2
        right = [c for c in group if (c['bbox_in_page'][0] + c['bbox_in_page'][2]) / 2 >= split / 1]
        left = [c for c in group if c not in right]
        right.sort(key=lambda c: c['bbox_in_page'][1])
        left.sort(key=lambda c: c['bbox_in_page'][1])
        ordered += right + left
    return ordered


def opcodes(gold, pred):
    return [[t, g0, g1, p0, p1] for t, g0, g1, p0, p1 in
            difflib.SequenceMatcher(None, gold, pred, autojunk=False).get_opcodes()]


def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def main():
    onnx = {r['id']: r for r in json.load(open('/Users/jwj/workspace/guji-ocr/var/scratch/receval_onnx.json'))['rows']}
    sample = json.load(open('/Users/jwj/workspace/guji-ocr/var/scratch/receval_sample.json'))
    pagemetrics = {r['page']: r for r in json.load(open('/Users/jwj/workspace/guji-ocr/var/scratch/pageeval_report.json'))}
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row

    pages = []
    for page in PAGES:
        crops = assemble([c for c in sample if c['source_page'] == page and c['kind'] in ('text_run', 'large')])
        gold = normD(open(GOLD % page).read().replace('\r', ''))
        rows = []
        local_parts = []
        for i, c in enumerate(crops):
            o = onnx[c['id']]
            g, p = norm(c['text']), norm(o['pred'])
            cer = lev(g, p) / max(1, len(g))
            thumb, _, _ = b64img(CROP_ROOT + c['image'], 120, 80)
            rows.append({'n': i, 'id': c['id'], 'kind': c['kind'], 'bbox': c['bbox_in_page'],
                         'gold': c['text'], 'pred': o['pred'], 'conf': o['conf'], 'ms': o['ms'],
                         'cer': round(cer, 3), 'cls': 'em' if cer == 0 else ('ok' if cer <= .3 else 'bad'),
                         'thumb': thumb})
            local_parts.append(normD(o['pred']))
        local = NL.join(local_parts)

        h = hashlib.sha256(open(SCAN % page, 'rb').read()).hexdigest()
        rj = json.loads(db.execute('select result_json from images where sha256=?', (h,)).fetchone()[0])
        blocks, online_parts = [], []
        for pg in rj['result']['layoutParsingResults']:
            for blk in pg['prunedResult']['parsing_res_list']:
                blocks.append({'label': blk.get('block_label'), 'order': blk.get('block_order'),
                               'bbox': blk.get('block_bbox'), 'poly': blk.get('block_polygon_points'),
                               'content': blk.get('block_content') or ''})
                part = normD(blocks[-1]['content'])
                if part:
                    online_parts.append(part)
        online = NL.join(online_parts)

        img, iw, ih = b64img(SCAN % page, DISPLAY_W)
        pages.append({
            'page': page, 'img': img, 'iw': iw, 'ih': ih,
            'gold': gold, 'local': local, 'online': online,
            'ops_local': opcodes(gold, local), 'ops_online': opcodes(gold, online),
            'crops': rows, 'oblocks': blocks,
            'metrics': pagemetrics[page],
        })
        print(page, 'crops', len(rows), 'gold', len(gold), 'local', len(local), 'online', len(online))

    summary = {
        'local_mean_cer': round(sum(p['metrics']['local']['cer'] for p in pages) / len(pages), 4),
        'online_mean_cer': round(sum(p['metrics']['online']['cer'] for p in pages) / len(pages), 4),
    }
    data = {'pages': pages, 'summary': summary}
    html = TEMPLATE.replace('__DATA__', json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    open(OUT, 'w').write(html)
    print('written', OUT, len(html) // 1024, 'KB')


TEMPLATE = r'''<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>整页识别对比：本机 ONNX PP-OCRv6 vs 线上 PaddleOCR-VL</title>
<style>
:root { --em:#1a7f37; --ok:#b08514; --bad:#cf222e; --ink:#1c1c1c; --mut:#6e7781; --bg:#f6f6f4; --card:#fff; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font-family:-apple-system,"PingFang SC","Hiragino Sans GB",sans-serif; }
header { padding:18px 24px 10px; }
h1 { font-size:18px; margin:0 0 4px; }
.sub { color:var(--mut); font-size:12.5px; }
.tabs { display:flex; gap:6px; padding:10px 24px; flex-wrap:wrap; }
.tab { padding:6px 14px; border:1px solid #d0d7de; border-radius:16px; background:var(--card);
  cursor:pointer; font-size:13px; }
.tab.on { background:#24292f; color:#fff; border-color:#24292f; }
main { padding:0 24px 40px; }
.cards { display:flex; gap:10px; flex-wrap:wrap; margin:4px 0 12px; }
.card { background:var(--card); border:1px solid #e4e4e1; border-radius:8px; padding:10px 14px; min-width:120px; }
.card .k { font-size:11px; color:var(--mut); margin-bottom:3px; }
.card .v { font-size:17px; font-weight:600; }
.card .v small { font-size:11px; color:var(--mut); font-weight:400; }
.bad-v { color:var(--bad); } .em-v { color:var(--em); }
.note { font-size:12px; color:var(--mut); margin:2px 0 10px; }
.modes { display:flex; gap:6px; margin-bottom:12px; }
.mode { padding:5px 12px; font-size:12.5px; border:1px solid #d0d7de; border-radius:6px;
  background:var(--card); cursor:pointer; }
.mode.on { background:#0969da; color:#fff; border-color:#0969da; }
.pane { display:none; } .pane.on { display:block; }
.diffcols { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.diffcard { background:var(--card); border:1px solid #e4e4e1; border-radius:8px; padding:12px 14px; }
.diffcard h3 { margin:0 0 8px; font-size:13px; }
.diffcard h3 .tag { font-weight:400; color:var(--mut); font-size:11px; }
.goldline, .predline { font-family:"Songti SC","Noto Serif SC",serif; font-size:15.5px;
  line-height:1.9; letter-spacing:.5px; word-break:break-all; margin:4px 0 10px; }
.lab { font-size:11px; color:var(--mut); margin-top:6px; }
span.eq {}
span.del { background:#ffdce0; border-radius:2px; }
span.ins { background:#fff3cd; border-radius:2px; }
span.nl { color:#8b949e; font-size:.8em; padding:0 1px; }
table { border-collapse:collapse; width:100%; background:var(--card); border:1px solid #e4e4e1;
  border-radius:8px; overflow:hidden; }
th, td { padding:6px 8px; border-bottom:1px solid #efefec; font-size:12.5px; text-align:left; vertical-align:top; }
th { background:#fafaf8; font-weight:600; color:var(--mut); font-size:11px; }
td.t { font-family:"Songti SC","Noto Serif SC",serif; font-size:14px; }
td.num { font-variant-numeric:tabular-nums; white-space:nowrap; }
tr.em td.t { color:var(--em); } tr.ok td.t { color:var(--ok); } tr.bad td.t { color:var(--bad); }
img.thumb { display:block; border:1px solid #e4e4e1; border-radius:4px; max-height:64px; }
.ovwrap { position:relative; display:inline-block; background:var(--card); border:1px solid #e4e4e1;
  border-radius:8px; padding:10px; }
.ovwrap img { display:block; }
canvas { position:absolute; left:10px; top:10px; cursor:crosshair; }
.legend { display:flex; gap:14px; font-size:12px; color:var(--mut); margin:8px 2px; flex-wrap:wrap; }
.legend .sw { display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:4px;
  vertical-align:-1px; }
.chk { font-size:12.5px; margin-right:14px; cursor:pointer; }
#tooltip { position:fixed; display:none; background:#24292f; color:#fff; font-size:12px;
  padding:6px 9px; border-radius:6px; max-width:320px; z-index:9; line-height:1.5; }
</style>
</head>
<body>
<header>
  <h1>整页识别对比：本机 ONNX PP-OCRv6（网格切段） vs 线上 PaddleOCR-VL-1.6</h1>
  <div class="sub">康熙字典 @312/318/328/342/349/358 · 金标=kangxi-gold 初校转写 · CER 按去空白编辑距离/金标字数 ·
    本机均值 CER <b id="sum-local"></b>，线上均值 CER <b id="sum-online"></b>（2026-11-16 评估）·
    文本对比含 ⏎ 换行标记参与对齐（金标=行界，本机=切段边界，线上=块界/块内换行），指标卡 CER 仍按去空白口径</div>
</header>
<div class="tabs" id="tabs"></div>
<main>
  <div class="cards" id="cards"></div>
  <div class="note" id="note"></div>
  <div class="modes">
    <div class="mode on" data-m="text">① 整页文本对比</div>
    <div class="mode" data-m="crops">② 切段对照（本机识别端）</div>
    <div class="mode" data-m="overlay">③ 图上叠加</div>
  </div>
  <div class="pane on" id="pane-text">
    <div class="diffcols">
      <div class="diffcard"><h3>本机 ONNX PP-OCRv6 <span class="tag" id="tag-local"></span></h3>
        <div class="lab">金标（红=缺失/被替换；⏎=金标行界）</div><div class="goldline" id="g-local"></div>
        <div class="lab">本机输出（黄=多出/替换；⏎=切段边界）</div><div class="predline" id="p-local"></div></div>
      <div class="diffcard"><h3>线上 PaddleOCR-VL-1.6 <span class="tag" id="tag-online"></span></h3>
        <div class="lab">金标（红=缺失/被替换；⏎=金标行界）</div><div class="goldline" id="g-online"></div>
        <div class="lab">线上输出（黄=多出/替换；⏎=块内换行/块界）</div><div class="predline" id="p-online"></div></div>
    </div>
  </div>
  <div class="pane" id="pane-crops"><table id="croptable"></table></div>
  <div class="pane" id="pane-overlay">
    <div class="legend" id="ovlegend"></div>
    <div style="font-size:12px;color:var(--mut);margin-bottom:6px">
      <label class="chk"><input type="checkbox" id="ly-crop" checked> 本机切段框（按识别正误着色）</label>
      <label class="chk"><input type="checkbox" id="ly-online"> 线上版面块（虚线，含 block 标签）</label>
    </div>
    <div class="ovwrap"><img id="ovimg"><canvas id="ovcv"></canvas></div>
  </div>
</main>
<div id="tooltip"></div>
<script>
const DATA = __DATA__;
let cur = 0;
const $ = s => document.querySelector(s);

function esc(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;'); }
function renderDiff(ops, gold, pred, gEl, pEl){
  const markNl = s => s.replace(/⏎/g, '<span class="nl">⏎</span>');
  let g = '', p = '';
  for (const [t,g0,g1,p0,p1] of ops){
    if (t === 'equal'){ g += markNl(esc(gold.slice(g0,g1))); p += markNl(esc(pred.slice(p0,p1))); }
    else { g += '<span class="del">'+esc(gold.slice(g0,g1))+'</span>';
           p += '<span class="ins">'+esc(pred.slice(p0,p1))+'</span>'; }
  }
  gEl.innerHTML = g || '（空）'; pEl.innerHTML = p || '（空）';
}
function fmtPct(x){ return (x*100).toFixed(1)+'%'; }

function drawOverlay(pg){
  const img = $('#ovimg'), cv = $('#ovcv');
  if (img.complete && img.naturalWidth){ cv.width = img.naturalWidth; cv.height = img.naturalHeight; }
  img.onload = () => {
    cv.width = img.naturalWidth; cv.height = img.naturalHeight;
    const ctx = cv.getContext('2d'); ctx.clearRect(0,0,cv.width,cv.height);
    const s = img.naturalWidth / 1130;
    if ($('#ly-crop').checked){
      for (const c of pg.crops){
        const [x1,y1,x2,y2] = c.bbox;
        ctx.strokeStyle = c.cls==='em' ? '#1a7f37' : c.cls==='ok' ? '#b08514' : '#cf222e';
        ctx.lineWidth = 1.6;
        ctx.strokeRect(x1*s, y1*s, (x2-x1)*s, (y2-y1)*s);
      }
    }
    if ($('#ly-online').checked){
      ctx.setLineDash([5,4]); ctx.lineWidth = 1.8; ctx.strokeStyle = '#0969da';
      ctx.font = '12px sans-serif';
      for (const b of pg.oblocks){
        if (!b.poly) continue;
        ctx.beginPath();
        b.poly.forEach(([x,y],i) => i ? ctx.lineTo(x*s,y*s) : ctx.moveTo(x*s,y*s));
        ctx.closePath(); ctx.stroke();
        const [bx,by] = b.poly[0];
        const label = (b.label||'') + (b.content ? ' ' + b.content.slice(0,6) : '');
        ctx.fillStyle = 'rgba(9,105,218,.85)';
        ctx.fillRect(bx*s, Math.max(0,by*s-14), ctx.measureText(label).width+8, 14);
        ctx.fillStyle = '#fff'; ctx.fillText(label, bx*s+4, Math.max(11,by*s-3));
      }
      ctx.setLineDash([]);
    }
  };
  img.src = 'data:image/jpeg;base64,' + pg.img;
}

function show(i){
  cur = i;
  const pg = DATA.pages[i], m = pg.metrics;
  document.querySelectorAll('.tab').forEach((t,j) => t.classList.toggle('on', j===i));
  const cards = [
    ['本机 CER', fmtPct(m.local.cer), 'em-v'],
    ['线上 CER', fmtPct(m.online.cer), m.online.cer > .15 ? 'bad-v' : ''],
    ['本机长度比', m.local.len_ratio.toFixed(3), ''],
    ['线上长度比', m.online.len_ratio.toFixed(3), m.online.len_ratio < .5 ? 'bad-v' : ''],
    ['本机识别耗时', m.local.recognize_ms/1000 + 's', ''],
    ['线上耗时(缓存实测)', m.online.measured_s + 's', ''],
    ['切段数', m.crops, ''],
    ['金标字数', m.gold_len, ''],
  ];
  $('#cards').innerHTML = cards.map(c =>
    `<div class="card"><div class="k">${c[0]}</div><div class="v ${c[2]}">${c[1]}</div></div>`).join('');
  $('#note').textContent = '拼装顺序金标验证：' + (m.assembly_gold_exact ? '6/6 逐字一致 ✓' : '不一致') +
    (pg.page===358 ? ' · 线上灾难失败：整页仅返回单字「寧」+页脚' : '') +
    (pg.page===342 ? ' · 线上版面分类混乱（doc_title=人部、表头杂质并入正文列）' : '');
  $('#tag-local').textContent = 'CER ' + fmtPct(m.local.cer);
  $('#tag-online').textContent = 'CER ' + fmtPct(m.online.cer);
  renderDiff(pg.ops_local, pg.gold, pg.local, $('#g-local'), $('#p-local'));
  renderDiff(pg.ops_online, pg.gold, pg.online, $('#g-online'), $('#p-online'));

  $('#croptable').innerHTML = '<tr><th>#</th><th>切块</th><th>类别</th><th>金标</th><th>本机识别</th>'+
    '<th>CER</th><th>识别置信</th><th>耗时</th></tr>' + pg.crops.map(c =>
    `<tr class="${c.cls}"><td class="num">${c.n}</td>
     <td><img class="thumb" src="data:image/jpeg;base64,${c.thumb}"></td>
     <td>${c.kind}</td><td class="t">${esc(c.gold)}</td><td class="t">${esc(c.pred)||'（空）'}</td>
     <td class="num">${(c.cer*100).toFixed(1)}%</td><td class="num">${c.conf.toFixed(2)}</td>
     <td class="num">${c.ms}ms</td></tr>`).join('');

  $('#ovlegend').innerHTML =
    `<span><span class="sw" style="background:#1a7f37"></span>本机切段·全对</span>`+
    `<span><span class="sw" style="background:#b08514"></span>部分对（CER≤30%）</span>`+
    `<span><span class="sw" style="background:#cf222e"></span>错误（CER&gt;30%）</span>`+
    `<span><span class="sw" style="border:2px dashed #0969da"></span>线上版面块</span>`;
  drawOverlay(pg);
}

$('#tabs').innerHTML = DATA.pages.map((p,i) =>
  `<div class="tab" onclick="show(${i})">@${p.page}</div>`).join('');
$('#sum-local').textContent = fmtPct(DATA.summary.local_mean_cer);
$('#sum-online').textContent = fmtPct(DATA.summary.online_mean_cer);
document.querySelectorAll('.mode').forEach(mo => mo.onclick = () => {
  document.querySelectorAll('.mode').forEach(x => x.classList.remove('on'));
  mo.classList.add('on');
  document.querySelectorAll('.pane').forEach(p => p.classList.remove('on'));
  $('#pane-' + mo.dataset.m).classList.add('on');
  if (mo.dataset.m === 'overlay') drawOverlay(DATA.pages[cur]);
});
$('#ly-crop').onchange = $('#ly-online').onchange = () => drawOverlay(DATA.pages[cur]);
const cv = $('#ovcv'), tip = $('#tooltip');
cv.onmousemove = e => {
  const pg = DATA.pages[cur], r = cv.getBoundingClientRect();
  const x = (e.clientX - r.left) * 1130 / r.width, y = (e.clientY - r.top) * 1130 / r.width;
  let hit = null;
  for (const c of pg.crops){
    const [x1,y1,x2,y2] = c.bbox;
    if (x1 <= x && x <= x2 && y1 <= y && y <= y2){ hit = c; break; }
  }
  if (hit){
    tip.style.display = 'block';
    tip.style.left = (e.clientX+14)+'px'; tip.style.top = (e.clientY+14)+'px';
    tip.innerHTML = `<b>${hit.id}</b>（${hit.kind}，CER ${(hit.cer*100).toFixed(1)}%）<br>金标：${esc(hit.gold)}<br>本机：${esc(hit.pred)||'（空）'}`;
  } else tip.style.display = 'none';
};
cv.onmouseleave = () => tip.style.display = 'none';
show(0);
</script>
</body>
</html>
'''


if __name__ == '__main__':
    main()
