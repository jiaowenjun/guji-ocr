#!/usr/bin/env python3
"""Capture the E708 baseline or verify its recorded insertion and donor recipe."""
import argparse
import copy
import hashlib
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from fontTools.ttLib import TTFont

from guji_chi_22f95_components import ROOT, FONT0, FONT2, RECIPE, SCAN, FIGURES, make_recipe
from guji_pua_patch import build_compose, verify_addition

OUT = ROOT/'docs/research/evidence/e708'
LOCAL = ROOT/'var/font-audit/0504-e708'
ANNOTATION = ROOT/'kangxi-gold/annotations/0504.gj'
PAGE = Path('/Volumes/WD-2T/guji-ocr/raw/kangxizidian/pages/0504.jpg')
CP = 0xE708


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
            'contains_E708': CP in cmap,
            'unmapped_count': len(set(font.getGlyphOrder())-set(cmap.values())),
            'format14': any(t.format == 14 for t in font['cmap'].tables),
            'gsub_features': ([r.FeatureTag for r in font['GSUB'].table.FeatureList.FeatureRecord]
                              if 'GSUB' in font else []),
        }


def capture():
    if (OUT/'audit.json').exists():
        raise SystemExit('Baseline already captured; refusing to overwrite historical evidence')
    OUT.mkdir(parents=True, exist_ok=True)
    LOCAL.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    source = np.asarray(Image.open(SCAN).convert('L')) < 120
    labels, _ = ndimage.label(source)
    counts = np.bincount(labels.ravel())
    keep = counts >= 8
    keep[0] = False
    mask = keep[labels]
    mask_path = ROOT/'tools/dataset/font-sources/e708-scan-mask.png'
    Image.fromarray(np.where(mask, 0, 255).astype('uint8')).save(mask_path)
    scan = Image.open(PAGE).convert('RGB').crop((275, 1310, 467, 1534))
    ImageDraw.Draw(scan).rectangle((20, 157, 80, 222), outline='#c43b32', width=2)
    scan.resize((384, 448)).save(FIGURES/'page-context.png')
    shutil.copy2(ANNOTATION, LOCAL/'0504.gj.before')
    font_facts = [facts(ROOT/'guji-preview-grid/public/fonts'/name) for name in
                  ('guji-plane0.ttf', 'guji-plane2.ttf', 'guji-planef.ttf', 'guji-large.ttf')]
    assert not any(f['contains_E708'] for f in font_facts)
    ids = []
    needles = ['⿰彳𢾕', '⿰彳⿰⿱出方攵', '⿲彳⿱出方攵', '⿰彳⿽放出', '⿰彳𢾍']
    paths = list((ROOT/'var/font-audit/0373/ids').glob('IDS*.txt')) + [
        ROOT/'var/font-audit/0373/babelstone-ids.txt', ROOT/'var/font-audit/0367/cjkvi-ids.txt']
    for path in sorted(paths):
        lines = [s for s in path.read_text().splitlines() if s.startswith(('U+', 'U-'))]
        ids.append({'path': str(path.relative_to(ROOT)), 'sha256': sha(path), 'entries': len(lines),
                    'target_matches': [s for s in lines if any(n in s for n in needles)],
                    'related': [s for s in lines if '\t𢕟\t' in s or '\t𢾕\t' in s]})
    ivd = ROOT/'var/font-audit/0373/unicode-ivd.txt'
    search = json.loads((OUT/'font-search.json').read_text())
    write(OUT/'audit.json', {
        'captured_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
        'page': 504, 'headword': '傲', 'headword_codepoint': 'U+50B2', 'headword_order': 7,
        'context': '不問而告謂之傲。*本作〈彳𢾕〉。或借奡，慠通。',
        'target_ids': '⿰彳𢾕', 'unicode_status': 'independent-codepoint-not-confirmed',
        'distinction': 'U+22F95 is only the right component; U+2255F has right 敖, not the required 出-bearing 𢾕. No claimed character-identity equivalence to U+2255F.',
        'source': {'page_path': str(PAGE), 'page_sha256': sha(PAGE),
                   'screenshot': str(SCAN.relative_to(ROOT)), 'screenshot_sha256': sha(SCAN),
                   'mask': str(mask_path.relative_to(ROOT)), 'mask_sha256': sha(mask_path),
                   'mask_method': 'grayscale < 120, discard connected ink components smaller than 8 pixels'},
        'fonts_before': font_facts, 'ids_search': {'queries': needles, 'sources': ids},
        'ivd': {'version': '2025-07-14', 'sha256': sha(ivd),
                'related_lines': [s for s in ivd.read_text().splitlines() if s.startswith(('2255F ', '22F95 ', '50B2 '))],
                'limitation': 'No 2255F/22F95 sequence. The 50B2 Adobe sequence is not evidence for the target; no small font has format-14 cmap.'},
        'shape_search': {'counts': {k: v['count'] for k,v in search.items()},
                         'reviewed': 'Top 48 of each small font, plus top 48 of 535 mapped 彳-related candidates and all 96 unmapped plane0 glyphs.',
                         'result': 'No matching target found',
                         'limitation': 'Candidate ranking plus finite visual review; not manual examination of every glyph or proof of global Unicode absence.'},
        'allocation': {'cp': 'E708', 'note': 'E701/E704-E707 occupied; E702/E703 reserved historical slots; E708 absent from all four cmap tables.'},
        'annotation_before': {'path': str(ANNOTATION.relative_to(ROOT)), 'sha256': sha(ANNOTATION),
                              'tracked': False, 'target_occurrences': ANNOTATION.read_text().count('*本作*。')},
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
        for label in ('external-donor-hash', 'frozen-outline'):
            bad = copy.deepcopy(recipe)
            if label == 'external-donor-hash':
                bad['external_donors'][0]['glyph_sha256']['22F95'] = '0'*64
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
        assert current['sha256'] == old['sha256'] and not current['contains_E708']
        others.append(current)
    registry = json.loads((ROOT/'guji-preview-grid/src/pua-registry.json').read_text())
    entry = next(g for g in registry['glyphs'] if g['cp'] == 'E708')
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
              'non_overlap': 'Disjoint x bounds, with more than 16 units of gap before integer rounding; this proves component outlines cannot intersect.',
              'rebuild_matches_production': True, 'corruption_rejected': rejected,
              'registry_shared_hashes_match': True, 'rollback': audit['rollback']}
    record_path = OUT/'patch-verification.json'
    if record_path.exists():
        commits = json.loads(record_path.read_text()).get('git_commits')
        if commits:
            result['git_commits'] = commits
    write(record_path, result)
    old = (LOCAL/'0504.gj.before').read_text()
    new = ANNOTATION.read_text()
    assert old.count('*本作*。') == 1
    assert new == old.replace('*本作*。', '*本作\ue708。')
    write(OUT/'annotation.json', {'checked_at': result['checked_at'],
                                  'page': 504, 'path': str(ANNOTATION.relative_to(ROOT)),
                                  'sha256_before': audit['annotation_before']['sha256'], 'sha256_after': sha(ANNOTATION),
                                  'old': '*本作*。', 'new': '*本作\ue708。', 'replacements': 1,
                                  'E708_count': new.count('\ue708'), 'other_text_unchanged': True,
                                  'git_scope': 'One local draft edit only; full untracked page excluded from font commit.'})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    args = parser.parse_args()
    capture() if args.capture else verify()
