#!/usr/bin/env python3
"""Render report figures for the small-font U+E707 glyph."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[2]
FONT = ROOT / 'guji-preview-grid/public/fonts/guji-plane0.ttf'
RECIPE = ROOT / 'tools/dataset/font-sources/e707-songti-v3.json'
SCAN = ROOT / 'tools/dataset/font-sources/e707-scan-original.png'
PAGE = Path('/Volumes/WD-2T/guji-ocr/raw/kangxizidian/pages/0427.jpg')
OUT = ROOT / 'docs/research/figures/e707'


def label_font(size):
    candidates = [
        Path('/System/Library/Fonts/PingFang.ttc'),
        Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf'),
    ]
    path = next((item for item in candidates if item.exists()), None)
    return ImageFont.truetype(str(path), size) if path else ImageFont.load_default()


def glyph_image(char, pixels=230, canvas=270):
    image = Image.new('RGB', (canvas, canvas), 'white')
    font = ImageFont.truetype(str(FONT), pixels)
    ImageDraw.Draw(image).text((canvas // 2, canvas // 2), char, font=font,
                               fill='#171717', anchor='mm')
    return image


def result_comparison():
    image = Image.new('RGB', (1080, 390), '#f8f6f1')
    draw = ImageDraw.Draw(image)
    title = label_font(22)
    scan = Image.open(SCAN).convert('RGB')
    scan = scan.crop((18, 16, 64, 69)).resize((230, 265))
    items = [
        ('427页原刻', scan),
        ('标准 U+4F3A 伺', glyph_image('伺')),
        ('新补 U+E707', glyph_image('\ue707')),
        ('相关 U+8997 覗', glyph_image('覗')),
    ]
    for index, (text, item) in enumerate(items):
        x = 20 + index * 265
        image.paste(item, (x + (250 - item.width) // 2, 70 + (270 - item.height) // 2))
        draw.text((x + 125, 35), text, font=title, fill='#222', anchor='mm')
    image.save(OUT / 'result-comparison.png')


def component_sources(recipe):
    image = Image.new('RGB', (1080, 390), '#f8f6f1')
    draw = ImageDraw.Draw(image)
    title = label_font(22)
    draw.text((175, 35), '供体 U+476D（取左貝旁）', font=title, fill='#222', anchor='mm')
    draw.text((440, 35), '供体 飼（取右司旁）', font=title, fill='#222', anchor='mm')
    draw.text((785, 35), 'U+E707：完整偏旁原位拼合', font=title, fill='#222', anchor='mm')
    image.paste(glyph_image('䝭'), (40, 70))
    image.paste(glyph_image('飼'), (305, 70))

    # Render the reviewed production glyph, then color complete contours by donor.
    with TTFont(FONT, recalcTimestamp=False) as font:
        name = font.getBestCmap()[0xE707]
        glyph = font['glyf'][name]
        coords, end_points, flags = glyph.getCoordinates(font['glyf'])
        start = 0
        scale, origin_x, baseline = .245, 650, 305
        colors = ['#2563a6'] * 6 + ['#258054'] * 4
        for end, color in zip(end_points, colors):
            points = []
            for index in range(start, end + 1):
                x, y = coords[index]
                points.append((origin_x + x * scale, baseline - y * scale))
            if points:
                draw.line(points + [points[0]], fill=color, width=3, joint='curve')
            start = end + 1
    draw.text((785, 355), f'{len(recipe["components"])} 个完整偏旁／10 条原生轮廓／恒等变换',
              font=label_font(18), fill='#555', anchor='mm')
    image.save(OUT / 'component-sources.png')


def small_text_context():
    image = Image.new('RGB', (1120, 430), '#f8f6f1')
    draw = ImageDraw.Draw(image)
    draw.text((30, 25), 'U+E707 小字号与横竖排', font=label_font(22), fill='#222')
    for index, size in enumerate([16, 24, 32, 48]):
        x = 40 + index * 190
        font = ImageFont.truetype(str(FONT), size)
        draw.text((x, 90), f'{size}px', font=label_font(18), fill='#555')
        draw.text((x, 145), '\ue707', font=font, fill='#9c2f2b')
        draw.text((x + 55, 145), '伺', font=font, fill='#222')
    sentence = '音斯。義同。別作\ue707。'
    font = ImageFont.truetype(str(FONT), 42)
    x = 35
    for char in sentence:
        draw.text((x, 270), char, font=font,
                  fill='#9c2f2b' if char == '\ue707' else '#222')
        x += 55
    for index, char in enumerate('別作\ue707。'):
        draw.text((920, 70 + index * 65), char, font=font,
                  fill='#9c2f2b' if char == '\ue707' else '#222')
    image.save(OUT / 'small-text-context.png')


def page_context():
    page = Image.open(PAGE).convert('RGB')
    # sips target crop is the source rectangle (84, 575, 156, 647).
    left, top, right, bottom = 20, 500, 370, 790
    crop = page.crop((left, top, right, bottom))
    draw = ImageDraw.Draw(crop)
    draw.rectangle((84 - left - 3, 575 - top - 3, 156 - left + 3, 647 - top + 3),
                   outline='#c43b32', width=4)
    crop.resize((700, 580)).save(OUT / 'page-context.png')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    recipe = json.loads(RECIPE.read_text())
    result_comparison()
    component_sources(recipe)
    small_text_context()
    page_context()
    print(f'Wrote E707 report figures to {OUT}')


if __name__ == '__main__':
    main()
