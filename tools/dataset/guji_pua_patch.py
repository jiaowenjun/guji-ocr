#!/usr/bin/env python3
"""PUA 自补字形生产工具：把无 Unicode 码位的字形补入仓库字体（U+E700–E7FF 段）。

注册表：guji-preview-grid/src/pua-registry.json（码位=字位；改进=version+1 重补同码位）。
scheme：
  scan-trace  截图轮廓（x_contours.json：闭运算+Moore+DP 的折线），现有实现；
  compose     已审定的字体部件合成；校验来源字形后恢复冻结轮廓；
  copy-glyph  整字复制，预留接口 NotImplementedError。
同一码位可通过 font_overrides 为小字/大字选择不同方案。
校准：每字体以其 U+343A 㐺 字形 bbox 为锚（同族形），轮廓方向对齐该字体自身外轮廓。
注入：glyf/glyphOrder/maxp/hmtx（advance=锚字）/**vmtx（有则必补，否则 compile KeyError）**/cmap format-4。
验证：PIL 渲染补录字形 vs verify_image 归一化 chamfer，方案可显式指定阈值，否则默认 0.5
（光栅源管线标尺：E701 实测 0.366，含 DP 简化误差；矢量源管线沿用 0.15 见 kangxi_font_patch.py）。
留痕：font-patches.jsonl 追加 + 注册表 version/hash 更新 + 登记簿人工行（docs/font-operations.md）。

用法（自仓库根）：
  python3 tools/dataset/guji_pua_patch.py --cp E701 [--dry-run] [--gate 0.5]
  # 同码位、仅小字升级（expected-version 为运行时的当前登记版本）：
  python3 tools/dataset/guji_pua_patch.py --cp E701 --font guji-plane0.ttf \
    --replace --expected-version 4 --scheme compose \
    --source tools/dataset/font-sources/e701-songti-v4.json --dry-run
"""

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from array import array
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphCoordinates
from fontTools.ttLib.tables.ttProgram import Program

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY = os.path.join(REPO, "guji-preview-grid/src/pua-registry.json")
PATCH_LOG = os.path.join(REPO, "var/unencoded/kangxi-unencoded/font-patches.jsonl")
ANCHOR_CP = 0x343A  # 㐺——三人同族形，各字体均有


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def signed_area(pts):
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return a / 2


def font_facts(font):
    """锚字 bbox、advance、外轮廓方向符号、有无 vmtx。"""
    cmap = font.getBestCmap()
    gs = font.getGlyphSet()
    bp = BoundsPen(gs)
    gs[cmap[ANCHOR_CP]].draw(bp)
    rec = RecordingPen()
    gs[cmap[ANCHOR_CP]].draw(rec)
    first_poly = []
    for op, args in rec.value:  # 第一段闭合轮廓折线化（定向用）
        if op == "moveTo":
            first_poly = [args[0]]
        elif op == "lineTo":
            first_poly.append(args[0])
        elif op == "qCurveTo":
            pts = [p for p in args if p is not None]
            first_poly.append(pts[-1])
        elif op == "closePath" and first_poly:
            break
    adv = font["hmtx"][cmap[ANCHOR_CP]][0]
    return bp.bounds, adv, signed_area(first_poly) >= 0, "vmtx" in font


def build_scan_trace(font, contours):
    """折线（像素 y-down）→ 该字体坐标的平滑二次贝塞尔字形。"""
    anchor_bbox, _, ref_ccw, _ = font_facts(font)
    all_pts = [p for c in contours["components"] for p in c["outer"]]
    px = [p[1] for p in all_pts]
    py = [p[0] for p in all_pts]
    pw, ph = max(px) - min(px), max(py) - min(py)
    s = ((anchor_bbox[2] - anchor_bbox[0]) / pw + (anchor_bbox[3] - anchor_bbox[1]) / ph) / 2
    tx = anchor_bbox[0] - s * min(px)
    ty = anchor_bbox[3] + s * min(py)
    tp = TTGlyphPen(font.getGlyphSet())
    for comp in contours["components"]:
        poly = [(tx + s * x, ty - s * y) for y, x in comp["outer"]]
        if (signed_area(poly) >= 0) != ref_ccw:
            poly = poly[::-1]
        n = len(poly)
        mids = [((poly[i][0] + poly[(i + 1) % n][0]) / 2,
                 (poly[i][1] + poly[(i + 1) % n][1]) / 2) for i in range(n)]
        tp.moveTo(mids[-1])
        for i in range(n):
            tp.qCurveTo(poly[i], mids[i])
        tp.closePath()
    return tp.glyph()


def build_compose(font, recipe):
    """恢复已审定的合成轮廓；生成器及部件变换另存于 recipe，避免重新拟合漂移。"""
    if font['head'].unitsPerEm != recipe['units_per_em']:
        raise ValueError('compose 源与目标字体 unitsPerEm 不同')
    cmap = font.getBestCmap()
    for cp, expected in recipe['donor_glyph_sha256'].items():
        name = cmap.get(int(cp, 16))
        if name is None or hashlib.sha256(font['glyf'][name].compile(font['glyf'])).hexdigest() != expected:
            raise ValueError(f'compose 来源字 U+{cp} 已变化，请重新审定部件')
    # A small-font component may come from another plane of the same family.
    # Read-only validation prevents silently applying a stale external outline.
    for donor in recipe.get('external_donors', []):
        with TTFont(os.path.join(REPO, donor['font']), recalcTimestamp=False) as source_font:
            if source_font['head'].unitsPerEm != recipe['units_per_em']:
                raise ValueError('compose 外部来源字体 unitsPerEm 不同')
            source_cmap = source_font.getBestCmap()
            for code, expected in donor['glyph_sha256'].items():
                name = source_cmap.get(int(code, 16))
                if name is None or hashlib.sha256(source_font['glyf'][name].compile(source_font['glyf'])).hexdigest() != expected:
                    raise ValueError(f'compose 外部来源字 {donor["font"]}/U+{code} 已变化，请重新审定部件')
    data = recipe['approved_glyph']
    glyph = Glyph()
    glyph.numberOfContours = data['number_of_contours']
    glyph.coordinates = GlyphCoordinates(data['coordinates'])
    glyph.endPtsOfContours = data['end_points']
    glyph.flags = array('B', data['flags'])
    glyph.program = Program()
    glyph.program.fromBytecode(data['instructions'])
    glyph.recalcBounds(font['glyf'])
    actual = hashlib.sha256(glyph.compile(font['glyf'])).hexdigest()
    if actual != data['compiled_sha256']:
        raise ValueError('compose 冻结轮廓校验失败')
    return glyph


def build_copy_glyph(font, contours):
    raise NotImplementedError("copy-glyph 方案预留：整字复制")


BUILDERS = {"scan-trace": build_scan_trace, "compose": build_compose, "copy-glyph": build_copy_glyph}


def norm_ink(arr, size=128):
    a = arr if arr.dtype == bool else arr < 128
    ys, xs = np.nonzero(a)
    if not len(xs):
        raise ValueError('字形没有实际墨迹')
    sub = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = sub.shape
    out = np.zeros((size, size), bool)
    sc = min((size - 8) / h, (size - 8) / w)
    r = Image.fromarray(sub.astype(np.uint8) * 255).resize(
        (max(1, int(w * sc)), max(1, int(h * sc))), Image.BILINEAR)
    rb = np.asarray(r) > 96
    oy, ox = (size - rb.shape[0]) // 2, (size - rb.shape[1]) // 2
    out[oy:oy + rb.shape[0], ox:ox + rb.shape[1]] = rb
    return out


def chamfer(a, b):
    ea = ndimage.distance_transform_edt(~a)
    eb = ndimage.distance_transform_edt(~b)
    return 0.5 * (ea[b].mean() + eb[a].mean())


def patch_font(font_path, cp, glyph, adv, has_vmtx_expected, output_path=None):
    font = TTFont(font_path, recalcTimestamp=False)
    cmap = font.getBestCmap()
    name = cmap.get(cp, f"uni{cp:04X}")
    if any(code != cp and mapped == name for code, mapped in cmap.items()):
        raise ValueError(f'{name} 被其他码位共用，拒绝修改')
    _, _, _, has_vmtx = font_facts(font)
    glyf = font["glyf"]
    vertical_origin = None
    if cp in cmap:
        adv = font['hmtx'][name][0]
        if has_vmtx:
            va, tsb = font['vmtx'][name]
            vertical_origin = (va, glyf[name].yMax + tsb)
    glyf.glyphs[name] = glyph  # 调用方按该字体坐标构建
    glyph.recalcBounds(glyf)
    if name not in font.glyphOrder:
        font.glyphOrder.append(name)
    font["maxp"].numGlyphs = len(font.glyphOrder)
    hm = font["hmtx"]
    hm.metrics[name] = (adv, glyf.glyphs[name].xMin)
    font["hhea"].numberOfHMetrics = len(hm.metrics)
    if has_vmtx:
        vm = font["vmtx"]
        if vertical_origin:
            va, origin = vertical_origin
            vm.metrics[name] = (va, origin - glyph.yMax)
        else:
            vm.metrics[name] = vm[cmap[ANCHOR_CP]]
    hit = 0
    # 只写 Windows/Unicode 子表；Mac (1,0,*) 的 format-0/6 子表区间小，
    # 塞 BMP PUA 会使 entryCount 撑爆 length 字段（guji-large 实测坑）
    ok = ((3, 1, 4), (0, 3, 4), (0, 4, 12), (3, 10, 12))
    for st in font["cmap"].tables:
        if (st.platformID, st.platEncID, st.format) in ok:
            st.cmap[cp] = name
            hit += 1
    if hit == 0:
        raise SystemExit(f"error: {font_path} 无可注入 cmap 子表")
    tmp = output_path or font_path + ".tmp"
    font.save(tmp)
    return tmp


def verify_replacement(before, after, cp):
    """A replacement may change only the selected outline and its bearings."""
    if before.getBestCmap() != after.getBestCmap() or before.getGlyphOrder() != after.getGlyphOrder():
        raise ValueError('替换不应改变 cmap 或 glyphOrder')
    target = before.getBestCmap()[cp]
    for name in before.getGlyphOrder():
        if name == target:
            continue
        if before['glyf'][name].compile(before['glyf']) != after['glyf'][name].compile(after['glyf']):
            raise ValueError(f'非目标轮廓变化：{name}')
        for tag in ('hmtx', 'vmtx'):
            if tag in before and before[tag][name] != after[tag][name]:
                raise ValueError(f'非目标度量变化：{tag}/{name}')
    if before['hmtx'][target][0] != after['hmtx'][target][0]:
        raise ValueError('替换改变了 advance')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--cp', required=True, help='注册表内码位，如 E701')
    ap.add_argument('--gate', type=float, help='覆盖方案的 chamfer 阈值（方案未指定时为 0.5）')
    ap.add_argument('--dry-run', action='store_true', help='只生成临时字体并验证')
    ap.add_argument('--font', action='append', help='仅处理注册表内指定文件（可重复；省略为全部）')
    ap.add_argument('--replace', action='store_true', help='替换已有字位，保持 cmap 与 advance')
    ap.add_argument('--expected-version', type=int, help='替换时必须给出当前登记版本')
    ap.add_argument('--scheme', choices=tuple(BUILDERS), help='本次选中字体的新方案')
    ap.add_argument('--source', help='新方案的仓库相对 JSON 路径')
    ap.add_argument('--cache-version', help='记录本次配套 CSS 缓存戳')
    args = ap.parse_args()
    if bool(args.scheme) != bool(args.source):
        ap.error('--scheme 与 --source 须同时给出')
    if args.replace and args.expected_version is None:
        ap.error('--replace 须带 --expected-version')
    with open(REGISTRY) as f:
        reg = json.load(f)
    entry = next((g for g in reg['glyphs'] if g['cp'].upper() == args.cp.upper()), None)
    if entry is None:
        raise SystemExit(f'U+{args.cp} 未登记')
    if args.expected_version is not None and entry['version'] != args.expected_version:
        raise SystemExit(f'登记版本已变化：{entry["version"]} != {args.expected_version}')
    selected = [rel for rel in entry['fonts'] if not args.font or
                rel in args.font or os.path.basename(rel) in args.font]
    if not selected or (args.font and any(not any(value in (r, os.path.basename(r)) for r in selected) for value in args.font)):
        ap.error('--font 不在该字位登记的字体清单中')
    cp = int(args.cp, 16)
    stamp = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
    results, plans = [], []
    with tempfile.TemporaryDirectory(prefix='guji-pua-') as temp:
        for rel in selected:
            path = os.path.join(REPO, rel)
            basename = os.path.basename(rel)
            before_hash, before_bytes = sha256(path), os.path.getsize(path)
            if args.replace and entry.get('sha256_after', {}).get(basename) != before_hash:
                raise SystemExit(f'{rel} 与登记哈希不一致，拒绝覆盖')
            override = entry.get('font_overrides', {}).get(basename, {})
            scheme = args.scheme or override.get('scheme', entry['scheme'])
            source = args.source or override.get('source', entry['source'])
            verify_path = override.get('verify_image', entry['verify_image'])
            with open(os.path.join(REPO, source)) as f:
                data = json.load(f)
            gate = args.gate if args.gate is not None else data.get('verification', {}).get('max_chamfer', 0.5)
            if scheme == 'compose' and data['font'] != basename:
                raise SystemExit('compose 字形源不适用于目标字体')
            font = TTFont(path, recalcTimestamp=False)
            exists = cp in font.getBestCmap()
            if exists != args.replace:
                raise SystemExit('已有字位须显式 --replace；新增字位不能使用 --replace')
            _, adv, _, has_vmtx = font_facts(font)
            glyph = BUILDERS[scheme](font, data)
            tmp = patch_font(path, cp, glyph, adv, has_vmtx, os.path.join(temp, basename))
            after = TTFont(tmp, recalcTimestamp=False)
            if args.replace:
                verify_replacement(font, after, cp)
            if scheme == 'compose':
                target = after.getBestCmap()[cp]
                for tag, expected in data['metrics'].items():
                    if list(after[tag][target]) != expected:
                        raise ValueError(f'{tag} 与审定字形的度量不一致')
            verify = np.asarray(Image.open(os.path.join(REPO, verify_path)).convert('L')) < 128
            image = Image.new('L', (440, 440), 255)
            ImageDraw.Draw(image).text((44, 44), chr(cp), font=ImageFont.truetype(tmp, 220), fill=0)
            score = chamfer(norm_ink(np.asarray(image) < 128), norm_ink(verify))
            if score > gate:
                raise SystemExit(f'{rel} chamfer={score:.3f} 超出 {gate}')
            result = {'font': rel, 'scheme': scheme, 'source': source,
                      'sha256_before': before_hash, 'sha256_after': sha256(tmp),
                      'bytes_before': before_bytes, 'bytes_after': os.path.getsize(tmp),
                      'chamfer': round(float(score), 3), 'chamfer_gate': gate, 'cmap_before': len(font.getBestCmap()),
                      'cmap_after': len(after.getBestCmap()),
                      'other_glyphs_and_metrics_unchanged': bool(args.replace)}
            print(json.dumps(result, ensure_ascii=False))
            results.append(result)
            plans.append((path, tmp, result))
        if args.dry_run:
            print('干跑通过；字体、注册表和流水均未写入。')
            return
        # Validate all inputs again before replacing any font.
        for path, _, result in plans:
            if sha256(path) != result['sha256_before']:
                raise SystemExit(f'{path} 在验证期间发生变化，拒绝覆盖')
        backup_root = os.path.join(os.path.dirname(PATCH_LOG), 'font-backups')
        os.makedirs(backup_root, exist_ok=True)
        for path, _, result in plans:
            backup = os.path.join(backup_root, os.path.basename(path)+'.'+result['sha256_before']+'.ttf')
            if not os.path.exists(backup):
                shutil.copy2(path, backup)
            if sha256(backup) != result['sha256_before']:
                raise ValueError('回滚备份校验失败')
            result['backup'] = os.path.relpath(backup, REPO)
        version = entry['version'] + 1
        entry.setdefault('font_versions', {os.path.basename(r): entry['version'] for r in entry['fonts']})
        for path, tmp, result in plans:
            os.replace(tmp, path)
            basename = os.path.basename(path)
            entry['sha256_after'][basename] = result['sha256_after']
            entry['font_versions'][basename] = version
            if args.scheme:
                entry.setdefault('font_overrides', {})[basename] = {
                    'scheme': result['scheme'], 'source': result['source'],
                    'source_note': '按已审定的宋体部件构形替换；码位稳定，具体部件与轮廓摘要见 source。'}
        entry['version'] = version
        entry['patched_at'] = stamp[:10]
        event = {'version': version, 'at': stamp, 'operation': 'replace' if args.replace else 'insert',
                 'results': results}
        if args.cache_version:
            event['cache_version'] = args.cache_version
        entry.setdefault('history', []).append(event)
        with open(REGISTRY, 'w') as f:
            json.dump(reg, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.makedirs(os.path.dirname(PATCH_LOG), exist_ok=True)
        with open(PATCH_LOG, 'a') as f:
            f.write(json.dumps({'tool': 'guji_pua_patch', 'cp': f'U+{cp:X}', **event}, ensure_ascii=False)+'\n')
        print(f'已写入 {len(results)} 份字体；登记版本 {version}；机器流水已追加。')


if __name__ == '__main__':
    main()
