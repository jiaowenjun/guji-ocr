#!/usr/bin/env python3
"""Rebuild the small, versioned illustrations in docs/gj-syntax-guide.md.

Uses the production .gj parser/grid geometry and the existing Pillow exporter.
Full-page intermediates stay in var/; only teaching figures enter docs/.
Requires Node >= 22.18 with TS support, Pillow and fontTools.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/dataset'))
import ocr_render  # noqa: E402

OUT = ROOT / 'docs/figures/gj-syntax'
CACHE = ROOT / 'var/gj-manual'
UNIT = 40
PAPER = '#fcf7ec'
INK = '#252b2b'
ACCENT = '#a34425'
MUTED = '#526566'
FONTS = ROOT / 'guji-preview-grid/public/fonts'
LABEL_FONT = FONTS / 'guji-plane0.ttf'
PAGE_NUMBERS = [312, 328, 336, 339, 340]
DEMOS = ['甲乙\n丙丁', '甲乙\n\n丙丁', '#甲乙\n丙丁', '甲乙#丙\n丁戊', '#*甲\n乙*丙']


def font(size):
    return ImageFont.truetype(str(LABEL_FONT), size)


def label(im, xy, text, size=23, color=INK):
    ImageDraw.Draw(im).text(xy, text, font=font(size), fill=color, spacing=9)


def card(title, subtitle, width, height):
    im = Image.new('RGB', (width, height), PAPER)
    label(im, (30, 22), title, 31)
    label(im, (30, 70), subtitle, 19, MUTED)
    ImageDraw.Draw(im).line((30, 108, width-30, 108), fill='#d9cdbc', width=2)
    return im


def paste(im, crop, xy, scale=1):
    if scale != 1:
        crop = crop.resize((round(crop.width*scale), round(crop.height*scale)), Image.Resampling.LANCZOS)
    im.paste(crop, xy)


def save(im, name, sources):
    im.save(OUT / f'{name}.png', optimize=True)
    evidence['figures'].append({'file': f'{name}.png', 'sources': sources,
                               'size': list(im.size)})


def box(page, bounds):
    """Crop the already rendered original page, using production grid coordinates."""
    return images[page].crop(tuple(round(20+UNIT*v) for v in bounds))


def band(page, index, bottom=24):
    x = layouts[page]['bands'][index-1]['grid_bbox'][0]
    return box(page, [x, 0, x+2, bottom])


def note(im, x, y, title, detail):
    label(im, (x, y), title, 25, ACCENT)
    label(im, (x, y+40), detail, 22)


OUT.mkdir(parents=True, exist_ok=True)
CACHE.mkdir(parents=True, exist_ok=True)
manifest = json.loads((ROOT / 'kangxi-gold/manifest.json').read_text())
records = {p['page']: p for p in manifest['pages']}
for page in PAGE_NUMBERS:
    if records[page]['status'] not in ('first', 'final'):
        raise ValueError(f'Example {page} is not proofread')

js = """
import {readFileSync} from 'node:fs';
import {exportLayout} from './tools/dataset/export_ocr_layout.mjs';
const req=JSON.parse(readFileSync(0,'utf8'));
const pages=req.pages.map(n=>exportLayout(readFileSync(`kangxi-gold/annotations/${String(n).padStart(4,'0')}.gj`,'utf8'),n));
const demos=req.demos.map((s,i)=> {
 const count=s.split(/\\n\\n/).length;
 return exportLayout(`@${9000+i}\\n\\n${s}\\n\\n`+Array(8-count).fill('@blank').join('\\n\\n')+'\\n',9000+i);
});
process.stdout.write(JSON.stringify([...pages,...demos]));
"""
result = subprocess.run(['node', '--input-type=module', '-e', js], cwd=ROOT,
                        input=json.dumps({'pages': PAGE_NUMBERS, 'demos': DEMOS}),
                        capture_output=True, text=True, check=True)
layouts = {p['page']: p for p in json.loads(result.stdout)}
ocr_render.STYLE.update(margin=[20, 20, 20, 20], background=PAPER)
fonts = ocr_render.Fonts(FONTS)
images = {}
for page, layout in layouts.items():
    output = CACHE / f'{page:04}.png'
    ocr_render.render(layout, layout['cols']*UNIT+40, 24*UNIT+40, fonts, output)
    images[page] = Image.open(output).convert('RGB')

evidence = {
    'grammar': 'gj/2', 'renderer': 'production gj2ir + layout3 + projectBooks; ocr_render.py',
    'note': 'Teaching crops of rendered transcription, not scans or browser pixel screenshots. Blue labels/rules are explanatory.',
    'style': dict(ocr_render.STYLE),
    'pages': [{'page': p, 'status': records[p]['status'],
               'path': f'kangxi-gold/annotations/{p:04}.gj',
               'sha256': layouts[p]['source_sha256']} for p in PAGE_NUMBERS],
    'synthetic_examples': DEMOS,
    'figures': [],
}

# A complete authentic page, with teaching column numbers and rules.
im = card('把一页看成八条排字槽', '@312 · 每个段落是一大列；先读右侧，再向左移。', 760, 1160)
paste(im, box(312, [0, 0, 16, 24]), (60, 164))
d = ImageDraw.Draw(im)
for i in range(8):
    x = 60+(7-i)*80
    label(im, (x+27, 124), str(i+1), 25, ACCENT)
    if i:
        d.line((x+80, 164, x+80, 1124), fill='#c4cfcc', width=1)
d.rectangle((59, 163, 700, 1124), outline='#8c9e98', width=1)
save(im, '01-page-and-columns', [{'page': 312, 'bands': [1, 8]}])

# Exact title columns, enlarged; blank slots outlined as a teaching aid.
im = card('空一大格，就是放一枚大空铅', '@312 · 下面三列取自原页，蓝框标出 * 占据的空位。', 900, 740)
for col, text in enumerate(['#康熙字典', '#*子集上', '#**一部']):
    x = 80+col*290
    label(im, (x-30, 130), text, 24)
    paste(im, band(312, col+1, 8), (x+20, 190), 1.5)
    for gap in range(col):
        ImageDraw.Draw(im).rectangle((x+21, 191+gap*120, x+138, 308+gap*120), outline='#7b9ba2', width=2)
    label(im, (x-10, 690), f'{col} 个大字空位', 21, MUTED)
save(im, '02-large-spaces', [{'page': 312, 'lines': [3, 7], 'bands': [1, 3]}])

# The original mixed-size band, with its four stacked segments called out.
im = card('一条大列里，交替排大字和小字', '@312 第 4 大列 · 所有换行都仍在同一段内。', 800, 1155)
paste(im, band(312, 4), (625, 145))
for y, title, detail in [
    (145, '#一，', '换大字活字：一，占一个大字格。'),
    (235, '古文：', '换行恢复小字；单独一小列居中。'),
    (315, '#弌', '再次换成大字活字。'),
    (420, '两行释文', '两小列并排：右列先读，左列后读。\n书名框围住文字，不改变字号。'),
]:
    note(im, 32, y, title, detail)
    ImageDraw.Draw(im).line((535, y+15, 613, y+15), fill='#b3a792', width=2)
label(im, (32, 950), '大字：2 × 2 小格\n小字：1 × 1 小格\n整条大列宽 2 小格、高 24 小格', 23, MUTED)
save(im, '03-mixed-sizes', [{'page': 312, 'lines': [9, 13], 'band': 4}])

# Deliberately tiny synthetic examples distinguish newline, blank line and # scope.
im = card('换行、空行、行中 #：摆出来看', '教学自造例 · 淡蓝线是格子辅助线，不是 .gj 正文。', 1120, 640)
for i, (title, source) in enumerate(zip(['换小列', '另起大列', '大字后换小字', '行中改用大字'], DEMOS[:4])):
    x = 25+i*280
    label(im, (x, 130), title, 25, ACCENT)
    label(im, (x, 175), source.replace('\n\n', '\n[空行]\n'), 25)
    bounds = [12, 0, 16, 3] if i == 1 else [14, 0, 16, 6]
    crop = box(9000+i, bounds)
    draw = ImageDraw.Draw(crop)
    for xx in range(0, crop.width, UNIT):
        draw.line((xx, 0, xx, crop.height), fill='#c4cfcc')
    for yy in range(0, crop.height, UNIT):
        draw.line((0, yy, crop.width, yy), fill='#c4cfcc')
    draw.rectangle((0, 0, crop.width-1, crop.height-1), outline='#c4cfcc')
    paste(im, crop, (x+45, 330))
save(im, '04-line-breaks', [{'synthetic': DEMOS[:4]}])

# Direct original crops, preserving circle ligatures and all vertical positions.
im = card('圈内两个字，合占一个大字格', '@328、@336 · 圈只套住括号里的字，后面的字头仍是大字。', 900, 740)
selections = [(328, [10, 10, 12, 14], '增 + 字头'),
              (328, [10, 17, 12, 21], '七 + 字头'),
              (336, [10, 13, 12, 19], '十一 + 增 + 字头')]
for i, (page, bounds, title) in enumerate(selections):
    x = 40+i*290
    label(im, (x, 135), title, 25, ACCENT)
    paste(im, box(page, bounds), (x+60, 195), 1.7)
label(im, (40, 660), '十一上下紧贴、压入同一格；它后面的「增」另占一格。', 24)
save(im, '05-circled-type', [{'page': 328, 'lines': [14, 17]}, {'page': 336, 'line': 18}])

# Two real adjoining bands, cropped to the end and start of one book title.
im = card('书名到了列尾，边框随文字接到下一列', '@312 · 【史記·儒 / 空行 / 林傳】；图中右侧先读。', 900, 530)
label(im, (530, 132), '第 5 大列末尾', 25, ACCENT)
paste(im, box(312, [6, 20, 7, 24]), (610, 190), 1.6)
label(im, (70, 132), '第 6 大列开头', 25, ACCENT)
paste(im, box(312, [5, 0, 6, 4]), (150, 190), 1.6)
label(im, (320, 265), '下一大列 ←', 25, MUTED)
label(im, (315, 310), '书名框连接处开口', 21, MUTED)
save(im, '06-book-continuation', [{'page': 312, 'lines': [16, 18], 'bands': [5, 6]}])

# Same glyph engine, explicit blank size comparison.
im = card('同一个 *，跟随当前字号占格', '教学自造例：#*甲 换行 乙*丙；蓝框圈出两个空位。', 790, 600)
crop = box(9004, [14, 0, 16, 7])
draw = ImageDraw.Draw(crop)
draw.rectangle((1, 1, 78, 78), outline='#7b9ba2', width=2)
draw.rectangle((21, 201, 58, 238), outline='#7b9ba2', width=2)
paste(im, crop, (590, 150), 1.4)
note(im, 32, 160, '# 后的 *', '大字空位：宽 2 小格、高 2 小格。')
note(im, 32, 350, '换行后的 *', '小字空位：宽 1 小格、高 1 小格。')
save(im, '07-space-sizes', [{'synthetic': DEMOS[4]}])

# A genuine page with four explicit blank bands; reduced to stay compact.
im = card('整列留白，也是一条有位置的排字槽', '@336 · 第 5、6、7、8 大列各写一个独占段落的 @blank。', 760, 1160)
paste(im, box(336, [0, 0, 16, 24]), (60, 164))
d = ImageDraw.Draw(im)
for i in range(8):
    x = 60+(7-i)*80
    label(im, (x+27, 124), str(i+1), 25, ACCENT)
    d.rectangle((x, 164, x+80, 1124), outline='#c4cfcc', width=1)
    if i >= 4:
        label(im, (x+25, 590), '留\n白', 25, MUTED)
save(im, '08-blank-columns', [{'page': 336, 'lines': [25, 31], 'bands': [5, 8]}])

im = card('书名可以跨页：前页开口，后页续框', '@339 → @340 · 【崔豹古今註】在页缝两侧延续。右图先读。', 900, 540)
label(im, (540, 132), '@339 页末', 25, ACCENT)
paste(im, box(339, [0, 21, 1, 24]), (610, 190), 1.6)
label(im, (70, 132), '@340 页首', 25, ACCENT)
paste(im, box(340, [15, 0, 16, 5]), (150, 190), 1.6)
label(im, (330, 260), '翻页 ←', 27, MUTED)
save(im, '09-page-continuation', [{'page': 339, 'line': 32}, {'page': 340, 'line': 3}])

for name in ocr_render.FONT_NAMES:
    evidence.setdefault('fonts', {})[name] = hashlib.sha256((FONTS/name).read_bytes()).hexdigest()
(OUT / 'sources.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n')
print(f'Wrote {len(evidence["figures"])} figures and sources.json to {OUT.relative_to(ROOT)}')
