#!/usr/bin/env python3
"""Capture the E709 baseline or verify its recorded insertion and donor recipe."""
import argparse
import copy
import hashlib
import json
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from fontTools.ttLib import TTFont

from guji_ren_heng_components import ROOT, FONT0, FONT2, RECIPE, SCAN, FIGURES, make_recipe
from guji_pua_patch import build_compose, verify_addition

OUT = ROOT/'docs/research/evidence/e709'
LOCAL = ROOT/'var/font-audit/0471-e709'
ANNOTATION = ROOT/'kangxi-gold/annotations/0471.gj'
PAGE = Path('/Volumes/WD-2T/guji-ocr/raw/kangxizidian/pages/0471.jpg')
CRAWL_DB = ROOT/'var/crawl/kangxi-crawl.sqlite3'
CP = 0xE709
OLD = '倀〈亻亨〉，疎率也。'
NEW = '倀\ue709，疎率也。'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def facts(path):
    with TTFont(path, recalcTimestamp=False) as font:
        cmap = font.getBestCmap()
        return {
            'path': str(path.relative_to(ROOT)), 'sha256': sha(path),
            'bytes': path.stat().st_size, 'cmap': len(cmap),
            'glyph_order': len(font.getGlyphOrder()),
            'contains_E709': CP in cmap,
            'unmapped_count': len(set(font.getGlyphOrder())-set(cmap.values())),
            'format14': any(t.format == 14 for t in font['cmap'].tables),
            'gsub_features': ([r.FeatureTag for r in font['GSUB'].table.FeatureList.FeatureRecord]
                              if 'GSUB' in font else []),
        }


def site_paragraph():
    """The station's own record is decisive: it transcribes the form as four
    descriptive characters and assigns no PUA slot of its own."""
    db = sqlite3.connect(CRAWL_DB)
    row = db.execute('SELECT record_json FROM entries WHERE codepoint=0x5000').fetchone()
    db.close()
    import json as js
    rec = js.loads(row[0])
    para = next(p for p in rec['text_paragraphs'] if '疎率' in p)
    i = para.find('疎率')
    ctx = para[max(0, i-8):i+5]
    return {'sword': rec['sword'], 'unicode': rec['unicode'],
            'pua_other': rec['pua_other'], 'context': ctx,
            'context_codepoints': [f'U+{ord(c):04X}' for c in ctx]}


def capture():
    if (OUT/'audit.json').exists():
        raise SystemExit('Baseline already captured; refusing to overwrite historical evidence')
    OUT.mkdir(parents=True, exist_ok=True)
    LOCAL.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    mask_path = ROOT/'tools/dataset/font-sources/e709-scan-mask.png'
    context = Image.open(PAGE).convert('RGB').crop((94, 590, 160, 810))
    ImageDraw.Draw(context).rectangle((8, 74, 57, 138), outline='#c43b32', width=2)
    context.resize((264, 880)).save(FIGURES/'page-context.png')
    shutil.copy2(ANNOTATION, LOCAL/'0471.gj.before')
    font_facts = [facts(ROOT/'guji-preview-grid/public/fonts'/name) for name in
                  ('guji-plane0.ttf', 'guji-plane2.ttf', 'guji-planef.ttf', 'guji-large.ttf')]
    assert not any(f['contains_E709'] for f in font_facts)
    needles = ['⿰亻亨', '⿰亻⿳亠口了', '⿰亻⿱亠⿱口了']
    ids_sources = sorted((ROOT/'var/font-audit/0373/ids').glob('IDS*.txt')) + [
        ROOT/'var/font-audit/0373/babelstone-ids.txt', ROOT/'var/font-audit/0367/cjkvi-ids.txt']
    ids = []
    for path in ids_sources:
        lines = [s for s in path.read_text().splitlines() if s.startswith(('U+', 'U-'))]
        ids.append({'path': str(path.relative_to(ROOT)), 'sha256': sha(path), 'entries': len(lines),
                    'target_matches': [s for s in lines if any(n in s for n in needles)],
                    'related': [s for s in lines if '\t𠆼\t' in s or '\t悙\t' in s or '\t亨\t' in s]})
    search = json.loads((OUT/'font-search.json').read_text())
    write(OUT/'audit.json', {
        'captured_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
        'page': 471, 'headword': '倀', 'headword_codepoint': 'U+5000', 'headword_order': 1,
        'context': OLD,
        'target_ids': '⿰亻亨',
        'unicode_status': 'independent-codepoint-not-confirmed',
        'irg_status': 'WS2024 UK-30044 (serial 00127, 人部 9 画); evidence accepted at IRG #63, 2025-11; no standard codepoint assigned yet. UK evidence of record is 江西通志 (n2686r), not the 集韵 Song editions.',
        'distinction': '停 U+505C is ⿰亻亭 (冖+丁 under the 口); the woodblock form shows one horizontal plus the hook. 𠆼 U+201BC is 6 strokes total (kRSUnicode 9.4), not the 9-stroke target. Visual models produced three different readings of the same crop, so identity rests on the paragraph, the transcription and stroke-level review.',
        'site_record': site_paragraph(),
        'source': {'page_path': str(PAGE), 'page_sha256': sha(PAGE),
                   'scan_crop': [102, 664, 151, 728],
                   'screenshot': str(SCAN.relative_to(ROOT)), 'screenshot_sha256': sha(SCAN),
                   'mask': str(mask_path.relative_to(ROOT)), 'mask_sha256': sha(mask_path),
                   'mask_method': 'grayscale < 120, discard connected ink components smaller than 8 pixels; crop excludes the column rule remnant at x99-100'},
        'fonts_before': font_facts, 'ids_search': {'queries': needles, 'sources': ids},
        'shape_search': {'counts': {k: v['count'] for k, v in search.items()},
                         'reviewed': 'Top 48 of each small font via figures/e709/font-candidates.png; ranking is dominated by small-ink glyphs because the raw scan is anisotropically squeezed.',
                         'result': 'No matching target found',
                         'limitation': 'Candidate ranking plus finite visual review; not manual examination of every glyph or proof of global Unicode absence.'},
        'calibration': 'chamfer-calibration.json: composition 6.41 inside the same-page true-identity band 5.19-7.04; 停 5.13 also inside, so scan distance cannot arbitrate identity on this page.',
        'allocation': {'cp': 'E709', 'note': 'E701, E704-E708 occupied; E702/E703 reserved historical slots; E709 absent from all four cmap tables.'},
        'annotation_before': {'path': str(ANNOTATION.relative_to(ROOT)), 'sha256': sha(ANNOTATION),
                              'tracked': False, 'target_occurrences': ANNOTATION.read_text().count(OLD)},
        'rollback': {'git_head': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                     'font_git_blob': subprocess.check_output(['git','rev-parse','HEAD:guji-preview-grid/public/fonts/guji-plane0.ttf'],cwd=ROOT,text=True).strip()},
    })
    print('Captured source, font/Unicode baseline and annotation snapshot')


def verify():
    audit = json.loads((OUT/'audit.json').read_text())
    recipe = json.loads(RECIPE.read_text())
    baseline = audit['fonts_before'][0]
    backup = ROOT/'var/unencoded/kangxi-unencoded/font-backups'/f"guji-plane0.ttf.{baseline['sha256']}.ttf"
    if sha(backup) != baseline['sha256']:
        raise ValueError('Backup hash differs from captured baseline')
    with TTFont(backup, recalcTimestamp=False) as before, TTFont(FONT0, recalcTimestamp=False) as after, TTFont(FONT2, recalcTimestamp=False) as donor:
        verify_addition(before, after, CP)
        rebuilt = make_recipe(after, donor)
        if rebuilt != recipe:
            raise ValueError('Frozen recipe does not reproduce from native donors')
        built = build_compose(after, recipe)
        name = after.getBestCmap()[CP]
        glyph = after['glyf'][name]
        if built.compile(after['glyf']) != glyph.compile(after['glyf']):
            raise ValueError('Production outline differs from reviewed recipe')
        for tag, expected in recipe['metrics'].items():
            assert list(after[tag][name]) == expected
        # Ensure bad donor provenance and corrupted frozen outlines are rejected.
        rejected = []
        for label in ('internal-donor-hash', 'external-donor-hash', 'frozen-outline'):
            bad = copy.deepcopy(recipe)
            if label == 'internal-donor-hash':
                bad['donor_glyph_sha256']['6059'] = '0'*64
            elif label == 'external-donor-hash':
                bad['external_donors'][0]['glyph_sha256']['201BC'] = '0'*64
            else:
                bad['approved_glyph']['coordinates'][0][0] += 7
            try:
                build_compose(after, bad)
            except ValueError:
                rejected.append(label)
            else:
                raise ValueError(f'Corrupt {label} was accepted')
        glyph_result = {'name': name, 'contours': glyph.numberOfContours,
                        'points': len(glyph.coordinates),
                        'bbox': [glyph.xMin,glyph.yMin,glyph.xMax,glyph.yMax],
                        'hmtx': list(after['hmtx'][name]), 'vmtx': list(after['vmtx'][name]),
                        'compiled_sha256': hashlib.sha256(glyph.compile(after['glyf'])).hexdigest()}
    others = []
    for old in audit['fonts_before'][1:]:
        current = facts(ROOT/old['path'])
        assert current['sha256'] == old['sha256'] and not current['contains_E709']
        others.append(current)
    registry = json.loads((ROOT/'guji-preview-grid/src/pua-registry.json').read_text())
    entry = next(g for g in registry['glyphs'] if g['cp'] == 'E709')
    for g in registry['glyphs']:
        if str(FONT0.relative_to(ROOT)) in g['fonts']:
            assert g['sha256_after'][FONT0.name] == sha(FONT0)
    left, right = recipe['components']
    gap = right['bounds'][0]-left['bounds'][2]
    assert gap >= recipe['verification']['min_component_gap_units']
    result = {'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
              'operation': entry['history'][-1], 'final_font': facts(FONT0), 'final_glyph': glyph_result,
              'preserved_glyphs': baseline['glyph_order'], 'all_previous_glyphs_and_metrics_unchanged': True,
              'other_fonts': others, 'complete_donor_contours': True,
              'component_gap_units': gap,
              'non_overlap': 'Disjoint x bounds with at least 18 units of gap; identity scaling and integer-free translation keep the original outlines.',
              'rebuild_matches_production': True, 'corruption_rejected': rejected,
              'registry_shared_hashes_match': True, 'rollback': audit['rollback']}
    record_path = OUT/'patch-verification.json'
    if record_path.exists():
        commits = json.loads(record_path.read_text()).get('git_commits')
        if commits:
            result['git_commits'] = commits
    write(record_path, result)
    old = (LOCAL/'0471.gj.before').read_text()
    new = ANNOTATION.read_text()
    assert old.count(OLD) == 1
    assert new == old.replace(OLD, NEW)
    write(OUT/'annotation.json', {'checked_at': result['checked_at'],
                                  'page': 471, 'path': str(ANNOTATION.relative_to(ROOT)),
                                  'sha256_before': audit['annotation_before']['sha256'], 'sha256_after': sha(ANNOTATION),
                                  'old': OLD, 'new': NEW, 'replacements': 1,
                                  'E709_count': new.count('\ue709'), 'other_text_unchanged': True,
                                  'git_scope': 'One local draft edit only; full untracked page excluded from font commit.'})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    args = parser.parse_args()
    capture() if args.capture else verify()
