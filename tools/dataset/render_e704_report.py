#!/usr/bin/env python3
"""Render the E704 report figures from the saved scan and production fonts."""
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/research/figures/e704'
FONTS = ROOT / 'guji-preview-grid/public/fonts'


def font(size, plane=0):
    return ImageFont.truetype(str(FONTS / f'guji-plane{plane}.ttf'), size)


def text(draw, xy, value, size, fill='#222222'):
    x, y = xy
    for c in value:
        draw.text((x, y), c, font=font(size, 2 if ord(c) > 0xffff else 0), fill=fill)
        x += size


def glyph(ch):
    image = Image.new('L', (320, 320), 255)
    ImageDraw.Draw(image).text((160, 160), ch,
        font=font(250, 2 if ord(ch) > 0xffff else 0), anchor='mm', fill=0)
    return image.crop(ImageOps.invert(image).getbbox()).convert('RGB')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (1120, 360), '#f7f5f0')
    draw = ImageDraw.Draw(image)
    items = [('373 页原刻', Image.open(OUT/'scan-original.png'), '上下横，中间心与支'),
             ('补录 U+E704', glyph('\ue704'), '小字宋体 · PUA'),
             ('字头 U+20139', glyph('𠄹'), '中间敂：句与攵'),
             ('亟 U+4E9F', glyph('亟'), '释文字，不是所引字形')]
    for i, (title, source, caption) in enumerate(items):
        x = i * 280
        draw.rectangle((x+8, 8, x+272, 352), fill='white')
        draw.text((x+140, 30), title, font=font(21), fill='#222222', anchor='mm')
        source = source.convert('RGB')
        source.thumbnail((225, 235))
        if i == 0:
            source = source.resize((225, 207))
        image.paste(source, (x+140-source.width//2, 68+(235-source.height)//2))
        draw.text((x+140, 330), caption, font=font(17), fill='#555555', anchor='mm')
    image.save(OUT/'result-comparison.png')

    image = Image.new('RGB', (1080, 365), 'white')
    draw = ImageDraw.Draw(image)
    titles = ['上横（取自𠄹）', '下横（取自𠄹）', '完整心', '支：接横处去衬线', '最终部件布局']
    for i, name in enumerate(['source-0', 'source-1', 'source-2', 'source-3', 'components']):
        png = OUT/f'{name}.png'
        subprocess.run(['rsvg-convert', '-w', '200', '-h', '200', str(OUT/f'{name}.svg'), '-o', str(png)], check=True)
        source = Image.open(png).convert('RGBA')
        image.paste(source, (i*216+8, 65), source)
        text(draw, (i*216+8, 20), titles[i], 17)
    draw.text((20, 305), '蓝：上下横   绿：心   红：支；在上横与支竖连接处合并轮廓。', font=font(22), fill='#333333')
    image.save(OUT/'component-sources.png')

    image = Image.new('RGB', (1180, 430), 'white')
    draw = ImageDraw.Draw(image)
    for i, size in enumerate([16, 24, 32, 48]):
        y = 25+i*94
        draw.text((25, y), f'{size}px', font=font(22), fill='#555555')
        text(draw, (125, y), '亟字。【風雅廣逸】又書作\ue704。', size)
    for i, ch in enumerate('又書作\ue704。'):
        text(draw, (1040, 20+i*65), ch, 48, '#8d3932' if ch == '\ue704' else '#222222')
    image.save(OUT/'small-text-context.png')
    print(OUT)


if __name__ == '__main__':
    main()
