"""页尾短余文的局部容错与末列复核；不依赖网络、真实库或扫描图。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))
import kangxi_page_tool as k


ANCHOR = "十年忠爲令德非其人猶不可况不令乎又姓又集韻"


class TailReviewTest(unittest.TestCase):
    def review(self, source, observed, column=None, anchor=ANCHOR):
        return k._review_tail_cut(anchor + source, anchor + observed, len(anchor), column)

    def assert_pending(self, result, reason):
        end, note = result
        self.assertEqual(end, len(ANCHOR))
        self.assertIn("页尾待核", note)
        self.assertIn(reason, note)

    def test_preserves_original_glyph_when_column_confirms_variant(self):
        for column in (ANCHOR + "郎", ANCHOR + "郞"):
            with self.subTest(column=column):
                end, note = self.review("郞丁切正韻", "郎", column)
                self.assertEqual(end, len(ANCHOR) + 1)
                self.assertIn("保留库文尾字「郞」", note)

    def test_two_character_tail_can_recover_one_substitution(self):
        end, note = self.review("㸦北史文苑", "乖北", ANCHOR + "乖北")
        self.assertEqual(end, len(ANCHOR) + 2)
        self.assertIn("复核通过", note)

    def test_no_extra_ocr_text_needs_no_review(self):
        self.assertEqual(self.review("郞丁切", ""), (len(ANCHOR), ""))

    def test_missing_conflicting_and_nonterminal_column_evidence(self):
        for column, reason in ((None, "无有效末列"), (ANCHOR, "不一致"),
                               (ANCHOR + "郎水印", "不一致"),
                               ("不同的列郎", "无法唯一定位")):
            with self.subTest(column=column):
                self.assert_pending(self.review("郞丁切", "郎", column), reason)

    def test_multiple_boundaries_and_insertions_are_not_guessed(self):
        self.assert_pending(self.review("甲乙丙", "乙", ANCHOR + "乙"), "多个裁点")
        self.assert_pending(self.review("甲丙丁", "乙甲", ANCHOR + "乙甲"), "插入或删除")

    def test_large_mismatch_new_head_and_exhausted_source(self):
        for source, observed, reason in (("甲乙丙", "天地", "超过 1 字"),
                                        ("#郞", "郎", "新字头"),
                                        ("", "增", "库文已结束"),
                                        ("甲乙丙丁戊己", "天地玄黃宇", "超过 4 字")):
            with self.subTest(source=source):
                self.assert_pending(self.review(source, observed, ANCHOR + observed), reason)

    def test_short_or_repeated_anchor_cannot_locate_tail(self):
        end, note = self.review("郞丁切", "郎", "又集韻郎", anchor="又集韻")
        self.assertEqual(end, 3)
        self.assertIn("锚点不足", note)
        self.assert_pending(self.review("郞丁切" + ANCHOR, "郎", ANCHOR + "郎"), "定位不唯一")
        self.assert_pending(self.review("郞丁切", "郎", ANCHOR + ANCHOR + "郎"), "无法唯一定位")
        # 重叠出现也不是唯一锚点，不能用 str.count 的非重叠计数放行。
        _, note = self.review("甲郞丁切", "郎", "甲" * 31 + "郎", anchor="甲" * 30)
        self.assertIn("定位不唯一", note)

    def test_distant_singleton_match_is_not_replaced_by_adjacent_character(self):
        source = "天地玄黃宇宙洪荒日月山"
        self.assert_pending(self.review(source, "山", ANCHOR + "山"), "更后面的库文")


class TailReviewIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((Path(__file__).parent / "fixtures/kangxi-0412-tail.json").read_text())

    def cache(self, markdown):
        return [{"index": i + 1, "x1": 8 - i, "x2": 9 - i,
                 "markdown": markdown if i == 7 else None} for i in range(8)]

    def test_real_page_with_partial_column_cache_extends_only_one_source_character(self):
        d = self.data
        with (
            mock.patch.object(k, "_ocr_cache_read", return_value=d["ocr"]),
            mock.patch.object(k, "_page_sha", return_value="current-image"),
            mock.patch.object(k, "_column_cache_read", return_value=self.cache(d["column"])) as columns,
            mock.patch.object(k, "ocr_submit_markdown", side_effect=AssertionError("must not submit OCR")),
        ):
            end, total, note = k.ocr_page_cut(412, d["text"], object(), full_page=True)
            bands = [[line] for line in d["text"].splitlines()]
            trimmed, trim_note = k._trim_bands_to_page(412, bands, object())
        self.assertEqual((end, total), (369, 569))
        self.assertEqual(trimmed[-1][-1][-6:], "又【集韻】郞")
        self.assertIn("复核通过", note)
        self.assertIn("复核通过", trim_note)
        columns.assert_called_with(412, "current-image")
        self.assertNotIn("子集中康熙", k._norm("".join(k._ocr_groups(d["ocr"]))))

    def test_missing_or_stale_column_cache_keeps_cut_and_persists_review_comment(self):
        d = self.data
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "columns").mkdir()
            cache_file = root / "columns/0412.json"
            for state in ("missing", "stale", "wrong-model", "failed-last-column"):
                with self.subTest(state=state):
                    if state != "missing":
                        cache_file.write_text(json.dumps({
                            "sha256": "old" if state == "stale" else "current",
                            "model": "other" if state == "wrong-model" else "paddle",
                            "columns": self.cache(None if state == "failed-last-column" else d["column"]),
                        }))
                    with (
                        mock.patch.object(k.paths, "OCR_CACHE_DIR", root),
                        mock.patch.object(k, "_ocr_cache_read", return_value=d["ocr"]),
                        mock.patch.object(k, "_page_sha", return_value="current"),
                        mock.patch.object(k, "page_heads", return_value=[]),
                        mock.patch.object(k, "ocr_regroup_bands", side_effect=lambda p, b: (b, "略")),
                        mock.patch.object(k, "ocr_submit_markdown", side_effect=AssertionError("must not submit OCR")),
                    ):
                        draft, counts = k.build_draft_gj(412, object(), d["text"].splitlines())
                    self.assertIn("// 页尾待核：", draft)
                    self.assertNotIn("【集韻】郞", draft)
                    self.assertTrue(any("归页尚未确认" in n for n in counts["ocr_notes"]))
                    self.assertFalse(any("留给下页自动续入" in n for n in counts["ocr_notes"]))

    def test_complete_candidate_does_not_hide_unmatched_ocr_warning(self):
        with (
            mock.patch.object(k, "_ocr_cache_read", return_value=ANCHOR + "增"),
            mock.patch.object(k, "_page_sha", return_value="sha"),
            mock.patch.object(k, "_column_cache_read", return_value=self.cache(ANCHOR + "增")),
        ):
            bands, note = k._trim_bands_to_page(376, [[ANCHOR]], object())
        self.assertEqual(bands[0], [ANCHOR])
        self.assertTrue(bands[-1][0].startswith("// 页尾待核："))
        self.assertIn("页尾待核", note)
        self.assertNotIn("未溢出页界", note)

    def test_skeleton_replay_keeps_review_note_out_of_body(self):
        columns = self.cache(ANCHOR + "增")
        for column in columns[:-1]:
            column["markdown"] = ""
        with (
            mock.patch.object(k.kangxi_store, "KangxiStore"),
            mock.patch.object(k, "_ocr_cache_read", return_value=ANCHOR + "增"),
            mock.patch.object(k, "_page_sha", return_value="sha"),
            mock.patch.object(k, "_column_cache_read", return_value=columns),
            mock.patch.object(k, "page_gj", return_value=f"@376\n\n{ANCHOR}\n"),
            mock.patch.object(k, "page_heads", return_value=[]),
            mock.patch.object(k, "continuation_from_prev", return_value=([ANCHOR], {})),
            mock.patch.object(k, "_compare_bands", return_value={}),
        ):
            replay = k.cmd_ocr_skeleton_replay(376)
        self.assertEqual(replay["blueprint"]["norm_len"], len(ANCHOR))
        self.assertEqual(replay["result"]["bands"], [[ANCHOR]])
        self.assertIn("页尾待核", replay["blueprint"]["source"])


if __name__ == "__main__":
    unittest.main()
