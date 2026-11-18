"""Image-evidenced scan proposals; never promoted to human gold automatically."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'eval'))
import kangxi_column_seg as segmentation
from ocr_render import pixel_annotation


def fit_vertical(dark, glyphs, x1, x2, initial_top, initial_pitch, rows):
    """Fit grid phase/step to ink inside glyph slots and whitespace at boundaries.

    Large slots use their full height; blank rows exert no false glyph pressure.
    Search is bounded around detected page frame. Score is a heuristic, not confidence.
    """
    if not glyphs:
        return initial_top, initial_pitch, None
    x1, x2 = max(0, round(x1+3)), min(dark.shape[1], round(x2-3))
    profile = dark[:, x1:x2].mean(axis=1)
    profile = np.convolve(profile, np.ones(5)/5, mode='same')
    ys = np.arange(len(profile))
    best = (-float('inf'), initial_top, initial_pitch)
    # Use unique row spans: parallel small columns should not double-weight a row.
    spans = sorted({(g['grid_bbox'][1], g['grid_bbox'][3]) for g in glyphs})
    for pitch in np.arange(initial_pitch*.96, initial_pitch*1.04+.01, .3):
        for top in np.arange(initial_top-22, initial_top+22.1, 1.5):
            centers = np.array([top+(a+b)*pitch/2 for a, b in spans])
            edges = np.array([top+a*pitch for a, b in spans] + [top+b*pitch for a, b in spans])
            inside = sum(np.interp(centers+delta*pitch, ys, profile).mean() for delta in (-.18, 0, .18))/3
            boundary = np.interp(edges, ys, profile).mean()
            score = inside-.55*boundary-.000015*(top-initial_top)**2-.002*(pitch-initial_pitch)**2
            if top < initial_top-8 or top+rows*pitch > initial_top+rows*initial_pitch+8: continue
            if score > best[0]: best = (float(score), float(top), float(pitch))
    return best[1], best[2], round(best[0], 5)


def select_body_grid(fits):
    """Reject wider frame choices that trade leftmost body text for the spine.

    A short/clipped fishtail can escape fishtail_x. With the same left frame,
    adding the right-hand spine can produce MORE valley support, but shifts the
    16-slot grid right and leaves body text uncovered on the left (@313/@323).
    Compare alternative frames sharing that left edge (including double rules): keep the wider choice
    only if its added width isn't largely lost again at the grid's left edge.
    A clipped image edge is not a measured left rule; different left edges
    remain independent (cropped scans such as @312/@330/@402).
    """
    def grid_left(fit):
        return fit['bx0'] + fit['lines'][-1]

    body_fits = []
    for box, fit in fits:
        includes_spine = any(
            inner[0] > segmentation.SMOOTH_K
            and abs(inner[0] - box[0]) <= inner_fit['pitch'] / 3
            and box[2] - inner[2] >= inner_fit['pitch'] * .5
            and 0 <= grid_left(inner_fit) - inner_fit['bx0'] <= inner_fit['pitch'] * .5
            and grid_left(fit) - grid_left(inner_fit) >= (box[2] - inner[2]) * .5
            for inner, inner_fit in fits
        )
        if not includes_spine:
            body_fits.append((box, fit))
    return max(body_fits, key=lambda pair: pair[1]['n_ev'])


def detect_grid(dark):
    """Use frame evidence only, explicitly exclude the spine/fishtail strip."""
    height, width = dark.shape
    candidates = segmentation.frame_candidates(dark, 960)
    tail = segmentation.fishtail_x(dark, width*.55)
    if tail is not None: candidates = [b for b in candidates if b[2] < tail-12]
    fits = [(b, segmentation._fit_for_block(dark, b, segmentation.PITCH_RANGE)) for b in candidates]
    fits = [(b, f) for b, f in fits if f]
    if not fits: raise ValueError('No scan frame/grid evidence; provide a reviewed page with supported layout')
    box, fit = select_body_grid(fits)
    # The old locator may pick the footer as bottom; locate long horizontal frame strokes.
    left, _, right, _ = box
    profile = dark[:, max(left+20, 80):min(right-20, width-80)].mean(axis=1)
    def border(lo, hi, top):
        groups = []
        for y in np.where(profile[lo:hi] > .50)[0]+lo:
            if not groups or y > groups[-1][-1]+2: groups.append([])
            groups[-1].append(int(y))
        if not groups: raise ValueError('Horizontal frame edge is ambiguous; review required')
        group = max(groups, key=lambda g: float(profile[g].sum()))
        return group[-1]+3 if top else group[0]-3
    y0 = border(int(height*.05), int(height*.25), True)
    y1 = border(int(height*.78), int(height*.97), False)
    boundaries = [float(v+fit['bx0']) for v in fit['lines']]
    majors = []
    for j in range(8):
        minors = [{'bound': 'detected' if fit['evidence'][k] and fit['evidence'][k+1] else 'grid'}
                  for k in (2*j, 2*j+1)]
        majors.append({'x1': boundaries[2*j+2], 'x2': boundaries[2*j], 'minors': minors})
    return {'block': [left, y0, right, y1], 'block_src': 'scan-frame', 'pitch': fit['pitch'],
            'lines_evidence': f"{fit['n_ev']}/17", 'fishtail_x': tail, 'majors': majors}


def locate_scan(layout, image_path, review=None):
    image = Image.open(image_path).convert('L'); width, height = image.size
    if layout['cols'] != 16 or len(layout['bands']) != 8:
        raise ValueError('Scan locator currently requires the Kangxi 8-band / 16-slot profile')
    dark = (np.asarray(image) < segmentation.DARK_THR).astype(float)
    # No mutable OCR cache/database participates in a reproducible dataset build.
    detected = detect_grid(dark)
    _, y0, _, y1 = detected['block']
    top = y0; pitch = (y1-y0)/layout['rows']
    band_boxes = {}; evidence = []
    for band, major in zip(layout['bands'], detected['majors']):
        glyphs = [g for g in layout['glyphs'] if g['band_id'] == band['id']]
        bt, bp, score = fit_vertical(dark, glyphs, major['x1'], major['x2'], top, pitch, layout['rows'])
        box = [major['x1'], bt, major['x2'], bt+bp*layout['rows']]
        band_boxes[band['id']] = box
        evidence.append({'band_id': band['id'], 'method': 'scan-valleys+bounded-vertical-ink-fit',
                         'score': score, 'minor_bounds': [m['bound'] for m in major['minors']]})
    review = review or {}
    known_bands = set(band_boxes)
    for key, box in review.get('band_bboxes', {}).items():
        if key not in known_bands: raise ValueError(f'Unknown reviewed band {key}')
        validate_box(box, width, height)
        band_boxes[key] = box
    band_grid = {b['id']: b['grid_bbox'] for b in layout['bands']}

    def mapper(band_id, b):
        x1, y1, x2, y2 = band_boxes[band_id]; grid = band_grid[band_id]
        ux = (x2-x1)/(grid[2]-grid[0]); uy = (y2-y1)/layout['rows']
        return [x1+(b[0]-grid[0])*ux, y1+b[1]*uy, x1+(b[2]-grid[0])*ux, y1+b[3]*uy]

    annotation = pixel_annotation(layout, width, height, 'scan', mapper)
    annotation.update(geometry_status='proposed', bbox_type='estimated-layout-cell',
                      method='image-grid+IR-local-layout/1',
                      band_geometry_status=review.get('band_geometry_status', 'proposed'),
                      alignment={'column_detection': detected, 'bands': evidence},
                      review=copy.deepcopy(review))
    # Explicit region corrections are useful without asserting child glyph accuracy.
    known_regions = {r['id']: r for r in annotation['regions']}
    for key, box in review.get('region_bboxes', {}).items():
        if key not in known_regions: raise ValueError(f'Unknown reviewed region {key}')
        validate_box(box, width, height)
        known_regions[key]['bbox'] = box
        known_regions[key]['geometry_status'] = 'reviewed'
    boxes = [b['bbox'] for b in annotation['bands']]
    x1, y1 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x2, y2 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    annotation['content_bbox'] = [x1, y1, x2, y2]
    annotation['ignore_regions'] = [
        {'bbox': b, 'reason': 'outside-transcribed-body'} for b in
        ([0, 0, width, y1], [0, y2, width, height], [0, y1, x1, y2], [x2, y1, width, y2])
        if b[2] > b[0] and b[3] > b[1]]
    annotation['quality_flags'] = []
    if any(g['clipped'] for g in annotation['glyphs']): annotation['quality_flags'].append('clipped-glyph-proposals')
    for region in annotation['regions']:
        a, b, c, d = [round(v) for v in region['bbox']]
        region['ink_fraction'] = round(float(dark[b:d, a:c].mean()), 5) if d>b and c>a else 0
        region.setdefault('geometry_status', 'proposed')
        if region['ink_fraction'] < .015: annotation['quality_flags'].append('low-ink:'+region['id'])
    return annotation


def validate_box(box, width, height):
    if not isinstance(box, list) or len(box) != 4 or not all(isinstance(v, (int, float)) and np.isfinite(v) for v in box):
        raise ValueError(f'Invalid bbox: {box}')
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError(f'Out-of-image bbox: {box}')
