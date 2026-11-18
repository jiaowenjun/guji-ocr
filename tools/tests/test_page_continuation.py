"""跨页续入回归：临时词条库、标注及 OCR 缓存，不依赖外置盘或联网。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))
import kangxi_page_tool as kpt


class ShortPageContinuationTest(unittest.TestCase):
    # @370→371：廣韻在词条内重复，OCR 有两个错字，不能靠短串全局搜索定位。
    paragraphs = [
        "【廣韻】寫耶切【正韻】思遮切，𠀤瀉平聲。",
        "【廣韻】少也。",
        "【集韻】或作𡭟。　又【集韻】桑何切，音娑。挽歌聲。　又【韻會】蘇箇切，娑去聲。語辭也。",
        "【楚辭·招魂】何爲四方些。",
        "【註】沈存中筆談，夔峽湖湘人，凡禁呪語末云娑婆訶，三合而爲些也。　又同娑。邏些，吐蕃城名。又麼些，禿光些，皆蠻族。",
    ]

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.annotations = root / "annotations"
        self.annotations.mkdir()
        self.cache = root / "ocr-cache"
        self.cache.mkdir()
        self.prev = self.annotations / "0370.gj"
        self.prev.write_text("@370\n\n#些\n【廣\n韻】\n")
        db = root / "crawl.sqlite3"
        kpt.kangxi_store.KangxiStore(db).save_entry("些", {"text_paragraphs": self.paragraphs})
        self.store = kpt.kangxi_store.KangxiStore(db, readonly=True)
        for p in (patch.object(kpt, "ANNOTATIONS", self.annotations),
                  patch.object(kpt.paths, "OCR_CACHE_DIR", self.cache),
                  patch.object(kpt, "_page_sha", return_value="scan-sha"),
                  patch.object(kpt, "ocr_submit_markdown", side_effect=AssertionError("must not submit OCR"))):
            p.start()
            self.addCleanup(p.stop)

    def write_ocr(self, markdown, sha="scan-sha"):
        (self.cache / "0371.json").write_text(json.dumps({"sha256": sha, "markdown": markdown}))

    def test_page371_recovers_entire_remainder_before_new_headword(self):
        expected = [self.paragraphs[0].removeprefix("【廣韻】"), *self.paragraphs[1:]]
        self.write_ocr("\n\n".join(expected).replace("𠀤", "𡋣").replace("𡭟", "尖") +
                       "\n\n死\n\n說文古文恆字\n\n註詳心部六畫")
        cont, info = kpt.continuation_from_prev(371, self.store)
        self.assertEqual(cont, expected)
        self.assertEqual(info, {"prev_page": 370, "host_page": 370, "head": "些",
                                "paragraphs": 5, "skipped": None})
        self.assertEqual(len(kpt._norm("".join(cont))), 97)
        bands, _ = kpt._draft_bands(
            [{"char": "𠄨", "codepoint": ord("𠄨"), "ord": 0}], {}, cont, info["head"])
        self.assertEqual(bands, [[p] for p in expected] + [["#𠄨"]])

    def test_missing_stale_or_conflicting_ocr_is_reported_as_uncertain(self):
        for markdown, sha in [(None, "scan-sha"), ("".join(self.paragraphs), "old-sha"),
                              ("說文古文恆字註詳心部六畫" + "".join(self.paragraphs), "scan-sha")]:
            with self.subTest(markdown=markdown, sha=sha):
                if markdown is not None:
                    self.write_ocr(markdown, sha)
                cont, info = kpt.continuation_from_prev(371, self.store)
                self.assertEqual(cont, [])
                self.assertIn("跨页续文待核", info["skipped"])
                self.assertIn("正文仅 2 字", info["skipped"])
                self.assertNotIn("大幅校订", info["skipped"])

    def test_head_only_keeps_opening_book_bracket(self):
        self.prev.write_text("@370\n\n#些\n")
        self.write_ocr("\n\n".join(self.paragraphs))
        cont, info = kpt.continuation_from_prev(371, self.store)
        self.assertIsNone(info["skipped"])
        self.assertEqual(cont, self.paragraphs)

    def test_split_book_title_keeps_closing_bracket(self):
        self.prev.write_text("@370\n\n#些\n【廣\n")
        self.write_ocr("韻】" + self.paragraphs[0].removeprefix("【廣韻】") + "".join(self.paragraphs[1:]))
        cont, info = kpt.continuation_from_prev(371, self.store)
        self.assertIsNone(info["skipped"])
        self.assertEqual(cont[0], self.paragraphs[0].removeprefix("【廣"))

    def test_remainder_at_paragraph_boundary_keeps_opening_bracket(self):
        self.write_ocr("\n\n".join(self.paragraphs))
        with patch.object(kpt, "entry_detail", return_value={"text_paragraphs": ["【廣韻】", *self.paragraphs]}):
            cont, info = kpt.continuation_from_prev(371, self.store)
        self.assertIsNone(info["skipped"])
        self.assertEqual(cont, self.paragraphs)

    def test_book_opener_already_on_previous_page_is_not_duplicated(self):
        self.prev.write_text("@370\n\n#些\n【\n")
        self.write_ocr("\n\n".join(self.paragraphs))
        cont, info = kpt.continuation_from_prev(371, self.store)
        self.assertIsNone(info["skipped"])
        self.assertEqual(cont, [self.paragraphs[0][1:], *self.paragraphs[1:]])
