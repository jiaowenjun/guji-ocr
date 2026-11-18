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
from ocr_scan import detect_blank_cells, detect_grid, select_body_grid, slanted_body_candidates


class ScanGridTests(unittest.TestCase):
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
                result = scan_grid({'page': 312, 'spans': [[] for _ in range(8)]}, manifest)
            self.assertEqual(result['bands'], [[880 - i * 120, 160, 1000 - i * 120, 1560] for i in range(8)])
            self.assertEqual(len(result['blank_cells']), 8 * 2 * 24)
            self.assertEqual(set(result), {'ok', 'width', 'height', 'bands', 'blank_cells'})
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['0312.png', 'manifest.json'])

    def test_invalid_row_spans_are_rejected_before_image_access(self):
        for span in ([0, 25], [-1, 1], [2, 2], [0, 1.5], [False, 1]):
            with self.subTest(span=span), self.assertRaises(ValueError):
                scan_grid({'page': 312, 'spans': [[span]] + [[] for _ in range(7)]}, Path('/missing'))

    def test_blank_detection_uses_pixels_and_preserves_thin_strokes(self):
        gray = np.full((1440, 120), 220, dtype=np.uint8)
        gray[145, 20:40] = 40  # A thin 一 below the total ink-fraction threshold.
        gray[201:205, 25:28] = 40  # Small but connected 丶.
        gray[265:267, 25:27] = 40  # Tiny paper fleck.
        gray[300:305, :] = 40  # Frame/book rule at a cell edge.
        gray[360:420, :60] = 166
        gray[361:420:4, 3:60:4] = 135  # Dark paper grain, not printed strokes.
        gray[420:480, :60] = 0  # Solid ink must never become "blank" by local thresholding.
        # Rows 0/1 form a large glyph: don't highlight its white quadrants.
        # The row-4 small glyph prior deliberately disagrees with the image.
        cells = detect_blank_cells(gray, [[0, 0, 120, 1440]], [[[0, 2], [4, 5]]])
        found = {(c['col'], c['row']) for c in cells}
        self.assertTrue(all(row >= 2 for _, row in found))
        for row in (2, 3, 7):
            self.assertNotIn((0, row), found)
        for row in (4, 5, 6):
            self.assertIn((0, row), found)
        self.assertIn((1, 2), found)  # Empty image cell with no source-space requirement.

    def test_clipped_cells_are_unknown_not_blank(self):
        gray = np.full((1440, 120), 220, dtype=np.uint8)
        cells = detect_blank_cells(gray, [[-60, 0, 60, 1440]], [[]])
        self.assertEqual(len(cells), 24)
        self.assertTrue(all(c['col'] == 1 for c in cells))

    def test_p415_leading_space_with_paper_fleck(self):
        # Original grayscale pixels from @415: the top three rows of band 6.
        # The speck before 又 must be blank; 女/王/充 and 又/集 remain ink.
        fixture = Path(__file__).parent / 'fixtures' / 'kangxi-0415-leading-space.png'
        with Image.open(fixture) as image:
            gray = np.asarray(image.convert('L'))
        cells = detect_blank_cells(gray, [[0, .5, 118, 1405.46]], [[]])
        self.assertEqual(cells, [{'band': 0, 'col': 1, 'row': 0}])

    def test_sparse_faint_line_and_dark_dot_remain_ink(self):
        gray = np.full((1440, 120), 220, dtype=np.uint8)
        gray[25, 20:40] = 130  # Pale, one-pixel 一 below the ink-density cutoff.
        gray[85:89, 25:28] = 110  # Small coherent 丶 still counts as ink.
        gray[145:150, 20:40] = 130  # A pale glyph body uses the softer threshold.
        cells = detect_blank_cells(gray, [[0, 0, 120, 1440]], [[]])
        found = {(c['col'], c['row']) for c in cells}
        for row in range(3):
            self.assertNotIn((0, row), found)
            self.assertIn((1, row), found)


if __name__ == '__main__':
    unittest.main()
