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


def slanted_body_candidates(dark, box, fit):
    """Recover a thin/slightly broken rule missed by the column projection.

    Only retry when a measured left frame loses over half a small column. A
    slightly slanted rule (@405) can have <50% ink at every fixed x, but remains
    present on >90% of rows within a +/-6 px corridor. A faded section (@419)
    may reduce total support to >75%; then also require >90% support over a
    half-band window, so repeated disconnected glyph strokes do not qualify.
    Search one small column inside the selected right frame; do not reinterpret
    cropped left edges or distant rules in sparse pages as a body boundary.
    """
    left, top, right, bottom = box
    pitch = fit['pitch']
    if left <= segmentation.SMOOTH_K or fit['lines'][-1] <= pitch * .5:
        return []
    height, width = dark.shape
    band = dark[int(height * .2):int(height * .8)] > 0
    nearby = np.zeros_like(band)
    radius = 6
    for offset in range(-radius, radius + 1):
        dst = slice(max(0, offset), min(width, width + offset))
        src = slice(max(0, -offset), min(width, width - offset))
        nearby[:, dst] |= band[:, src]
    support = nearby.mean(axis=0)
    half = len(nearby) // 2
    sustained = np.maximum.reduce([
        nearby[start:start + half].mean(axis=0)
        for start in (0, len(nearby) // 4, len(nearby) - half)
    ])
    xs = np.flatnonzero((support > .9) | ((support > .75) & (sustained > .9)))
    groups = []
    for x in xs:
        if not groups or x > groups[-1][-1] + 3:
            groups.append([])
        groups[-1].append(int(x))
    candidates = []
    for group in groups:
        # Keep the original center when the rule already has full support;
        # accepting its faded fringe must not move a previously stable grid.
        strong = [x for x in group if support[x] > .9]
        inner = int(np.mean(strong or group))
        if (.5 * pitch <= right - inner <= 1.5 * pitch
                and inner - left >= segmentation.N_SLOTS * segmentation.PITCH_RANGE[0]):
            candidates.append((left, top, inner, bottom))
    return candidates


def detect_grid(dark):
    """Use frame evidence only, explicitly exclude the spine/fishtail strip."""
    height, width = dark.shape
    raw_candidates = segmentation.frame_candidates(dark, 960)
    tail = segmentation.fishtail_x(dark, width*.55)
    candidates = [b for b in raw_candidates if tail is None or b[2] < tail-12]
    fits = [(b, segmentation._fit_for_block(dark, b, segmentation.PITCH_RANGE)) for b in candidates]
    fits = [(b, f) for b, f in fits if f]
    if fits:
        recovery_seeds = [select_body_grid(fits)]
    else:
        # @443: the thin body rule slopes, leaving only spine frames, all
        # excluded by the fishtail. Use those frames solely to search inward;
        # they must never become accepted fits without a measured body rule.
        recovery_seeds = [(b, segmentation._fit_for_block(dark, b, segmentation.PITCH_RANGE))
                          for b in raw_candidates if b not in candidates]
        recovery_seeds = [(b, f) for b, f in recovery_seeds if f]
    for box, fit in recovery_seeds:
        for candidate in slanted_body_candidates(dark, box, fit):
            if tail is not None and candidate[2] >= tail-12:
                continue
            recovered = segmentation._fit_for_block(dark, candidate, segmentation.PITCH_RANGE)
            if recovered and 0 <= recovered['lines'][-1] <= recovered['pitch'] * .5:
                fits.append((candidate, recovered))
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


def _has_ink_stroke(mask, minimum_span=0):
    """Require enough connected ink, optionally with an extended stroke span."""
    remaining = {tuple(point) for point in np.argwhere(mask)}
    minimum = max(6, int(np.ceil(mask.size * .006)))
    while remaining:
        stack = [remaining.pop()]
        area = 0
        ymin = ymax = stack[0][0]
        xmin = xmax = stack[0][1]
        while stack:
            y, x = stack.pop()
            area += 1
            ymin, ymax = min(ymin, y), max(ymax, y)
            xmin, xmax = min(xmin, x), max(xmax, x)
            if area >= minimum and max(ymax - ymin + 1, xmax - xmin + 1) >= minimum_span:
                return True
            for dy, dx in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
                neighbor = (y + dy, x + dx)
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
    return False


def _ink_components(mask):
    """8-connected ink bounds/areas, using row runs without a SciPy dependency."""
    parents, bounds = [], []

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    previous = []
    for y, row in enumerate(mask):
        edges = np.flatnonzero(np.diff(np.r_[False, row, False]))
        current = []
        first = 0
        for x1, x2 in zip(edges[::2], edges[1::2]):
            i = len(parents)
            parents.append(i)
            bounds.append([int(x1), y, int(x2), y + 1, int(x2 - x1)])
            while first < len(previous) and previous[first][1] < x1:
                first += 1
            for a, b, j in previous[first:]:
                if a > x2:
                    break
                j = root(j)
                if j == i:
                    continue
                parents[j] = i
                old, new = bounds[j], bounds[i]
                bounds[i] = [min(old[0], new[0]), min(old[1], new[1]),
                             max(old[2], new[2]), max(old[3], new[3]), old[4] + new[4]]
            current.append((x1, x2, i))
        previous = current
    return [bounds[i] for i in range(len(parents)) if parents[i] == i]


def _scan_large_rows(gray, box):
    """Protect large-glyph whitespace only where scan strokes span small slots.

    Wide strokes bridge the two columns; a tall, thick central stroke also
    supports narrow heads such as 丨. Thin book rules and page rules do not.
    No draft glyph positions participate in this decision.
    """
    left, top, right, bottom = box
    cw, ch = (right - left) / 2, (bottom - top) / 24
    if cw <= 0 or ch <= 0:
        return set()
    x0, x2 = max(0, int(np.ceil(left + cw * .1))), min(gray.shape[1], int(right - cw * .1))
    y0, y2 = max(0, int(np.ceil(top))), min(gray.shape[0], int(bottom))
    if x2 <= x0 or y2 <= y0:
        return set()
    rows = set()
    strip = gray[y0:y2, x0:x2] < segmentation.DARK_THR
    components = _ink_components(strip)
    # A complete two-row ink window keeps an upper bar with the rest of its
    # glyph rather than assigning the preceding blank row to that bar.
    weights = np.zeros(strip.shape[0])
    for a, b, c, d, area in components:
        cx = x0 + (a + c) / 2
        if (area / (d - b) >= cw * .08 and d - b <= ch * 2.25
                and (c - a > cw * .95 or abs(cx - (left + right) / 2) < cw * .3)):
            weights[b:d] += strip[b:d, a:c].sum(axis=1)
    ys = y0 + np.arange(len(weights)) + .5
    for a, b, c, d, area in components:
        w, h = c - a, d - b
        cx = x0 + (a + c) / 2
        if a == 0 and c == strip.shape[1] and h < ch * .3:
            continue  # A horizontal rule continuing beyond both band edges.
        wide = w > cw * 1.05 and area / w >= ch * .08
        centre = (left + right) / 2
        central = (w < cw * 1.1 and area / h >= cw * .08
                   and ((h > ch * 1.15 and abs(cx - centre) < cw * .35)
                        or (h > ch * .5 and x0 + a >= centre - cw * .3
                            and x0 + c <= centre + cw * .3)))
        mid = (left + right) / 2 - x0
        centre_ink = strip[b:d, max(a, int(mid - cw * .15)):min(c, int(np.ceil(mid + cw * .15)))]
        thick_centre = np.count_nonzero(centre_ink.sum(axis=1) >= cw * .08) >= min(h * .4, ch * .3)
        if not (wide or (central and thick_centre)) or h > ch * 2.05:
            continue
        local_weights = weights
        if central and not wide and h < ch:
            # A small glyph's detached radical can lean into the band centre
            # (e.g. 郞). Its companion ink at a small-column centre rules out 丶.
            if any(min(d, dd) - max(b, bb) > h * .5
                   and abs(x0 + (aa + cc) / 2 - centre) > cw * .3
                   and dd - bb > ch * .3 and size / (dd - bb) >= cw * .08
                   for aa, bb, cc, dd, size in components):
                continue
            # A central 丶 can belong to a multi-dot head. Include nearby dots
            # in both columns, without pulling a preceding wide glyph into it.
            local_weights = np.zeros_like(weights)
            for aa, bb, cc, dd, size in components:
                if (cc - aa < cw * .7 and dd - bb < ch and size / (dd - bb) >= cw * .08
                        and bb < d + ch and dd > b - ch):
                    local_weights[bb:dd] += strip[bb:dd, aa:cc].sum(axis=1)
        candidates = []
        for start in range(23):
            if y0 + b < top + (start - .12) * ch or y0 + d > top + (start + 2.12) * ch:
                continue
            # A triangular window rewards the full glyph's centre of ink;
            # neighbouring small text near the two-row edges contributes less.
            kernel = np.maximum(0, 1 - np.abs((ys - top) / ch - start - 1))
            candidates.append((float(local_weights @ kernel), start))
        if candidates:
            _, start = max(candidates)
            rows.update((start, start + 1))
    return rows


def _has_rule_return(gray, x1, x2, endpoint, outward, cw, ch, threshold):
    """A connected corner turns toward the neighbouring title, not this cell."""
    reach = int(np.ceil(cw * .2))
    left = max(0, x1 - int(np.ceil(cw * .5)) if outward < 0 else x1)
    right = min(gray.shape[1], x2 if outward < 0 else x2 + int(np.ceil(cw * .5)))
    top, bottom = max(0, endpoint - int(np.ceil(ch * .25))), min(gray.shape[0], endpoint + int(np.ceil(ch * .25)) + 1)
    for a, b, c, d, _ in _ink_components(gray[top:bottom, left:right] < threshold):
        if (left + c > x1 and left + a < x2
                and top + b <= endpoint + ch * .1 and top + d >= endpoint - ch * .1
                and ((outward < 0 and left + a <= x1 - reach)
                     or (outward > 0 and left + c >= x2 + reach))):
            return True
    return False


def _book_rule_mask(gray, cell, core_box, threshold):
    """Mask only thin edge rules with continuation AND an outward frame corner.

    A single-cell 丨/亻, repeated disconnected vertical strokes, and horizontal
    strokes are not rules. The normal core inset and ink thresholds stay intact.
    """
    x1, y1, x2, y2 = cell
    a, b, c, d = core_box
    cw, ch = x2 - x1, y2 - y1
    core = gray[b:d, a:c]
    result = np.zeros(core.shape, dtype=bool)
    columns = np.flatnonzero((core < threshold).any(axis=0)) + a
    groups = []
    for x in columns:
        if not groups or x > groups[-1][-1] + 1:
            groups.append([])
        groups[-1].append(int(x))
    for group in groups:
        lo, hi = group[0], group[-1] + 1
        if hi - lo > max(3, cw * .08):
            continue
        outward = -1 if hi <= x1 + cw * .25 else 1 if lo >= x2 - cw * .25 else 0
        if not outward:
            continue
        # One pixel of drift on each side; only this corridor can be masked.
        lo, hi = max(a, lo - 1), min(c, hi + 1)
        top, bottom = max(0, int(y1 - ch)), min(gray.shape[0], int(np.ceil(y2 + ch)))
        support = np.flatnonzero((gray[top:bottom, lo:hi] < threshold).any(axis=1)) + top
        runs = np.split(support, np.flatnonzero(np.diff(support) > max(2, int(ch * .15)) + 1) + 1)
        for run in runs:
            if not len(run):
                continue
            first, last = int(run[0]), int(run[-1])
            if (last - first + 1 < ch * 1.35 or len(run) / (last - first + 1) < .65
                    or np.count_nonzero((run >= b) & (run < d)) < (d - b) * .45
                    or not (first < y1 - ch * .4 or last > y2 + ch * .4)):
                continue
            if any(_has_rule_return(gray, lo, hi, end, outward, cw, ch, threshold) for end in (first, last)):
                result[max(0, first - b):min(d - b, last - b + 1), lo - a:hi - a] = True
    return result


def detect_blank_cells(gray, band_boxes):
    """Image-derived empty small cells, not transcribed gaps.

    Large-glyph protection and book-rule removal require scan evidence, never
    draft row spans. Includes untranscribed empty areas. Inset 16% avoids adjacent ink;
    local paper tone limits the dark threshold. Sparse compact marks need a
    darker coherent core; extended fine strokes retain the softer threshold.
    """
    height, width = gray.shape
    blanks = []
    for band, (left, top, right, bottom) in enumerate(band_boxes):
        cw, ch = (right - left) / 2, (bottom - top) / 24
        large_rows = _scan_large_rows(gray, (left, top, right, bottom))
        for col in range(2):
            for row in range(24):
                if row in large_rows:
                    continue
                x1, y1 = left + col * cw, top + row * ch
                x2, y2 = x1 + cw, y1 + ch
                # Cropped/invalid cells are unknown, not empty.
                if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                    continue
                core_box = (int(np.ceil(x1 + cw * .16)), int(np.ceil(y1 + ch * .16)),
                            int(np.floor(x2 - cw * .16)), int(np.floor(y2 - ch * .16)))
                a, b, c, d = core_box
                core = gray[b:d, a:c]
                if min(core.shape) < 4:
                    continue
                threshold = np.clip(np.percentile(core, 80) - 35, 70, segmentation.DARK_THR)
                ink = core < threshold
                rule = _book_rule_mask(gray, (x1, y1, x2, y2), core_box, threshold) if ink.any() else np.zeros(core.shape, dtype=bool)
                ink = ink & ~rule
                # A fleck's gray fringe can just reach the component-size cutoff
                # (@415, before 又). Keep dense/faint glyphs at the original
                # threshold, and preserve even pale thin strokes spanning 1/4
                # of the core; compact dots must also have a coherent dark core.
                if (ink.mean() < .015
                        and not _has_ink_stroke((core < threshold - 20) & ~rule)
                        and not _has_ink_stroke(ink, minimum_span=np.ceil(min(core.shape) * .25))):
                    blanks.append({'band': band, 'col': col, 'row': row})
    return blanks


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
