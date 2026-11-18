#!/usr/bin/env python3
"""Incremental scan/synthetic OCR dataset builder. Run with --help."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import PIL
from PIL import Image, features
import fontTools
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths
from ocr_render import Fonts, FONT_NAMES, STYLE, render, draw_overlay
from ocr_scan import locate_scan, validate_box

SCHEMA = 'guji-ocr-build/1'
DEFAULT_OUTPUT = paths.VAR_DIR / 'datasets' / 'kangxi-ocr'
DEFAULT_REVIEWS = paths.REPO_ROOT / 'kangxi-gold' / 'scan-reviews'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def value_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def atomic_json(path, value):
    temp = path.with_suffix(path.suffix+'.tmp')
    write_json(temp, value); os.replace(temp, path)


def implementation_fingerprint():
    root = paths.REPO_ROOT
    files = sorted((root/'guji-preview-grid/src/ir').glob('*.ts'))
    files += sorted((root/'guji-preview-grid/src/parser').glob('*.ts'))
    files += sorted((root/'guji-preview-grid/src/semantics').glob('*'))
    files += sorted((root/'guji-preview-grid/src/datasets').glob('*.ts'))
    files += [root/'kangxi-gold/dataset-config.json']
    files += [HERE/'kangxi_semantics.py']
    files += [HERE/name for name in ('build_ocr_dataset.py', 'export_ocr_layout.mjs', 'annotation_source.mjs', 'ocr_render.py', 'ocr_scan.py')]
    files += [root/'tools/eval/kangxi_column_seg.py', root/'guji-preview-grid/src/pua-registry.json']
    files += [root/'guji-preview-grid/public/fonts'/name for name in FONT_NAMES]
    versions = {'python': sys.version.split()[0], 'pillow': PIL.__version__, 'numpy': np.__version__,
                'freetype': features.version('freetype2'),
                'fonttools': fontTools.__version__,
                'node': subprocess.check_output(['node', '--version'], text=True).strip()}
    return {'files': {str(p.relative_to(root)): digest(p) for p in files}, 'versions': versions,
            'style': STYLE, 'schema': SCHEMA}


def page_inputs(manifest_path, entry, images_dir, shared_hash, review_dir):
    source = manifest_path.parent/'annotations'/entry['annotations']['gj']
    image = images_dir/entry['image']
    source_hash, image_hash = digest(source), digest(image)
    if image_hash != entry['sha256']: raise ValueError('Image hash differs from source manifest')
    with Image.open(image) as im:
        if list(im.size) != [entry['width'], entry['height']]: raise ValueError('Image dimensions differ from manifest')
    review_path = review_dir/f"{entry['page']:04d}.json"
    review = read_json(review_path) if review_path.exists() else None
    if review and (review.get('source_sha256') != source_hash or review.get('image_sha256') != image_hash):
        raise ValueError('Scan review is stale; rebase/review against the changed source or image')
    config_path = manifest_path.parent/'dataset-config.json'
    config_hash = digest(config_path) if config_path.exists() else None
    inputs = {'dataset_config_sha256': config_hash, 'source_sha256': source_hash, 'image_sha256': image_hash,
              'proofread_status': entry['status'], 'page': entry['page'],
              'width': entry['width'], 'height': entry['height'], 'url': entry.get('url'),
              'implementation_sha256': shared_hash, 'scan_review': review}
    return inputs, value_hash(inputs), source, image


def intact(output, record):
    try:
        base = output/record['path']
        return bool(record.get('artifacts')) and all(digest(base/name) == sha for name, sha in record['artifacts'].items())
    except (OSError, KeyError):
        return False


def validate_annotation(annotation):
    if ''.join(g['text'] for g in annotation['glyphs']) != annotation['text']:
        raise ValueError('Glyph reading order mismatch')
    if ''.join(r['text'] for r in annotation['regions']) != annotation['text']:
        raise ValueError('Region reading order mismatch')
    for key in ('bands', 'regions', 'glyphs', 'gaps', 'decorations'):
        ids = [o['id'] for o in annotation[key]]
        if len(set(ids)) != len(ids): raise ValueError(f'Duplicate IDs: {key}')
        for obj in annotation[key]: validate_box(obj['bbox'], annotation['width'], annotation['height'])
    if annotation['domain'] == 'synthetic' and any(g['clipped'] for g in annotation['glyphs']):
        raise ValueError('Synthetic glyph is clipped')


def save_crops(root, domain, image_path, annotation):
    folder = root/'crops'/domain; folder.mkdir(parents=True)
    image = Image.open(image_path).convert('RGB'); records = []
    region_map = {r['id']: r for r in annotation['regions']}
    for obj in annotation['bands']+annotation['regions']:
        text = obj.get('text')
        if text is None: text = ''.join(region_map[k]['text'] for k in obj['region_ids'])
        if not text: continue
        b = obj['bbox']; crop = [int(np.floor(b[0])), int(np.floor(b[1])), int(np.ceil(b[2])), int(np.ceil(b[3]))]
        file = folder/(obj['id']+'.png'); image.crop(tuple(crop)).save(file)
        records.append({'id': obj['id'], 'image': str(file.relative_to(root)), 'text': text,
                        'domain': domain, 'bbox_in_page': crop, 'source_page': annotation['page'],
                        'geometry_status': annotation['geometry_status'],
                        'kind': obj.get('kind', 'band'), 'split_group': 'kangxi-wuyingdian-development'})
    return records


def build_page(output, entry, inputs, fingerprint, image_path, layout, fonts):
    parent = output/'objects'/f"{entry['page']:04d}"; parent.mkdir(parents=True, exist_ok=True)
    destination = parent/fingerprint
    staging = Path(tempfile.mkdtemp(prefix='.building-', dir=parent))
    try:
        shutil.copyfile(image_path, staging/'scan.jpg')
        (staging/'source.gj').write_text(layout['source'], encoding='utf-8')
        (staging/'text.txt').write_text(layout['transcription'], encoding='utf-8')
        write_json(staging/'ir.json', layout['ir'])
        synthetic = render(layout, entry['width'], entry['height'], fonts, staging/'synthetic.png')
        scan = locate_scan(layout, image_path, inputs['scan_review'])
        crop_records = []
        for domain, annotation, filename in [('synthetic', synthetic, 'synthetic.png'), ('scan', scan, 'scan.jpg')]:
            annotation.update(image=filename, image_sha256=digest(staging/filename),
                              proofread_status=entry['status'], source_page_id=f"kangxi-wuyingdian-{entry['page']:04d}",
                              split_group='kangxi-wuyingdian-development')
            validate_annotation(annotation)
            write_json(staging/f'{domain}.json', annotation)
            draw_overlay(staging/filename, annotation, staging/f'{domain}-overlay.jpg')
            crop_records += save_crops(staging, domain, staging/filename, annotation)
        write_json(staging/'crops.json', crop_records)
        write_json(staging/'provenance.json', inputs)
        artifacts = {str(p.relative_to(staging)): digest(p) for p in sorted(staging.rglob('*')) if p.is_file()}
        record = {'page': entry['page'], 'fingerprint': fingerprint,
                  'path': str(destination.relative_to(output)), 'proofread_status': entry['status'],
                  'source_sha256': inputs['source_sha256'], 'image_sha256': inputs['image_sha256'],
                  'artifacts': artifacts, 'counts': {'codepoints': len(layout['text']), 'regions': len(layout['regions']),
                  'glyphs': len(layout['glyphs']), 'bands': len(layout['bands']), 'crops': len(crop_records)},
                  'scan_quality_flags': scan['quality_flags'], 'band_geometry_status': scan['band_geometry_status']}
        if destination.exists():
            # Only this builder's reproducible revision is replaced after an integrity failure.
            backup = parent/(fingerprint+'.damaged-'+dt.datetime.now().strftime('%Y%m%d%H%M%S%f'))
            destination.rename(backup)
        staging.rename(destination)
        return record
    finally:
        if staging.exists(): shutil.rmtree(staging)


def export_indexes(output, records):
    pages = []; crops = []; viewer = []; pua = {}
    for record in records:
        base = output/record['path']
        a = {domain: read_json(base/f'{domain}.json') for domain in ('synthetic', 'scan')}
        for domain in a:
            pages.append({'source_page': record['page'], 'source_page_id': a[domain]['source_page_id'],
                          'image': record['path']+'/'+a[domain]['image'], 'text': a[domain]['text'],
                          'annotation': record['path']+'/'+domain+'.json', 'domain': domain,
                          'geometry_status': a[domain]['geometry_status'],
                          'split_group': a[domain]['split_group']})
        for c in read_json(base/'crops.json'):
            crops.append({**c, 'image': record['path']+'/'+c['image']})
        viewer.append({'page': record['page'], 'proofread_status': record['proofread_status'],
                       'source_sha256': record['source_sha256'], 'image_sha256': record['image_sha256'],
                       **a, 'synthetic_image': record['path']+'/synthetic.png', 'scan_image': record['path']+'/scan.jpg'})
        for glyph in a['synthetic']['glyphs']:
            for i, ch in enumerate(glyph['text']):
                cp = ord(ch)
                if 0xE000 <= cp <= 0xF8FF or 0xF0000 <= cp <= 0x10FFFD:
                    item = pua.setdefault(f'U+{cp:04X}', {'char': ch, 'font_files': glyph['font_files'], 'occurrences': []})
                    item['occurrences'].append({'page': record['page'], 'glyph_id': glyph['id'],
                                                'image': record['path']+'/synthetic.png', 'bbox': glyph['bbox']})
    for name, rows in [('pages.jsonl', pages), ('recognition.jsonl', crops)]:
        temp = output/(name+'.tmp')
        temp.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows), encoding='utf-8')
        os.replace(temp, output/name)
    registry = read_json(paths.REPO_ROOT/'guji-preview-grid/src/pua-registry.json')
    for cp, entry in pua.items():
        entry['registration'] = next((g for g in registry['glyphs'] if 'U+'+g['cp'] == cp), None)
        if entry['registration'] is None: entry['identity_status'] = 'font-specific PUA; semantic identity not adjudicated'
    atomic_json(output/'pua.json', pua)
    html = (HERE/'ocr_review.html').read_text(encoding='utf-8').replace('__DATA__', json.dumps(viewer, ensure_ascii=False).replace('<', '\\u003c'))
    (output/'review.html.tmp').write_text(html, encoding='utf-8'); os.replace(output/'review.html.tmp', output/'review.html')


def import_reviews(path, manifest_path, images_dir, review_dir):
    payload = read_json(path)
    if payload.get('schema') != 'guji-ocr-review/1': raise ValueError('Unknown review schema')
    manifest = read_json(manifest_path); entries = {e['page']: e for e in manifest['pages']}
    validated = []
    for key, proposed in payload['pages'].items():
        entry = entries[int(key)]; source = manifest_path.parent/'annotations'/entry['annotations']['gj']
        if proposed.get('source_sha256') != digest(source) or proposed.get('image_sha256') != digest(images_dir/entry['image']):
            raise ValueError(f'Stale review for {key}')
        for boxes in ('band_bboxes', 'region_bboxes'):
            for box in proposed.get(boxes, {}).values(): validate_box(box, entry['width'], entry['height'])
        result = subprocess.run(['node', str(HERE/'export_ocr_layout.mjs')], input=json.dumps({
            'manifest': str(manifest_path), 'pages': [entry['page']]}), text=True, capture_output=True, check=True)
        current_layout = json.loads(result.stdout)[0]
        for boxes, kind in [('band_bboxes','bands'), ('region_bboxes','regions')]:
            unknown = set(proposed.get(boxes, {}))-{v['id'] for v in current_layout[kind]}
            if unknown: raise ValueError(f'Unknown review IDs: {sorted(unknown)}')
        if proposed.get('band_geometry_status', 'proposed') not in ('proposed', 'reviewed'):
            raise ValueError('Invalid review state')
        destination = review_dir/f"{entry['page']:04d}.json"
        previous = read_json(destination) if destination.exists() else {}
        if previous and (previous.get('source_sha256') != proposed['source_sha256'] or previous.get('image_sha256') != proposed['image_sha256']):
            raise ValueError(f'Existing review stale for {key}; archive it explicitly before replacing')
        merged = {**previous, **proposed}
        for boxes in ('band_bboxes', 'region_bboxes'): merged[boxes] = {**previous.get(boxes, {}), **proposed.get(boxes, {})}
        validated.append((destination, merged))
    review_dir.mkdir(parents=True, exist_ok=True)
    for destination, merged in validated: atomic_json(destination, merged)


def build(args):
    manifest_path = args.manifest.resolve(); output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    manifest = read_json(manifest_path)
    images_dir = args.images_dir or Path(manifest['images_dir'])
    if not images_dir.is_absolute(): images_dir = manifest_path.parent/images_dir
    lock = (output/'.build.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        if args.import_review: import_reviews(args.import_review, manifest_path, images_dir, args.review_dir)
        shared = implementation_fingerprint(); shared_hash = value_hash(shared)
        old = read_json(output/'manifest.json') if (output/'manifest.json').exists() else {}
        old_records = {r['page']: r for r in old.get('pages', [])}
        eligible = [e for e in manifest['pages'] if e.get('status') in ('first', 'final')]
        selected = set(int(p.strip().lstrip('@')) for p in args.pages.split(',')) if args.pages else {e['page'] for e in eligible}
        unknown = selected-{e['page'] for e in eligible}
        if unknown: raise ValueError(f'Pages missing or not first/final: {sorted(unknown)}')
        pending = []; active = []; errors = []; skipped = []; deferred = []
        for entry in sorted(eligible, key=lambda e: e['page']):
            no = entry['page']
            try:
                inputs, fingerprint, source, image = page_inputs(manifest_path, entry, images_dir, shared_hash, args.review_dir)
                prior = old_records.get(no)
                if (not args.force or no not in selected) and prior and prior['fingerprint'] == fingerprint and intact(output, prior):
                    active.append(prior); skipped.append(no)
                elif no in selected: pending.append((entry, inputs, fingerprint, image))
                else: deferred.append(no)
            except Exception as error: errors.append({'page': no, 'error': str(error)})
        built = []
        if pending:
            request = {'manifest': str(manifest_path), 'pages': [e['page'] for e, *_ in pending]}
            # Parse pages independently so one malformed page does not block all valid pages.
            fonts = Fonts(paths.REPO_ROOT/'guji-preview-grid/public/fonts')
            for entry, inputs, fingerprint, image in pending:
                try:
                    result = subprocess.run(['node', str(HERE/'export_ocr_layout.mjs')],
                        input=json.dumps({**request, 'pages': [entry['page']]}), text=True, capture_output=True, check=True)
                    layout = json.loads(result.stdout)[0]
                    if layout['source_sha256'] != inputs['source_sha256']: raise ValueError('Source changed during build')
                    record = build_page(output, entry, inputs, fingerprint, image, layout, fonts)
                    # Detect an editor save or scan replacement during generation.
                    if digest(manifest_path.parent/'annotations'/entry['annotations']['gj']) != inputs['source_sha256'] or digest(image) != inputs['image_sha256']:
                        raise ValueError('Inputs changed during build; rerun')
                    active.append(record); built.append(entry['page'])
                    print(f"built @{entry['page']}: {record['counts']['codepoints']} codepoints", flush=True)
                except Exception as error:
                    detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
                    errors.append({'page': entry['page'], 'error': detail})
        # A proofer may save or change status while a long build runs. Never publish stale active rows.
        current_entries = {e['page']: e for e in read_json(manifest_path)['pages'] if e.get('status') in ('first','final')}
        verified = []
        for record in active:
            if record['page'] not in current_entries: continue
            try:
                now = page_inputs(manifest_path, current_entries[record['page']], images_dir, shared_hash, args.review_dir)
                if now[1] != record['fingerprint']: raise ValueError('Inputs changed during build; rerun')
                verified.append(record)
            except Exception as error: errors.append({'page': record['page'], 'error': str(error)})
        active = sorted(verified, key=lambda r: r['page'])
        export_indexes(output, active)
        index = {'schema': SCHEMA, 'built_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                 'source_manifest': str(manifest_path), 'source_manifest_sha256': digest(manifest_path),
                 'implementation': shared, 'split_policy': 'All current pages are development; no random train/test split.',
                 'scan_policy': 'All automatically projected region/glyph boxes are proposals, not localization gold.',
                 'pages': active, 'errors': errors, 'deferred_pages': deferred}
        atomic_json(output/'manifest.json', index)
        report = {'built': built, 'skipped': skipped, 'active_pages': len(active), 'errors': errors, 'deferred': deferred,
                  'output': str(output), 'review': str(output/'review.html')}
        atomic_json(output/'last-build.json', report)
        print(json.dumps(report, ensure_ascii=False))
        return 1 if errors else 0
    finally:
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=paths.REPO_ROOT/'kangxi-gold/manifest.json')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--images-dir', type=Path)
    parser.add_argument('--review-dir', type=Path, default=DEFAULT_REVIEWS)
    parser.add_argument('--pages', help='Optional comma-separated first/final pages; default all eligible pages')
    parser.add_argument('--force', action='store_true', help='Rebuild selected pages even when hashes match')
    parser.add_argument('--import-review', type=Path, help='Import downloaded review JSON before building')
    args = parser.parse_args()
    try: return build(args)
    except Exception as error:
        print(f'Build failed: {error}', file=sys.stderr); return 1


if __name__ == '__main__':
    raise SystemExit(main())
