"""E702 made solely from existing guji-plane0 Songti outlines.

Every curve is copied from a donor, then transformed affinely. The top stroke
is a closed subpath of 乑; the closing edge is hidden under the centre stem.
No scan-traced or newly drawn stroke outline is used for E702.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
from fontTools.misc.transform import Transform
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import DecomposingRecordingPen, RecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen

PARTS = []


def contours(font, ch):
    gs = font.getGlyphSet()
    rec = DecomposingRecordingPen(gs)
    gs[font.getBestCmap()[ord(ch)]].draw(rec)
    out, part = [], RecordingPen()
    for op, pts in rec.value:
        getattr(part, op)(*pts)
        if op == 'closePath':
            out.append(part)
            part = RecordingPen()
    return out


def bbox(rec):
    bp = BoundsPen(None)
    rec.replay(bp)
    return bp.bounds


def moved(rec, transform):
    out = RecordingPen()
    rec.replay(TransformPen(out, transform))
    return out


def in_box(rec, target):
    a,b,c,d = bbox(rec)
    x0,y0,x1,y1 = target
    sx,sy = (x1-x0)/(c-a),(y1-y0)/(d-b)
    return Transform(sx,0,0,sy,x0-sx*a,y0-sy*b)


def from_anchors(source, target):
    a = np.array([[x,y,1] for x,y in source])
    result = np.linalg.solve(a,np.array(target))
    return Transform(result[0,0],result[0,1],result[1,0],result[1,1],result[2,0],result[2,1])


def build_songti(font, scan_contours, mapping):
    global PARTS
    PARTS = []
    s,tx,ty,_ = mapping
    def point(x,y):return tx+s*x,ty-s*y
    def box(x0,y0,x1,y1):return (*point(x0,y1),*point(x1,y0))
    def add(ch, index, role, rec, transform, note='complete contour'):
        assert transform.xx*transform.yy-transform.xy*transform.yx>0, 'Reflected donor'
        dest = moved(rec,transform)
        PARTS.append({'source_char':ch,'codepoint':f'U+{ord(ch):04X}',
                      'contour':index,'role':role,'extraction':note,
                      'source_outline_sha256':hashlib.sha256(repr(rec.value).encode()).hexdigest(),
                      'transform':list(transform),'source_bounds':bbox(rec),'bounds':bbox(dest),
                      'recording':dest, 'source_recording':rec})
    # 乑 top stroke only: preserve its source curves and triangular terminal.
    src = contours(font,'乑')[0]
    assert src.value[5] == ('qCurveTo',((677,718),(542,699)))
    assert src.value[27] == ('lineTo',((490,692),))
    top = RecordingPen()
    top.value = src.value[:6] + [src.value[27]] + src.value[28:]
    top_shape = Transform(.56,.068,0,.8,0,0)
    b = bbox(moved(top,top_shape))
    px,py = point(25,8)
    add('乑',0,'顶撇',top,Transform(.56,.068,0,.8,px-b[0],py-b[3]),
        'top-stroke subpath; one closing edge across the original stem junction')
    # 丨: retain the original stem width, head serif and lower terminal.
    stem = contours(font,'丨')[0]
    sy = s*(75-16)/(853+132)
    add('丨',0,'中竖',stem,Transform(.95,0,0,sy,point(43.5,0)[0]-.95*508,point(0,16)[1]-sy*853))
    # 从: the left person already includes the short right branch.
    left = contours(font,'从')[1]
    add('从',1,'左侧撇与短分支',left,from_anchors([(285,800),(17,-70),(449,150)],
        [point(32,30),point(9,70),point(36.2,54.5)]))
    # 分: independently place the two existing 八 strokes to match the scan fork.
    strokes = contours(font,'分')
    add('分',2,'右侧撇',strokes[2],in_box(strokes[2],box(43.4,26,62.4,54)))
    # The right stroke is attached at its head: omit its independent head serif
    # instead of leaving a false extra spur at the new fork.
    falling = RecordingPen()
    assert strokes[1].value[10] == ('qCurveTo',((604,810),(605,791)))
    falling.value = strokes[1].value[:6] + [('lineTo',((605,791),))] + strokes[1].value[11:]
    add('分',1,'右侧捺',falling,in_box(falling,box(53.3,40.8,74,58)),
        'right stroke, detached head serif omitted at the joined fork')
    pen = TTGlyphPen(font.getGlyphSet())
    for item in PARTS:item['recording'].replay(pen)
    glyph = pen.glyph()
    glyph.flags[0] |= 0x40  # TrueType OVERLAP_SIMPLE; boolean union follows.
    return glyph


def export_parts(path, mapping, font):
    s,tx,ty,_ = mapping
    colors = ['#ad6332','#336f9e','#287c59','#9257a2','#c04642']
    paths = []
    records = []
    for index,(part,color) in enumerate(zip(PARTS,colors)):
        pen = SVGPathPen(None);part['recording'].replay(pen)
        paths.append(f'<path d="{pen.getCommands()}" fill="{color}"/>')
        source = SVGPathPen(None);part['source_recording'].replay(source)
        gs = font.getGlyphSet()
        whole = SVGPathPen(gs)
        gs[font.getBestCmap()[ord(part['source_char'])]].draw(whole)
        (path/f'e702-source-{index}.svg').write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
            '<g transform="matrix(1 0 0 -1 0 864)">'
            f'<path d="{whole.getCommands()}" fill="#d3cec3"/>'
            f'<path d="{source.getCommands()}" fill="{color}"/></g></svg>')
        records.append({k:v for k,v in part.items() if k not in ('recording','source_recording')}
                       |{'color':color,'path':pen.getCommands(),'source_path':source.getCommands()})
    (path/'e702-components.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 84 88">'
        f'<g transform="matrix({1/s} 0 0 {-1/s} {-tx/s} {ty/s})">'+''.join(paths)+'</g></svg>')
    (path/'e702-components.json').write_text(json.dumps({'font':'guji-plane0.ttf','parts':records},ensure_ascii=False,indent=2)+'\n')


def main():
    """Rebuild native components and compare to the reviewed frozen recipe.

    Requires skia-pathops for this authoring check; applying the frozen recipe
    through guji_pua_patch.py does not require it.
    """
    import argparse
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.removeOverlaps import removeOverlaps
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('--font', type=Path, default=root/'guji-preview-grid/public/fonts/guji-plane0.ttf')
    parser.add_argument('--recipe', type=Path, default=root/'tools/dataset/font-sources/e701-songti-v2.json')
    args = parser.parse_args()
    recipe = json.loads(args.recipe.read_text())
    font = TTFont(args.font, recalcTimestamp=False)
    name = font.getBestCmap()[0xE701]
    font['glyf'][name] = build_songti(font, None, recipe['coordinate_mapping'])
    removeOverlaps(font, glyphNames=[name])
    actual = hashlib.sha256(font['glyf'][name].compile(font['glyf'])).hexdigest()
    if actual != recipe['approved_glyph']['compiled_sha256']:
        raise SystemExit('Generated components differ from approved recipe; review before updating it.')
    print('Five native components reproduce the approved U+E701 Songti outline exactly:', actual)


if __name__ == '__main__':
    main()
