"""Deterministic raster backend for the production Guji grid layout.

No system font fallback or UI screenshots. Boxes use output pixel coordinates.
The export has its own versioned raster style, not browser pixel parity.
"""
from __future__ import annotations

import copy
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

FONT_NAMES = ('guji-large.ttf', 'guji-plane0.ttf', 'guji-plane2.ttf', 'guji-planef.ttf')
STYLE = {'version': 2,
         'ink': '#1c1c1c', 'small_scale': .8, 'large_scale': 1.8, 'circle_scale': 1.5,
         'supersample': 2, 'rules': False}


class Fonts:
    def __init__(self, directory: Path):
        self.directory = directory
        self.cmaps = {}
        self.loaded = {}
        for name in FONT_NAMES:
            with TTFont(directory / name, lazy=True) as font:
                self.cmaps[name] = font.getBestCmap()

    def font(self, ch, size_class, size):
        stack = FONT_NAMES[:1] if size_class == 'large' else FONT_NAMES[1:]
        name = next((n for n in stack if ord(ch) in self.cmaps[n]), None)
        if name is None:
            raise ValueError(f'Missing {size_class} glyph U+{ord(ch):04X}')
        key = (name, max(1, round(size)))
        if key not in self.loaded:
            self.loaded[key] = ImageFont.truetype(str(self.directory / name), key[1], layout_engine=ImageFont.Layout.BASIC)
        return self.loaded[key], name


def pixel_annotation(layout, width, height, domain, mapper):
    annotation = {k: copy.deepcopy(layout[k]) for k in (
        'page', 'text', 'transcription', 'bands', 'regions', 'glyphs', 'gaps', 'decorations')}
    annotation.update(schema='guji-ocr/1', domain=domain, width=width, height=height,
                      source_sha256=layout['source_sha256'],
                      coordinate_system='pixel-xyxy-half-open',
                      bbox_type='layout-cell', reading_order=[r['id'] for r in layout['regions']],
                      glyph_reading_order=[g['id'] for g in layout['glyphs']],
                      profile=layout['ir']['meta']['profile'],
                      layout=layout['config'],
                      layout_preset=layout['ir']['pages'][0].get('layoutPreset', layout['ir']['meta'].get('layoutPreset')),
                      overlays=layout['ir']['overlays'])
    for group in ('bands', 'regions', 'glyphs', 'gaps', 'decorations'):
        for obj in annotation[group]:
            band_id = obj['id'] if group == 'bands' else obj['band_id']
            raw = mapper(band_id, obj['grid_bbox'])
            box = [max(0., min(float(width if i % 2 == 0 else height), float(v)))
                   for i, v in enumerate(raw)]
            obj['bbox'] = [round(v, 3) for v in box]
            obj['clipped'] = any(abs(a-b) > .01 for a, b in zip(raw, box))
            if box[2] <= box[0] or box[3] <= box[1]:
                raise ValueError(f"Empty/outside box: {layout['page']} {obj['id']}")
    return annotation


def render(layout, width, height, fonts: Fonts, destination: Path):
    scan = layout['scan']
    left, top, right, bottom = (scan['margin'][k] for k in ('left', 'top', 'right', 'bottom'))
    style = {**STYLE, 'margin': [left, top, right, bottom], 'background': scan['background']}
    if left + right >= width or top + bottom >= height:
        raise ValueError('Scan margins leave no content area')
    ux = (width-left-right)/layout['cols']; uy = (height-top-bottom)/layout['rows']
    mapper = lambda _band, b: [left+b[0]*ux, top+b[1]*uy, left+b[2]*ux, top+b[3]*uy]
    annotation = pixel_annotation(layout, width, height, 'synthetic', mapper)
    annotation.update(geometry_status='generated', renderer='guji-grid-pillow/1', style=style,
                      content_bbox=[left, top, width-right, height-bottom])
    s = STYLE['supersample']
    canvas = Image.new('RGB', (width*s, height*s), style['background'])
    draw = ImageDraw.Draw(canvas)
    ink = STYLE['ink']
    draw.rectangle(tuple(v*s for v in annotation['content_bbox']), outline=ink, width=s)
    for g in annotation['glyphs']:
        x1, y1, x2, y2 = g['bbox']
        cx, cy = (x1+x2)*s/2, (y1+y2)*s/2
        ratio = STYLE['small_scale'] if g['size_class'] == 'small' else (
            STYLE['circle_scale'] if g['circled'] else STYLE['large_scale'])
        patches = []; used = []
        for ch in g['text']:
            font, name = fonts.font(ch, g['size_class'], ux*ratio*s)
            box = font.getbbox(ch)
            patch = Image.new('L', (max(1, box[2]-box[0]), max(1, box[3]-box[1])))
            ImageDraw.Draw(patch).text((-box[0], -box[1]), ch, font=font, fill=255)
            if not patch.getbbox():
                raise ValueError(f"Empty font outline: {g['id']} U+{ord(ch):04X}")
            patches.append(patch); used.append(name)
        # Multiple codepoints occupy one big slot, stacked with vertical compression.
        pw = max(p.width for p in patches); ph = sum(p.height for p in patches)
        mask = Image.new('L', (pw, ph)); cursor = 0
        for p in patches:
            mask.paste(p, ((pw-p.width)//2, cursor)); cursor += p.height
        maxw, maxh = (x2-x1)*s*.95, (y2-y1)*s*(.72 if g['circled'] else .95)
        factor_x = min(1., maxw/pw); factor_y = min(1., maxh/ph)
        if len(patches) > 1: factor_y = min(factor_y, .5)
        mask = mask.resize((max(1, round(pw*factor_x)), max(1, round(ph*factor_y))), Image.Resampling.LANCZOS)
        px, py = round(cx-mask.width/2), round(cy-mask.height/2)
        canvas.paste(ink, (px, py), mask)
        mb = mask.getbbox()
        g['ink_bbox'] = [round((px+mb[0])/s, 3), round((py+mb[1])/s, 3),
                         round((px+mb[2])/s, 3), round((py+mb[3])/s, 3)]
        g['font_files'] = used
    for o in annotation['decorations']:
        x1, y1, x2, y2 = o['bbox']
        if o['kind'] == 'circle':
            d = ux*1.7; cx = (x1+x2)/2; cy = (y1+y2)/2
            o['decoration_bbox'] = [cx-d/2, cy-d/2, cx+d/2, cy+d/2]
            draw.ellipse(tuple(v*s for v in o['decoration_bbox']), outline=ink, width=s)
        else:
            r = min(ux*.3, (x2-x1)/2, (y2-y1)/2)*s
            a, b, c, d = [v*s for v in (x1, y1, x2, y2)]
            # Open ends preserve cross-line/page book-title fragments.
            ot, ob = o['open_top'], o['open_bottom']
            draw.line((a, b if ot else b+r, a, d if ob else d-r), fill=ink, width=s)
            draw.line((c, b if ot else b+r, c, d if ob else d-r), fill=ink, width=s)
            if not ot:
                draw.line((a+r, b, c-r, b), fill=ink, width=s)
                draw.arc((a, b, a+2*r, b+2*r), 180, 270, fill=ink, width=s)
                draw.arc((c-2*r, b, c, b+2*r), 270, 360, fill=ink, width=s)
            if not ob:
                draw.line((a+r, d, c-r, d), fill=ink, width=s)
                draw.arc((a, d-2*r, a+2*r, d), 90, 180, fill=ink, width=s)
                draw.arc((c-2*r, d-2*r, c, d), 0, 90, fill=ink, width=s)
    canvas = canvas.resize((width, height), Image.Resampling.LANCZOS)
    canvas.save(destination)
    return annotation


def draw_overlay(image_path, annotation, output):
    image = Image.open(image_path).convert('RGB'); draw = ImageDraw.Draw(image)
    for region in annotation['regions']:
        color = '#d52824' if region['kind'] == 'large' else '#0069d9'
        draw.rectangle(tuple(region['bbox']), outline=color, width=2)
        draw.text((region['bbox'][0]+2, region['bbox'][1]+1), str(region['order']), fill=color)
    image.save(output)
