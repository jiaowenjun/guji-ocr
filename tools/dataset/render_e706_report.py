#!/usr/bin/env python3
"""Render report figures for the small-font U+E706 glyph."""
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[2]
FONT = ROOT / 'guji-preview-grid/public/fonts/guji-plane0.ttf'
LARGE = ROOT / 'guji-preview-grid/public/fonts/guji-large.ttf'
RECIPE = ROOT / 'tools/dataset/font-sources/e706-songti-v1.json'
SCAN = ROOT / 'tools/dataset/font-sources/e706-scan-original.png'
OUT = ROOT / 'docs/research/figures/e706'


def label_font(size):
    candidates = [
        Path('/System/Library/Fonts/PingFang.ttc'),
        Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf'),
    ]
    path = next((p for p in candidates if p.exists()), None)
    return ImageFont.truetype(str(path), size) if path else ImageFont.load_default()


def glyph_image(char, font_path, pixels=230, canvas=270):
    image = Image.new('RGB', (canvas, canvas), 'white')
    font = ImageFont.truetype(str(font_path), pixels)
    ImageDraw.Draw(image).text((canvas // 2, canvas // 2), char, font=font,
                               fill='#171717', anchor='mm')
    return image


def result_comparison():
    image = Image.new('RGB', (1080, 390), '#f8f6f1')
    draw = ImageDraw.Draw(image)
    title = label_font(22)
    scan = Image.open(SCAN).convert('RGB')
    scan.thumbnail((250, 250))
    items = [
        ('421页原刻', scan),
        ('小字 U+343A', glyph_image('㐺', FONT)),
        ('新补 U+E706', glyph_image('\ue706', FONT)),
        ('大字 U+343A', glyph_image('㐺', LARGE)),
    ]
    for index, (text, item) in enumerate(items):
        x = 20 + index * 265
        image.paste(item, (x + (250 - item.width) // 2, 70 + (250 - item.height) // 2))
        draw.text((x + 125, 35), text, font=title, fill='#222', anchor='mm')
    image.save(OUT / 'result-comparison.png')


def component_sources(recipe):
    colors = ['#2563a6', '#258054', '#a33d35']
    paths = ''.join(
        f'<path d="{part["path"]}" fill="{color}"/>'
        for part, color in zip(recipe['components'], colors)
    )
    with TTFont(FONT) as font:
        glyph_set = font.getGlyphSet()
        source = SVGPathPen(glyph_set)
        glyph_set[font.getBestCmap()[0x343A]].draw(source)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="520" viewBox="0 0 1200 520">
      <rect width="1200" height="520" fill="#f8f6f1"/>
      <text x="300" y="42" text-anchor="middle" font-size="24">U+343A donor</text>
      <text x="900" y="42" text-anchor="middle" font-size="24">U+E706: three complete side-person contours</text>
      <g transform="translate(60 470) scale(.47 -.47)"><path d="{source.getCommands()}" fill="#d2cdc4"/></g>
      <g transform="translate(660 470) scale(.47 -.47)">{paths}</g>
    </svg>'''
    with tempfile.NamedTemporaryFile('w', suffix='.svg', delete=False) as source_file:
        source_file.write(svg)
        source_path = source_file.name
    subprocess.run(['rsvg-convert', source_path, '-o', str(OUT / 'component-sources.png')], check=True)


def small_text_context():
    image = Image.new('RGB', (1120, 430), '#f8f6f1')
    draw = ImageDraw.Draw(image)
    title = label_font(22)
    draw.text((30, 25), 'U+E706 小字号与横竖排', font=title, fill='#222')
    for index, size in enumerate([16, 24, 32, 48]):
        x = 40 + index * 190
        font = ImageFont.truetype(str(FONT), size)
        draw.text((x, 90), f'{size}px', font=label_font(18), fill='#555')
        draw.text((x, 145), '\ue706', font=font, fill='#9c2f2b')
        draw.text((x + 55, 145), '㐺', font=font, fill='#222')
    sentence = '象形。亦作\ue706。'
    font = ImageFont.truetype(str(FONT), 42)
    x = 35
    for char in sentence:
        draw.text((x, 270), char, font=font,
                  fill='#9c2f2b' if char == '\ue706' else '#222')
        x += 55
    for index, char in enumerate('亦作\ue706。'):
        draw.text((920, 75 + index * 62), char, font=font,
                  fill='#9c2f2b' if char == '\ue706' else '#222')
    image.save(OUT / 'small-text-context.png')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    recipe = json.loads(RECIPE.read_text())
    result_comparison()
    component_sources(recipe)
    small_text_context()
    print(f'Wrote E706 report figures to {OUT}')


if __name__ == '__main__':
    main()
