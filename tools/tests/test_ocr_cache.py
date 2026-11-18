"""缓存、预取及重试契约；临时文件 + 模拟 OCR，无网络。"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dataset'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'eval'))
import kangxi_page_tool as kpt
from prefetch_ocr import cache_valid

TEXT = '天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏'


class OcrCacheTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.image = self.root / 'scan.jpg'
        self.image.write_bytes(b'image')
        self.store = Mock()
        self.store.get_page.return_value = {'scan_sha256': 'sha', 'scan_file': str(self.image)}
        p = patch.object(kpt.paths, 'OCR_CACHE_DIR', self.root / 'cache')
        p.start(); self.addCleanup(p.stop)
        kpt.paths.OCR_CACHE_DIR.mkdir()

    def test_status_reader_and_prefetch_agree(self):
        f = kpt.paths.OCR_CACHE_DIR / '0367.json'
        for md, sha, model, state in [('', 'sha', 'paddle', 'invalid'), ('寧', 'sha', 'paddle', 'invalid'),
                (TEXT, 'old', 'paddle', 'stale'), (TEXT, 'sha', 'other', 'stale'),
                (TEXT, 'sha', 'paddle', 'valid')]:
            f.write_text(json.dumps({'sha256': sha, 'model': model, 'markdown': md}))
            self.assertEqual(kpt._ocr_cache_meta(367, 'sha')['state'], state)
            self.assertEqual(cache_valid(367, self.store), state == 'valid')
            self.assertEqual(kpt._ocr_cache_read(367, self.store), md if state == 'valid' else None)
        f.write_text('broken')
        self.assertEqual(kpt._ocr_cache_meta(367, 'sha')['state'], 'invalid')
        f.unlink()
        self.assertEqual(kpt._ocr_cache_meta(367, 'sha')['state'], 'none')

    def test_failure_retries_then_cache_is_used_and_image_changes_invalidate(self):
        with patch.object(kpt, 'ocr_submit_markdown', side_effect=[None, TEXT, TEXT]) as submit:
            self.assertIsNone(kpt.page_ocr(367, store=self.store))
            self.assertFalse((kpt.paths.OCR_CACHE_DIR / '0367.json').exists())
            self.assertEqual(kpt.page_ocr(367, store=self.store), TEXT)
            self.assertEqual(kpt.page_ocr(367, store=self.store), TEXT)
            self.assertEqual(submit.call_count, 2)
            self.store.get_page.return_value['scan_sha256'] = 'new-sha'
            self.assertEqual(kpt.page_ocr(367, store=self.store), TEXT)
            self.assertEqual(submit.call_count, 3)

    def test_invalid_write_preserves_good_cache(self):
        self.assertTrue(kpt.ocr_cache_write(367, self.store, TEXT))
        self.assertFalse(kpt.ocr_cache_write(367, self.store, '寧'))
        self.assertEqual(kpt._ocr_cache_read(367, self.store), TEXT)

    def test_alignment_reads_cache_without_submitting_ocr(self):
        with patch.object(kpt, 'ocr_submit_markdown', side_effect=AssertionError('read submitted OCR')):
            end, _, _ = kpt.ocr_page_cut(367, TEXT, self.store)
            self.assertIsNone(end)
            bands = [[TEXT]]
            self.assertEqual(kpt.ocr_fold_page_lines(367, bands, self.store)[0], bands)
            self.assertFalse((kpt.paths.OCR_CACHE_DIR / '0367.json').exists())

    def test_partial_columns_survive_and_retry_only_failed_columns(self):
        image = Mock(width=100)
        image.__enter__ = Mock(return_value=image)
        image.__exit__ = Mock(return_value=False)
        pil = types.ModuleType('PIL')
        pil.Image = Mock()
        pil.Image.open.return_value = image
        seg = {'block': [0, 0, 100, 100], 'majors': [{'x1': i * 10, 'x2': i * 10 + 10} for i in range(8)]}
        with patch.dict(sys.modules, {'PIL': pil}), patch.object(kpt, 'page_columns', return_value=seg), \
             patch.object(kpt, 'ocr_service_up', return_value=True), \
             patch.object(kpt, 'ocr_submit_markdown', side_effect=['', None, '甲', '乙', '丙', '丁', '戊', '己', '补成']) as submit:
            partial = kpt.page_column_ocr(367, store=self.store)
            self.assertFalse(kpt.column_ocr_complete(partial))
            self.assertFalse(kpt.column_cache_valid(367, self.store))
            complete = kpt.page_column_ocr(367, store=self.store)
            self.assertEqual(submit.call_count, 9)
            self.assertEqual(complete[0]['markdown'], '')
            self.assertEqual(complete[1]['markdown'], '补成')
            self.assertTrue(kpt.column_cache_valid(367, self.store))
            self.assertEqual(kpt.page_column_ocr(367, store=self.store), complete)
            self.assertEqual(submit.call_count, 9)
