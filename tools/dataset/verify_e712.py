#!/usr/bin/env python3
"""Capture the E712 baseline or verify its recorded insertion and donor recipe."""
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

from PIL import Image
from fontTools.ttLib import TTFont

from guji_ren_yi_components import ROOT, FONT0, FONT2, RECIPE, SCAN, FIGURES, make_recipe
from guji_pua_patch import build_compose, verify_addition

OUT = ROOT/'docs/research/evidence/e712'
LOCAL = ROOT/'var/font-audit/0512-e712'
ANNOTATION = ROOT/'kangxi-gold/annotations/0512.gj'
PAGE = Path('/Volumes/WD-2T/guji-ocr/raw/kangxizidian/pages/0512.jpg')
CRAWL_DB = ROOT/'var/crawl/kangxi-crawl.sqlite3'
CP = 0xE712
OLD = '或作〈亻𫇮〉。'
NEW = '或作\ue712。'


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
            'contains_E712': CP in cmap,
            'unmapped_count': len(set(font.getGlyphOrder())-set(cmap.values())),
            'format14': any(t.format == 14 for t in font['cmap'].tables),
            'gsub_features': ([r.FeatureTag for r in font['GSUB'].table.FeatureList.FeatureRecord]
                              if 'GSUB' in font else []),
        }


def site_paragraph():
    """The station's paragraph lazily repeats the headword 𠌾 for the variant
    form; the gold transcription and the screenshot structure establish
    〈亻𫇮〉 instead. Recorded verbatim as a transcription-divergence case."""
    db = sqlite3.connect(CRAWL_DB)
    row = db.execute('SELECT record_json FROM entries WHERE codepoint=0x2033E').fetchone()
    db.close()
    rec = json.loads(row[0])
    para = next(p for p in rec['text_paragraphs'] if '八駿名' in p or '白𠌾' in p)
    i = para.find('或作')
    ctx = para[max(0, i-6):i+10]
    return {'sword': rec['sword'], 'unicode': rec['unicode'],
            'pua_other': rec['pua_other'], 'context': ctx,
            'context_codepoints': [f'U+{ord(c):04X}' for c in ctx],
            'note': 'Station writes 或作𠌾 (the headword again, U+2033E) where the woodblock shows the 亻+𫇮 variant; pua_other=[]. The gold transcription 〈亻𫇮〉 plus the screenshot structure (亻 + sheep-over-我 right part, distinct from 𠌾 ⿰亻莪) overrides the lazy repetition. First station-transcription-divergence case among E704-E712.'}


def capture():
    if (OUT/'audit.json').exists():
        raise SystemExit('Baseline already captured; refusing to overwrite historical evidence')
    OUT.mkdir(parents=True, exist_ok=True)
    LOCAL.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    mask_path = ROOT/'tools/dataset/font-sources/e712-scan-mask.png'
    context = Image.open(SCAN).convert('RGB')
    from PIL import ImageDraw
    ImageDraw.Draw(context).rectangle((2, 3, 108, 106), outline='#c43b32', width=2)
    context.resize((324, 324)).save(FIGURES/'page-context.png')
    shutil.copy2(ANNOTATION, LOCAL/'0512.gj.before')
    font_facts = [facts(ROOT/'guji-preview-grid/public/fonts'/name) for name in
                  ('guji-plane0.ttf', 'guji-plane2.ttf', 'guji-planef.ttf', 'guji-large.ttf')]
    assert not any(f['contains_E712'] for f in font_facts)
    needles = ['⿰亻𫇮']
    ids_sources = sorted((ROOT/'var/font-audit/0373/ids').glob('IDS*.txt')) + [
        ROOT/'var/font-audit/0373/babelstone-ids.txt', ROOT/'var/font-audit/0367/cjkvi-ids.txt']
    ids = []
    for path in ids_sources:
        lines = [s for s in path.read_text().splitlines() if s.startswith(('U+', 'U-'))]
        ids.append({'path': str(path.relative_to(ROOT)), 'sha256': sha(path), 'entries': len(lines),
                    'target_matches': [s for s in lines if any(n in s for n in needles)],
                    'head_entry': [s for s in lines if s.startswith(('U+2033E', 'U-0002033E'))]})
    search = json.loads((OUT/'font-search.json').read_text())
    write(OUT/'audit.json', {
        'captured_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
        'page': 512, 'headword': '𠌾', 'headword_codepoint': 'U+2033E', 'headword_order': 1,
        'context': '【字彙補】古文義字。白𠌾，八駿名。' + OLD,
        'target_ids': '⿰亻𫇮',
        'unicode_status': 'independent-codepoint-not-confirmed',
        'distinction': 'CHISE has no encoded ⿰亻𫇮. The component 𫇮 U+2B1EE is standard-encoded (plane2 in library); the headword 𠌾 U+2033E is itself ⿰亻莪 with a different right part. The woodblock draws a SHORT 亻; the composition keeps the full-height 𠌾 donor radical per the user instruction and the stylistic gap is documented.',
        'site_record': site_paragraph(),
        'source': {'page_path': str(PAGE), 'page_sha256': sha(PAGE),
                   'screenshot': str(SCAN.relative_to(ROOT)), 'screenshot_sha256': sha(SCAN),
                   'screenshot_note': 'User-provided site-zoom crop (crisp); archived per the E708/E710-E711 precedent, no raw-page crop taken.',
                   'mask': str(mask_path.relative_to(ROOT)), 'mask_sha256': sha(mask_path),
                   'mask_method': 'grayscale < 128, discard connected ink components smaller than 8 pixels'},
        'fonts_before': font_facts, 'ids_search': {'queries': needles, 'sources': ids},
        'shape_search': {'counts': {k: v['count'] for k, v in search.items()},
                         'reviewed': 'Top 48 of each small font via figures/e712/font-candidates.png.',
                         'result': 'No matching target found',
                         'limitation': 'Candidate ranking plus finite visual review; not manual examination of every glyph or proof of global Unicode absence.'},
        'calibration': 'chamfer-calibration.json: the short-亻 stylistic gap dominates (composition 3.672 vs wrong-right 𠌾 2.969), weak gate 4.4 only rejects gross breakage (left-only 11.355).',
        'allocation': {'cp': 'E712', 'note': 'E701, E704-E711 occupied; E702/E703 reserved historical slots; E712 absent from all four cmap tables.'},
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
    with TTFont(backup, recalcTimestamp=False) as before, TTFont(FONT0, recalcTimestamp=False) as after:
        verify_addition(before, after, CP)
        with TTFont(FONT2, recalcTimestamp=False) as donor:
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
        rejected = []
        for label in ('donor-hash-2033E', 'donor-hash-2B1EE', 'frozen-outline'):
            bad = copy.deepcopy(recipe)
            if label == 'donor-hash-2033E':
                bad['external_donors'][0]['glyph_sha256']['2033E'] = '0'*64
            elif label == 'donor-hash-2B1EE':
                bad['external_donors'][0]['glyph_sha256']['2B1EE'] = '0'*64
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
        assert current['sha256'] == old['sha256'] and not current['contains_E712']
        others.append(current)
    registry = json.loads((ROOT/'guji-preview-grid/src/pua-registry.json').read_text())
    entry = next(g for g in registry['glyphs'] if g['cp'] == 'E712')
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
              'non_overlap': 'Disjoint x bounds with at least 16 units of gap; both donors external (plane2), first such case.',
              'rebuild_matches_production': True, 'corruption_rejected': rejected,
              'registry_shared_hashes_match': True, 'rollback': audit['rollback']}
    record_path = OUT/'patch-verification.json'
    if record_path.exists():
        commits = json.loads(record_path.read_text()).get('git_commits')
        if commits:
            result['git_commits'] = commits
    write(record_path, result)
    old = (LOCAL/'0512.gj.before').read_text()
    new = ANNOTATION.read_text()
    assert old.count(OLD) == 1
    assert new == old.replace(OLD, NEW)
    write(OUT/'annotation.json', {'checked_at': result['checked_at'],
                                  'page': 512, 'path': str(ANNOTATION.relative_to(ROOT)),
                                  'sha256_before': audit['annotation_before']['sha256'], 'sha256_after': sha(ANNOTATION),
                                  'old': OLD, 'new': NEW, 'replacements': 1,
                                  'E712_count': new.count('\ue712'), 'other_text_unchanged': True,
                                  'git_scope': 'One local draft edit only; full untracked page excluded from font commit.'})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    args = parser.parse_args()
    capture() if args.capture else verify()
