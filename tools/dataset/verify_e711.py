#!/usr/bin/env python3
"""Capture the E711 baseline or verify its recorded insertion and donor recipe."""
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

from guji_ren_juan_components import ROOT, FONT0, FONT2, RECIPE, SCAN, FIGURES, make_recipe
from guji_pua_patch import build_compose, verify_addition

OUT = ROOT/'docs/research/evidence/e711'
LOCAL = ROOT/'var/font-audit/0480-e711'
ANNOTATION = ROOT/'kangxi-gold/annotations/0480.gj'
PAGE = Path('/Volumes/WD-2T/guji-ocr/raw/kangxizidian/pages/0480.jpg')
CRAWL_DB = ROOT/'var/crawl/kangxi-crawl.sqlite3'
CP = 0xE711
OLD = '人部作〈亻𠨟〉，'
NEW = '人部作\ue711，'


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
            'contains_E711': CP in cmap,
            'unmapped_count': len(set(font.getGlyphOrder())-set(cmap.values())),
            'format14': any(t.format == 14 for t in font['cmap'].tables),
            'gsub_features': ([r.FeatureTag for r in font['GSUB'].table.FeatureList.FeatureRecord]
                              if 'GSUB' in font else []),
        }


def site_paragraph():
    """The station's own record transcribes the form descriptively as 〈亻𠨟〉
    with the encoded component 𠨟 U+20A1F, and assigns no PUA of its own."""
    db = sqlite3.connect(CRAWL_DB)
    row = db.execute('SELECT record_json FROM entries WHERE codepoint=0x5026').fetchone()
    db.close()
    rec = json.loads(row[0])
    para = next(p for p in rec['text_paragraphs'] if '音義同' in p)
    i = para.find('人部作')
    ctx = para[i:i+8]
    return {'sword': rec['sword'], 'unicode': rec['unicode'],
            'pua_other': rec['pua_other'], 'context': ctx,
            'context_codepoints': [f'U+{ord(c):04X}' for c in ctx],
            'note': 'Station writes the descriptive pair 〈亻𠨟〉 with the encoded component U+20A1F and assigns no PUA slot; unlike E710 the component itself is standard-encoded, only the composite is not.'}


def capture():
    if (OUT/'audit.json').exists():
        raise SystemExit('Baseline already captured; refusing to overwrite historical evidence')
    OUT.mkdir(parents=True, exist_ok=True)
    LOCAL.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    mask_path = ROOT/'tools/dataset/font-sources/e711-scan-mask.png'
    context = Image.open(SCAN).convert('RGB')
    from PIL import ImageDraw
    ImageDraw.Draw(context).rectangle((4, 12, 118, 117), outline='#c43b32', width=2)
    context.resize((372, 372)).save(FIGURES/'page-context.png')
    shutil.copy2(ANNOTATION, LOCAL/'0480.gj.before')
    font_facts = [facts(ROOT/'guji-preview-grid/public/fonts'/name) for name in
                  ('guji-plane0.ttf', 'guji-plane2.ttf', 'guji-planef.ttf', 'guji-large.ttf')]
    assert not any(f['contains_E711'] for f in font_facts)
    needles = ['⿰亻𠨟']
    ids_sources = sorted((ROOT/'var/font-audit/0373/ids').glob('IDS*.txt')) + [
        ROOT/'var/font-audit/0373/babelstone-ids.txt', ROOT/'var/font-audit/0367/cjkvi-ids.txt']
    ids = []
    for path in ids_sources:
        lines = [s for s in path.read_text().splitlines() if s.startswith(('U+', 'U-'))]
        ids.append({'path': str(path.relative_to(ROOT)), 'sha256': sha(path), 'entries': len(lines),
                    'target_matches': [s for s in lines if any(n in s for n in needles)],
                    'zao_entry': [s for s in lines if s.startswith(('U+20A1F', 'U-00020A1F'))]})
    search = json.loads((OUT/'font-search.json').read_text())
    write(OUT/'audit.json', {
        'captured_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
        'page': 480, 'headword': '倦', 'headword_codepoint': 'U+5026', 'headword_order': 1,
        'context': '【說文】力部作𠢏，' + OLD + '音義同。',
        'target_ids': '⿰亻𠨟',
        'unicode_status': 'independent-codepoint-not-confirmed',
        'distinction': 'CHISE has no encoded ⿰亻𠨟. The component 𠨟 U+20A1F is itself encoded (IDS ⿵⿱釆大㔾) and lives in plane2, as does the 力部 sibling 𠢏 U+2088F cited in the same note. 倦 U+5026 is ⿰亻卷 — its right part is not 𠨟, so 倦 cannot stand in for the target. The woodblock draws a SHORT 亻 (head ~27% down); the composition keeps the full-height 倦 donor radical per the user instruction and the stylistic gap is documented, not hidden.',
        'site_record': site_paragraph(),
        'source': {'page_path': str(PAGE), 'page_sha256': sha(PAGE),
                   'screenshot': str(SCAN.relative_to(ROOT)), 'screenshot_sha256': sha(SCAN),
                   'screenshot_note': 'User-provided site-zoom crop (crisp); archived as scan source per the E708/E710 precedent, no raw-page crop taken for this slot.',
                   'mask': str(mask_path.relative_to(ROOT)), 'mask_sha256': sha(mask_path),
                   'mask_method': 'grayscale < 128, discard connected ink components smaller than 8 pixels'},
        'fonts_before': font_facts, 'ids_search': {'queries': needles, 'sources': ids},
        'shape_search': {'counts': {k: v['count'] for k, v in search.items()},
                         'reviewed': 'Top 48 of each small font via figures/e711/font-candidates.png.',
                         'result': 'No matching target found',
                         'limitation': 'Candidate ranking plus finite visual review; not manual examination of every glyph or proof of global Unicode absence.'},
        'calibration': 'chamfer-calibration.json: the short-亻 stylistic gap dominates (composition 3.377 vs bare 𠨟 2.321 and wrong-right 倦 3.311), so the metric does not discriminate identity here; weak gate 4.0 only rejects gross breakage (left-only 9.763).',
        'allocation': {'cp': 'E711', 'note': 'E701, E704-E710 occupied; E702/E703 reserved historical slots; E711 absent from all four cmap tables.'},
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
        for label in ('internal-donor-hash', 'external-donor-hash', 'frozen-outline'):
            bad = copy.deepcopy(recipe)
            if label == 'internal-donor-hash':
                bad['donor_glyph_sha256']['5026'] = '0'*64
            elif label == 'external-donor-hash':
                bad['external_donors'][0]['glyph_sha256']['20A1F'] = '0'*64
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
        assert current['sha256'] == old['sha256'] and not current['contains_E711']
        others.append(current)
    registry = json.loads((ROOT/'guji-preview-grid/src/pua-registry.json').read_text())
    entry = next(g for g in registry['glyphs'] if g['cp'] == 'E711')
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
              'non_overlap': 'Disjoint x bounds with at least 17 units of gap; the radical and the compressed 𠨟 cannot intersect.',
              'rebuild_matches_production': True, 'corruption_rejected': rejected,
              'registry_shared_hashes_match': True, 'rollback': audit['rollback']}
    record_path = OUT/'patch-verification.json'
    if record_path.exists():
        commits = json.loads(record_path.read_text()).get('git_commits')
        if commits:
            result['git_commits'] = commits
    write(record_path, result)
    old = (LOCAL/'0480.gj.before').read_text()
    new = ANNOTATION.read_text()
    assert old.count(OLD) == 1
    assert new == old.replace(OLD, NEW)
    write(OUT/'annotation.json', {'checked_at': result['checked_at'],
                                  'page': 480, 'path': str(ANNOTATION.relative_to(ROOT)),
                                  'sha256_before': audit['annotation_before']['sha256'], 'sha256_after': sha(ANNOTATION),
                                  'old': OLD, 'new': NEW, 'replacements': 1,
                                  'E711_count': new.count('\ue711'), 'other_text_unchanged': True,
                                  'git_scope': 'One local draft edit only; full untracked page excluded from font commit.'})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    args = parser.parse_args()
    capture() if args.capture else verify()
