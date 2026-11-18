"""跨页短缺口检测与绑定扫描指纹的人审页界回归。"""
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))
import kangxi_page_tool as k


class PageBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(
            (Path(__file__).parent / "fixtures/kangxi-0420-boundary.json").read_text()
        )
        self.cand = k._norm(self.data["text"])
        self.ocr = k._norm(self.data["ocr"])
        self.next_ocr = k._norm(self.data["next_ocr"])
        self.end = len(self.ocr)

    def test_two_page_gap_is_pending_when_both_current_ocr_runs_omit_it(self):
        end, note = k._review_next_page_gap(
            self.cand, self.ocr, self.end, self.next_ocr, k._norm(self.data["column"])
        )
        self.assertEqual(end, self.end)
        self.assertIn("页尾待核", note)
        self.assertIn("短缺口「前」", note)
        self.assertIn("同样漏掉", note)
        self.assertIn("不能仅按缺口字数补入", note)

    def test_column_confirmation_can_extend_only_the_located_gap(self):
        end, note = k._review_next_page_gap(
            self.cand, self.ocr, self.end, self.next_ocr,
            k._norm(self.data["column"] + "前"),
        )
        self.assertEqual(end, self.end + 1)
        self.assertIn("跨页首尾复核通过", note)
        self.assertEqual(self.cand[self.end:self.end + 1], "前")

    def test_next_opening_allows_one_substitution_but_rejects_ambiguity_and_heads(self):
        variant = self.next_ocr.replace("隂", "陰", 1)
        end, note = k._review_next_page_gap(
            self.cand, self.ocr, self.end, variant, k._norm(self.data["column"] + "前")
        )
        self.assertEqual(end, self.end + 1)
        self.assertIn("复核通过", note)

        anchor, _ = k._tail_context(self.cand, self.ocr, self.end)
        repeated = anchor + "甲" * 30
        self.assertEqual(
            k._review_next_page_gap(repeated, anchor, len(anchor), "甲" * 24, None),
            (len(anchor), ""),
        )
        crossing = self.cand[:self.end] + "#前" + self.cand[self.end + 1:]
        self.assertEqual(
            k._review_next_page_gap(crossing, self.ocr, self.end, self.next_ocr, None),
            (self.end, ""),
        )

    def test_verified_boundary_requires_sha_unique_tail_and_adjacent_head(self):
        end, note = k._verified_boundary_cut(
            self.cand, self.end, self.data["scan_sha256"], self.data["review"]
        )
        self.assertEqual(end, self.end + 1)
        self.assertIn("已核页界", note)

        for sha, review in (
            ("stale", self.data["review"]),
            (self.data["scan_sha256"], {**self.data["review"], "head_after": "天地玄黃宇宙洪荒"}),
            (self.data["scan_sha256"], {**self.data["review"], "max_adjust": 0}),
        ):
            with self.subTest(sha=sha, review=review):
                self.assertEqual(k._verified_boundary_cut(self.cand, self.end, sha, review),
                                 (self.end, ""))

    def test_real_420_contract_keeps_open_bracket_with_verified_first_character(self):
        cache = [{"index": i + 1, "x1": 8 - i, "x2": 9 - i,
                  "markdown": self.data["column"] if i == 7 else ""} for i in range(8)]

        def page_ocr(page, _store):
            return self.data["ocr"] if page == 420 else self.data["next_ocr"]

        with (
            mock.patch.object(k, "_ocr_cache_read", side_effect=page_ocr),
            mock.patch.object(k, "_page_sha", return_value=self.data["scan_sha256"]),
            mock.patch.object(k, "_column_cache_read", return_value=cache),
            mock.patch.object(k, "_page_boundary_reviews", return_value={"420": self.data["review"]}),
        ):
            bands, note = k._trim_bands_to_page(420, [[self.data["text"]]], object())
        self.assertTrue(bands[-1][-1].endswith("又【前"))
        self.assertIn("已核页界", note)
        self.assertNotIn("页尾待核", note)

    def test_unverified_420_gap_persists_review_comment_without_guessing(self):
        cache = [{"index": i + 1, "x1": 8 - i, "x2": 9 - i,
                  "markdown": self.data["column"] if i == 7 else ""} for i in range(8)]

        def page_ocr(page, _store):
            return self.data["ocr"] if page == 420 else self.data["next_ocr"]

        with (
            mock.patch.object(k, "_ocr_cache_read", side_effect=page_ocr),
            mock.patch.object(k, "_page_sha", return_value=self.data["scan_sha256"]),
            mock.patch.object(k, "_column_cache_read", return_value=cache),
            mock.patch.object(k, "_page_boundary_reviews", return_value={}),
        ):
            bands, note = k._trim_bands_to_page(420, [[self.data["text"]]], object())
        self.assertTrue(bands[-1][0].startswith("// 页尾待核："))
        self.assertIn("短缺口「前」", bands[-1][0])
        self.assertTrue(bands[-2][-1].endswith("又"))
        self.assertIn("归页尚未确认", note)
        self.assertNotIn("留给下页自动续入", note)


if __name__ == "__main__":
    unittest.main()
