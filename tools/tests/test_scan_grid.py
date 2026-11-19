"""Grid preview uses scan evidence without producing or writing text proposals."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dataset'))
from scan_grid import scan_grid
from ocr_scan import _scan_centered_rows, detect_blank_cells, detect_grid, select_body_grid, slanted_body_candidates


class ScanGridTests(unittest.TestCase):
    def test_p445_centered_small_text_does_not_create_a_corner_space(self):
        fixture = Path(__file__).parent / 'fixtures' / 'kangxi-0445.jpg'
        with tempfile.TemporaryDirectory() as temp:
            manifest = Path(temp) / 'manifest.json'
            manifest.write_text(json.dumps({'images_dir': str(fixture.parent.resolve()),
                                            'pages': [{'page': 445, 'image': fixture.name}]}))
            result = scan_grid({'page': 445}, manifest)
        found = {(c['band'], c['col'], c['row']) for c in result['blank_cells']}
        # The false right-hand corner of 文 is the only removed candidate;
        # every existing space elsewhere on the scan remains available.
        self.assertEqual(found, {
            (0, 0, 9), (0, 0, 21), (0, 1, 2), (1, 0, 10), (1, 0, 19),
            (2, 0, 3), (3, 0, 0), (3, 0, 21), (3, 1, 7),
            (5, 0, 11), (5, 1, 7), (7, 1, 17),
        })
        # Do not "fix" this by moving the grid back to the draft-based fit.
        self.assertAlmostEqual(result['bands'][4][1], 178.5)
        with Image.open(fixture) as image:
            gray = np.asarray(image.convert('L'))
        for band, rows in ((4, {0, 1}), (5, {14, 15})):
            for shift in (-6, -3, 0, 3, 6):
                with self.subTest(band=band, shift=shift):
                    left, top, right, bottom = result['bands'][band]
                    box = [left, top + shift, right, bottom + shift]
                    self.assertEqual(_scan_centered_rows(gray, box), rows)
                    cells = detect_blank_cells(gray, [box])
                    self.assertFalse(any(c['row'] in rows for c in cells))

    def test_other_scanned_centered_runs_keep_their_whole_character_slots(self):
        fixtures = Path(__file__).parent / 'fixtures'
        for case in json.loads((fixtures / 'kangxi-centered-runs.json').read_text()):
            with self.subTest(page=case['page']):
                with Image.open(fixtures / case['image']) as image:
                    gray = np.asarray(image.convert('L'))
                self.assertEqual(_scan_centered_rows(gray, case['box']), set(case['rows']))
                self.assertEqual(detect_blank_cells(gray, [case['box']]), [])

    def test_centered_run_keeps_adjacent_empty_rows_and_requires_neighbour_evidence(self):
        gray = np.full((1440, 120), 220, dtype=np.uint8)
        # Two small characters straddle the middle. Each has disconnected
        # upper and lower strokes, so no single component describes its slot.
        for row in (2, 3):
            y = row * 60
            gray[y + 10:y + 13, 40:80] = 40
            gray[y + 5:y + 22, 58:62] = 40
            gray[y + 25:y + 45, 45:49] = 40
            gray[y + 25:y + 45, 73:77] = 40
            gray[y + 25:y + 29, 45:77] = 40
            gray[y + 41:y + 45, 45:77] = 40
        box = [0, 0, 120, 1440]
        self.assertEqual(_scan_centered_rows(gray, box), {2, 3})
        found = {(c['col'], c['row']) for c in detect_blank_cells(gray, [box])}
        for col in (0, 1):
            for row in (2, 3):
                self.assertNotIn((col, row), found)
            for row in (1, 4):
                self.assertIn((col, row), found)
        gray[180:240] = 220
        self.assertEqual(_scan_centered_rows(gray, box), set())

    def test_centered_protection_rejects_normal_columns_radicals_and_rules(self):
        for variant in ('single-column', 'two-columns', 'detached-radical', 'thin-strokes', 'rule'):
            for mirror in (False, True):
                with self.subTest(variant=variant, mirror=mirror):
                    gray = np.full((1440, 120), 220, dtype=np.uint8)
                    for row in (2, 3):
                        y = row * 60
                        if variant in ('single-column', 'two-columns', 'detached-radical'):
                            gray[y + 10:y + 45, 15:20] = 40
                            gray[y + 10:y + 14, 15:50] = 40
                            gray[y + 40:y + 45, 15:50] = 40
                        if variant == 'two-columns':
                            gray[y + 10:y + 45, 75:80] = 40
                            gray[y + 10:y + 14, 75:110] = 40
                        if variant == 'detached-radical':
                            gray[y + 20:y + 38, 55:66] = 40
                        if variant == 'thin-strokes':
                            gray[y + 10:y + 45, 59:61] = 40
                    if variant == 'rule':
                        gray[110:250, 59:61] = 40
                        gray[110:113, 40:61] = 40
                    if mirror:
                        gray = gray[:, ::-1].copy()
                    self.assertEqual(_scan_centered_rows(gray, [0, 0, 120, 1440]), set())
                    if variant == 'single-column':
                        found = {(c['col'], c['row']) for c in detect_blank_cells(gray, [[0, 0, 120, 1440]])}
                        empty_col = 0 if mirror else 1
                        for row in (2, 3):
                            self.assertIn((empty_col, row), found)

    def test_p443_recovers_body_when_fishtail_excludes_every_frame(self):
        fixture = Path(__file__).parent / 'fixtures' / 'kangxi-0443.jpg'
        with Image.open(fixture) as image:
            dark = (np.asarray(image.convert('L')) < 140).astype(float)
        with patch('ocr_scan.slanted_body_candidates', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'No scan frame/grid evidence'):
                detect_grid(dark)
        detected = detect_grid(dark)
        self.assertAlmostEqual(detected['block'][2], 1036, delta=3)
        self.assertLess(detected['block'][2], detected['fishtail_x'] - 12)
        self.assertEqual(len(detected['majors']), 8)
        self.assertAlmostEqual(detected['majors'][0]['x2'], 1029, delta=3)
        self.assertAlmostEqual(detected['majors'][-1]['x1'], 53, delta=3)
        for major in detected['majors']:
            self.assertTrue(110 < major['x2'] - major['x1'] < 130)

    def test_fishtail_recovery_requires_a_body_rule_left_of_the_tail(self):
        for body_rule, tail_left in ((True, 1052), (False, 1052), (True, 1025)):
            with self.subTest(body_rule=body_rule, tail_left=tail_left):
                image = Image.new('L', (1130, 1665), 255)
                draw = ImageDraw.Draw(image)
                for line in ((78, 116, 78, 1540), (1108, 116, 1108, 1540),
                             (78, 116, 1108, 116), (78, 1540, 1108, 1540)):
                    draw.line(line, fill=0, width=8)
                if body_rule:
                    draw.line((1026, 120, 1040, 1536), fill=0, width=2)
                for col in range(17):
                    for row in range(24):
                        x, y = 108 + 58 * col, 138 + 58 * row
                        draw.rectangle((x, y, x + 25, y + 12), fill=0)
                draw.rectangle((tail_left, 180, 1094, 520), fill=0)
                dark = (np.asarray(image) < 140).astype(float)
                if body_rule and tail_left == 1052:
                    result = detect_grid(dark)
                    self.assertAlmostEqual(result['block'][2], 1034, delta=3)
                    self.assertEqual(len(result['majors']), 8)
                else:
                    # Neither the original spine frame nor a recovered rule
                    # on the wrong side of the fishtail is a usable body frame.
                    with self.assertRaisesRegex(ValueError, 'No scan frame/grid evidence'):
                        detect_grid(dark)

    def test_slanted_body_rule_recovers_grid_from_spine_frame(self):
        # @405: the thin body rule slopes across x=1026..1040, so no fixed
        # column reaches 50% ink. Only the outer spine frame was detected.
        image = Image.new('L', (1130, 1665), 255)
        draw = ImageDraw.Draw(image)
        for line in ((78, 116, 78, 1540), (1108, 116, 1108, 1540),
                     (78, 116, 1108, 116), (78, 1540, 1108, 1540)):
            draw.line(line, fill=0, width=8)
        draw.line((1026, 120, 1040, 1536), fill=0, width=2)
        # Sixteen text columns plus ink in the spine; no OCR/text prior.
        for col in range(17):
            for row in range(24):
                x, y = 108 + 58 * col, 138 + 58 * row
                draw.rectangle((x, y, x + 25, y + 12), fill=0)
        dark = (np.asarray(image) < 140).astype(float)
        with patch('ocr_scan.slanted_body_candidates', return_value=[]):
            before = detect_grid(dark)
        after = detect_grid(dark)
        self.assertEqual(before['block'][2], 1108)
        self.assertAlmostEqual(after['block'][2], 1034, delta=3)
        self.assertLess(after['majors'][-1]['x1'], 110)
        self.assertLess(after['majors'][0]['x2'], 1040)
        self.assertGreater(before['majors'][-1]['x1'] - after['majors'][-1]['x1'], 29)
        self.assertEqual(len(after['majors']), 8)

    def test_slanted_rule_recovery_rejects_unsupported_or_distant_edges(self):
        box = (78, 116, 1108, 1646)
        fit = {'lines': [72], 'pitch': 58.6}
        dark = np.zeros((1665, 1130))
        for y in range(120, 1536):
            x = round(1026 + (y - 120) * 14 / 1416)
            dark[y, x:x + 2] = 1
        self.assertEqual(len(slanted_body_candidates(dark, box, fit)), 1)
        self.assertEqual(slanted_body_candidates(dark, (1, 116, 1108, 1646), fit), [])
        self.assertEqual(slanted_body_candidates(dark, box, {'lines': [15], 'pitch': 58.6}), [])
        # A distant rule must not shrink a sparse page to an unrelated frame.
        self.assertEqual(slanted_body_candidates(
            np.roll(dark, -153, axis=1), (53, 136, 1012, 1554), {'lines': [90], 'pitch': 53}), [])
        dark[::2] = 0  # Disconnected glyph strokes cannot stand in for a rule.
        self.assertEqual(slanted_body_candidates(dark, box, fit), [])

    def test_partly_faded_body_rule_recovers_grid_from_spine_frame(self):
        # @419: a long thin body rule survives above a faded section, but the
        # whole corridor has only about 80% ink support. The spine still has
        # enough valleys to attract the grid one small column to the right.
        image = Image.new('L', (1130, 1665), 255)
        draw = ImageDraw.Draw(image)
        for line in ((56, 156, 56, 1540), (1104, 156, 1104, 1540),
                     (56, 156, 1104, 156), (56, 1540, 1104, 1540)):
            draw.line(line, fill=0, width=8)
        draw.line((1028, 160, 1042, 1536), fill=0, width=2)
        draw.rectangle((1020, 990, 1050, 1190), fill=255)
        for col in range(17):
            for row in range(24):
                x, y = 85 + 60 * col, 176 + 55 * row
                draw.rectangle((x, y, x + 25, y + 12), fill=0)
        dark = (np.asarray(image) < 140).astype(float)
        with patch('ocr_scan.slanted_body_candidates', return_value=[]):
            before = detect_grid(dark)
        after = detect_grid(dark)
        self.assertEqual(before['block'][2], 1104)
        self.assertAlmostEqual(after['block'][2], 1035, delta=3)
        self.assertLess(after['majors'][-1]['x1'], 90)
        self.assertLess(after['majors'][0]['x2'], 1040)
        self.assertGreater(before['majors'][-1]['x1'] - after['majors'][-1]['x1'], 30)

    def test_dense_disconnected_strokes_do_not_replace_a_faded_rule(self):
        dark = np.zeros((1665, 1130))
        for y in range(120, 1536):
            if y % 58 < 48:  # >80% total support, without a sustained rule.
                x = round(1026 + (y - 120) * 14 / 1416)
                dark[y, x:x + 2] = 1
        self.assertEqual(slanted_body_candidates(
            dark, (56, 156, 1104, 1646), {'lines': [66], 'pitch': 60.4}), [])

    def test_spine_valleys_cannot_displace_leftmost_body_column(self):
        # Measured @313 and @323 candidates. The spine's extra valleys used to
        # win 13:10 / 13:11 even though the leftmost small column was omitted.
        for left, candidates, expected_right in [
            (85, [(1048, 107, 58.4, 10), (1108, 168, 58.6, 12), (1123, 156.4, 59.6, 13)], 1048),
            (57, [(1023, 79, 58.8, 11), (1087, 130, 59.4, 11), (1096, 130, 60, 13), (1117, 119.6, 61.4, 7)], 1023),
        ]:
            fits = [((left, 150, right, 1560), {'bx0': left + 6,
                     'lines': [start - left - 6], 'pitch': pitch, 'n_ev': support})
                    for right, start, pitch, support in candidates]
            for ordered in (fits, list(reversed(fits))):
                with self.subTest(left=left):
                    box, _ = select_body_grid(ordered)
                    self.assertEqual(box[2], expected_right)

    def test_cropped_left_edge_and_nearby_double_frame_remain_valid(self):
        # @312/@330 need the outer candidate with a different/cropped left edge.
        for candidates, expected in [
            ([(51, 1014, 58.2, 58.8, 5), (51, 997, 57.8, 58.2, 9), (1, 1014, 49.6, 59.4, 10)], (1, 1014)),
            ([(60, 1026, 68.6, 57.4, 5), (60, 1041, 67, 60, 6), (4, 1041, 59.6, 60.4, 13)], (4, 1041)),
            ([(53, 1010, 60.6, 58.4, 9), (1, 937, 7.4, 57.6, 7), (1, 1010, 48.8, 59.2, 15)], (1, 1010)),
            # A too-narrow region whose fit escapes the frame cannot veto it.
            ([(110, 1073, 117.2, 58.8, 0), (110, 1125, 138.8, 61.2, 2), (110, 809, -229, 50, 0)], (110, 1125)),
            # @411's two measured left rules must not rescue the spine frame.
            ([(97, 1055, 104, 59, 9), (97, 1127, 154, 60.2, 15), (81, 1127, 154, 60.4, 14)], (97, 1055)),
        ]:
            fits = [((left, 150, right, 1560), {'bx0': left + 6,
                     'lines': [start - left - 6], 'pitch': pitch, 'n_ev': support})
                    for left, right, start, pitch, support in candidates]
            box, _ = select_body_grid(fits)
            self.assertEqual((box[0], box[2]), expected)

    def test_empty_bands_keep_detected_frame_and_full_height(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            Image.new('L', (1130, 1679), 255).save(root / '0312.png')
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'images_dir': '.', 'pages': [{'page': 312, 'image': '0312.png'}]}))
            detected = {'block': [40, 160, 1000, 1560], 'majors': [
                {'x1': 880 - i * 120, 'x2': 1000 - i * 120} for i in range(8)]}
            with patch('scan_grid.detect_grid', return_value=detected):
                result = scan_grid({'page': 312}, manifest)
            self.assertEqual(result['bands'], [[880 - i * 120, 160, 1000 - i * 120, 1560] for i in range(8)])
            self.assertEqual(len(result['blank_cells']), 8 * 2 * 24)
            self.assertEqual(set(result), {'ok', 'width', 'height', 'bands', 'blank_cells'})
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['0312.png', 'manifest.json'])

    def test_invalid_pages_are_rejected_before_image_access(self):
        for page in (0, 7739, -1, 1.5, True, '427', None):
            with self.subTest(page=page), self.assertRaises(ValueError):
                scan_grid({'page': page}, Path('/missing'))

    def test_blank_detection_uses_pixels_and_preserves_thin_strokes(self):
        gray = np.full((1440, 120), 220, dtype=np.uint8)
        gray[145, 20:40] = 40  # A thin 一 below the total ink-fraction threshold.
        gray[201:205, 25:28] = 40  # Small but connected 丶.
        gray[265:267, 25:27] = 40  # Tiny paper fleck.
        gray[300:305, :] = 40  # Frame/book rule at a cell edge.
        gray[360:420, :60] = 166
        gray[361:420:4, 3:60:4] = 135  # Dark paper grain, not printed strokes.
        gray[420:480, :60] = 0  # Solid ink must never become "blank" by local thresholding.
        # A scanned large 一 bridges both columns; no transcription is provided.
        gray[55:65, 10:110] = 40
        cells = detect_blank_cells(gray, [[0, 0, 120, 1440]])
        found = {(c['col'], c['row']) for c in cells}
        self.assertTrue(all(row >= 2 for _, row in found))
        for row in (2, 3, 7):
            self.assertNotIn((0, row), found)
        for row in (4, 5, 6):
            self.assertIn((0, row), found)
        self.assertIn((1, 2), found)  # Empty image cell with no source-space requirement.

    def test_clipped_cells_are_unknown_not_blank(self):
        gray = np.full((1440, 120), 220, dtype=np.uint8)
        cells = detect_blank_cells(gray, [[-60, 0, 60, 1440]])
        self.assertEqual(len(cells), 24)
        self.assertTrue(all(c['col'] == 1 for c in cells))

    def test_p415_leading_space_with_paper_fleck(self):
        # Original grayscale pixels from @415: the top three rows of band 6.
        # The speck before 又 must be blank; 女/王/充 and 又/集 remain ink.
        fixture = Path(__file__).parent / 'fixtures' / 'kangxi-0415-leading-space.png'
        with Image.open(fixture) as image:
            gray = np.asarray(image.convert('L'))
        cells = detect_blank_cells(gray, [[0, .5, 118, 1405.46]])
        self.assertEqual(cells, [{'band': 0, 'col': 1, 'row': 0}])

    def test_sparse_faint_line_and_dark_dot_remain_ink(self):
        gray = np.full((1440, 120), 220, dtype=np.uint8)
        gray[25, 20:40] = 130  # Pale, one-pixel 一 below the ink-density cutoff.
        gray[85:89, 25:28] = 110  # Small coherent 丶 still counts as ink.
        gray[145:150, 20:40] = 130  # A pale glyph body uses the softer threshold.
        cells = detect_blank_cells(gray, [[0, 0, 120, 1440]])
        found = {(c['col'], c['row']) for c in cells}
        for row in range(3):
            self.assertNotIn((0, row), found)
            self.assertIn((1, row), found)

    def test_book_rule_requires_continuation_and_outward_corner(self):
        # A rule entering the left edge of the right small column. Its lower
        # corner turns back toward the title in the neighbouring column.
        for side in ('left', 'right'):
            for variant in ('frame', 'broken-frame', 'single-stroke', 'no-corner', 'disconnected', 'inward-corner'):
                with self.subTest(side=side, variant=variant):
                    gray = np.full((1440, 120), 220, dtype=np.uint8)
                    gray[65:174, 72:74] = 100
                    if variant == 'single-stroke':
                        gray[65:130, 72:74] = 220
                    elif variant == 'disconnected':
                        gray[108:132, 72:74] = 220
                    if variant not in ('no-corner', 'single-stroke', 'disconnected'):
                        if variant == 'inward-corner':
                            gray[172:175, 72:96] = 100
                        else:
                            gray[172:175, 48:74] = 100
                    if variant == 'broken-frame':
                        for y in (84, 102, 130, 145, 160):
                            gray[y:y + 4, 72:74] = 220
                    col = 1
                    if side == 'right':
                        gray = gray[:, ::-1].copy()
                        col = 0
                    found = {(c['col'], c['row']) for c in detect_blank_cells(gray, [[0, 0, 120, 1440]])}
                    self.assertEqual((col, 2) in found, variant in ('frame', 'broken-frame'))

    def test_rule_removal_keeps_nearby_glyph_ink(self):
        for stroke in ('thin-horizontal', 'thin-vertical', 'dot', 'faint-radical'):
            with self.subTest(stroke=stroke):
                gray = np.full((1440, 120), 220, dtype=np.uint8)
                gray[65:174, 72:74] = 100
                gray[172:175, 48:74] = 100
                if stroke == 'thin-horizontal':
                    gray[146, 72:98] = 130
                elif stroke == 'thin-vertical':
                    gray[135:161, 78] = 130
                elif stroke == 'dot':
                    gray[143:147, 78:81] = 100
                else:
                    gray[138:160, 78:80] = 130
                    gray[143, 77:86] = 130
                found = {(c['col'], c['row']) for c in detect_blank_cells(gray, [[0, 0, 120, 1440]])}
                self.assertNotIn((1, 2), found)

    def test_large_strokes_are_located_from_scan_and_leave_adjacent_gaps(self):
        for shape in ('horizontal', 'vertical', 'ding', 'bu'):
            with self.subTest(shape=shape):
                gray = np.full((1440, 120), 220, dtype=np.uint8)
                if shape in ('horizontal', 'ding'):
                    gray[175:185, 10:110] = 40
                if shape in ('vertical', 'ding', 'bu'):
                    gray[130:230, 55:65] = 40
                if shape == 'bu':
                    gray[155:165, 55:92] = 40
                found = {(c['col'], c['row']) for c in detect_blank_cells(gray, [[0, 0, 120, 1440]])}
                for col in range(2):
                    for row in (2, 3):
                        self.assertNotIn((col, row), found)
                    for row in (1, 4):
                        self.assertIn((col, row), found)

    def test_bottom_frame_joined_to_ordinary_glyphs_does_not_hide_previous_blank(self):
        gray = np.full((1440, 120), 220, dtype=np.uint8)
        # As on @466, the bottom rule touches ordinary glyphs in both small
        # columns. Their combined component spans the major band but remains
        # a single small-text row, so row 22 must not become a protected large
        # slot. A large interior 一 is covered by the preceding test.
        gray[1437:1440, :] = 40
        for x in (15, 75):
            gray[1390:1438, x:x + 5] = 40
            gray[1390:1395, x:x + 35] = 40
        found = {(c['col'], c['row']) for c in detect_blank_cells(gray, [[0, 0, 120, 1440]])}
        for col in (0, 1):
            self.assertIn((col, 22), found)
            self.assertNotIn((col, 23), found)

    def test_p427_scan_is_independent_of_draft_and_recovers_all_reported_gaps(self):
        fixture = Path(__file__).parent / 'fixtures' / 'kangxi-0427.jpg'
        with tempfile.TemporaryDirectory() as temp:
            manifest = Path(temp) / 'manifest.json'
            manifest.write_text(json.dumps({'images_dir': str(fixture.parent.resolve()),
                                            'pages': [{'page': 427, 'image': fixture.name}]}))
            result = scan_grid({'page': 427}, manifest)
            # Legacy clients may still send an uncalibrated draft. Neither
            # its large rows nor their movement can change image results.
            for rows in ([[5, 7], [11, 13], [17, 19]], [[6, 8], [12, 14], [18, 20]]):
                self.assertEqual(scan_grid({'page': 427, 'spans': [rows] * 8}, manifest), result)
        found = {(c['band'], c['col'], c['row']) for c in result['blank_cells']}
        self.assertEqual(found, {
            (0, 0, 3), (0, 0, 17), (0, 1, 0), (0, 1, 10), (0, 1, 20),
            (1, 0, 5), (1, 0, 11), (1, 0, 17), (2, 1, 20),
            (3, 0, 15), (3, 1, 1), (4, 0, 9), (4, 0, 19), (4, 1, 2), (4, 1, 5),
            (6, 0, 13), (6, 1, 7), (7, 0, 4), (7, 0, 8),
        })

    def test_scanned_large_heads_preserve_the_blank_above_them(self):
        fixtures = Path(__file__).parent / 'fixtures'
        cases = json.loads((fixtures / 'kangxi-scan-large-gaps.json').read_text())
        for case in cases:
            with self.subTest(page=case['page']):
                with Image.open(fixtures / case['image']) as image:
                    gray = np.asarray(image.convert('L'))
                found = {(c['col'], c['row']) for c in detect_blank_cells(gray, [case['band_box']])}
                for cell in case['blank']:
                    self.assertIn(tuple(cell), found)
                for cell in case['occupied']:
                    self.assertNotIn(tuple(cell), found)


if __name__ == '__main__':
    unittest.main()
