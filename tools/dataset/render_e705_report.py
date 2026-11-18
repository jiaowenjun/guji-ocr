#!/usr/bin/env python3
"""Render U+E705 report figures from frozen components and a selected font."""
import argparse
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFont, ImageOps
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[2]
FONTS = ROOT / 'guji-preview-grid/public/fonts'
OUT = ROOT / 'docs/research/figures/e705'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font', type=Path, default=FONTS/'guji-plane0.ttf')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    label = ImageFont.truetype(str(FONTS/'guji-plane0.ttf'), 19)

    def glyph(cp, path):
        im = Image.new('L', (320, 320), 255)
        ImageDraw.Draw(im).text((160, 160), chr(cp),
            font=ImageFont.truetype(str(path), 240), fill=0, anchor='mm')
        return im.crop(ImageOps.invert(im).getbbox()).convert('RGB')

    im = Image.new('RGB', (1120, 360), '#f7f5f0')
    d = ImageDraw.Draw(im)
    items = [('407页原刻', Image.open(ROOT/'tools/dataset/font-sources/e705-scan-original.png').resize((206,240)), '左口，右部两层四支'),
             ('U+E705 新补宋体', glyph(0xE705, args.font), '口旁 + 完整 U+200B9'),
             ('U+2A88A', glyph(0x2A88A, FONTS/'guji-plane2.ttf'), '右上有围框，不能代替'),
             ('既有 U+E701', glyph(0xE701, args.font), '分支不同，保留原字位')]
    for i, (title, picture, caption) in enumerate(items):
        x=i*280
        d.rectangle((x+6,6,x+274,354),fill='white')
        d.text((x+140,28),title,font=label,fill='black',anchor='mm')
        picture=picture.copy(); picture.thumbnail((235,245))
        im.paste(picture,(x+140-picture.width//2,60+(245-picture.height)//2))
        d.text((x+140,328),caption,font=label,fill='#555555',anchor='mm')
    im.save(OUT/'result-comparison.png')

    recipe=json.loads((ROOT/'tools/dataset/font-sources/e705-songti-v1.json').read_text())
    # Rebuild illustrations from tracked recipe and fonts, without authoring caches.
    svgs = {}
    for i, part in enumerate(recipe['components']):
        with TTFont(FONTS/part['source_font']) as donor:
            gs = donor.getGlyphSet()
            whole = SVGPathPen(gs)
            gs[donor.getBestCmap()[ord(part['source_char'])]].draw(whole)
            svgs[f'source-{i}'] = (
                f'<path d="{whole.getCommands()}" fill="#dad7d1"/>'
                f'<path d="{part["source_path"]}" fill="{part["color"]}"/>')
    svgs['components'] = ''.join(
        f'<path d="{part["path"]}" fill="{part["color"]}"/>'
        for part in recipe['components'])
    for name, paths in svgs.items():
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
               '<g transform="matrix(1 0 0 -1 0 870)">'+paths+'</g></svg>')
        (OUT/(name+'.svg')).write_text(svg)
        subprocess.run(['rsvg-convert','-w','270','-h','270',str(OUT/(name+'.svg')),'-o',str(OUT/(name+'.png'))],check=True)
    im=Image.new('RGB',(1000,380),'white');d=ImageDraw.Draw(im)
    for i,(name,title) in enumerate([('source-0','吹：取口旁两条轮廓'),('source-1','U+200B9：完整五轮廓'),('components','两部件分别整体定位')]):
        x=i*330
        d.text((x+165,28),title,font=label,fill='black',anchor='mm')
        source=Image.open(OUT/(name+'.png')).convert('RGBA');im.paste(source,(x+30,65),source)
    d.text((30,350),'蓝色：口旁（含内白）  绿色：完整右部；无切笔、重绘或镜像。',font=label,fill='#555555')
    im.save(OUT/'component-sources.png')

    im=Image.new('RGB',(1180,450),'white');d=ImageDraw.Draw(im)
    for i,size in enumerate([16,24,32,48]):
        y=25+i*100
        d.text((25,y),f'{size}px',font=label,fill='#555555')
        x=125
        ft=ImageFont.truetype(str(args.font),size)
        for c in '【註】他音\ue705。言禽獸僵死交相積也。':
            d.text((x,y),c,font=ft,fill='#a63832' if c=='\ue705' else '#222222');x+=size
    for i,c in enumerate('他音\ue705。'):
        d.text((1080,25+i*85),c,font=ImageFont.truetype(str(args.font),64),fill='#a63832' if c=='\ue705' else '#222222')
    im.save(OUT/'small-text-context.png')
    print(OUT)


if __name__ == '__main__':
    main()
