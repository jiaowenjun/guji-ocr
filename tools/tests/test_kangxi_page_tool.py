#!/usr/bin/env python3
"""kangxi_page_tool 纯函数单测（stdlib unittest，零外部依赖、零数据依赖）。

只测抽出的纯函数（A/B/C 级封装）；I/O 编排（cmd_add/_prefetch_pipeline 等）
由 tools/eval/ 的回放脚本覆盖（两级测试策略）。用例来源：各函数 docstring
与实现在档的踩坑记录（@313 周期振荡、@334 折点坍缩、@339 双空行…）。

运行：python3 -m unittest discover -s tools/tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "crawl"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))

import kangxi_page_tool as kpt  # noqa: E402


def distinct_chars(n: int, start: int = 0x4E00) -> str:
    """n 个互不相同的汉字（对齐用例构造）。"""
    return "".join(chr(start + i) for i in range(n))


# ---- A1 对齐判信 ----


class TestAlignCut(unittest.TestCase):
    def test_clean_prefix_cut(self):
        """候选前缀 = 页面全文 → 裁点在 OCR 全长处。"""
        page_txt = distinct_chars(40)
        end, why = kpt._align_cut(page_txt + distinct_chars(40, 0x5000), page_txt)
        self.assertEqual(end, 40)
        self.assertEqual(why, "")

    def test_too_short_rejected(self):
        """裁点 <20 字拒绝（页面过小无连续性证据）。"""
        ocr = distinct_chars(10)
        end, why = kpt._align_cut(ocr + "甲乙", ocr)
        self.assertIsNone(end)
        self.assertIn("过短", why)

    def test_low_coverage_rejected(self):
        """匹配零星（无大面积匹配块）→ 拒绝。"""
        cand = distinct_chars(60)
        ocr = distinct_chars(60, 0x6000) + cand[:3]  # 只 3 字真匹配
        end, why = kpt._align_cut(cand, ocr)
        self.assertIsNone(end)

    def test_zero_matching_blocks_rejected(self):
        """两串非空但零公共块（@358：残缺 OCR 单字与续文无交集）→ 拒绝而非崩溃。"""
        end, why = kpt._align_cut(distinct_chars(40), distinct_chars(40, 0x9000))
        self.assertIsNone(end)
        self.assertIn("零匹配", why)

    def test_full_page_span_uses_ocr_side(self):
        """full_page=True 判信按 OCR 侧：候选远大于页面仍可裁（@334 场景）。"""
        ocr = distinct_chars(50)
        cand = ocr + distinct_chars(200, 0x7000)  # 候选 250 字，页面 50 字
        end, _ = kpt._align_cut(cand, ocr, full_page=True)
        self.assertEqual(end, 50)

    def test_tail_retraction(self):
        """末段伪匹配回缩：真匹配断流后的孤字（山）不虚增末界（@331 场景）。"""
        page_real = distinct_chars(60)  # 真页 60 字（不含「山」）
        cand = page_real + distinct_chars(10, 0x8000) + "山"  # 溢出段尾的孤字
        ocr = page_real + "山"  # OCR 尾把溢出某字读成「山」
        end, why = kpt._align_cut(cand, ocr, full_page=True)
        self.assertEqual(end, 60)
        self.assertIn("回缩", why)


# ---- A2 宿主标记解析 ----


class TestFindHostMarks(unittest.TestCase):
    def test_explicit_variants_skipped(self):
        """古文标签和变体分行，变体不是宿主。"""
        self.assertEqual(kpt.find_host_marks("#(三)#中\n古文\n#𠁧𠁩"), [("中", 6)])

    def test_standalone_variant_lines_skipped(self):
        """独占式 @313：#丁 + 古文 + 变体 #行。"""
        self.assertEqual(kpt.find_host_marks("#丁\n古文\n#𠆤"), [("丁", 2)])

    def test_bare_ligature_takes_last_char(self):
        """糖连写 #丶宔 ≡ #丶#宔：宿主取串末字。"""
        self.assertEqual(kpt.find_host_marks("#丶宔"), [("宔", 3)])

    def test_separate_guwen_marker(self):
        """主字头后的标点及跨行古文不改变宿主 丹。"""
        self.assertEqual(kpt.find_host_marks("#(三)丹，\n古文：\n#𠁿㣋"), [("丹", 5)])


# ---- A3 续入锚定 ----


class TestLocateTail(unittest.TestCase):
    def test_exact_substring(self):
        entry = distinct_chars(40)
        end, why = kpt.locate_tail(entry, entry[10:28])
        self.assertEqual(end, 28)
        self.assertEqual(why, "")

    def test_tolerates_single_edit(self):
        """站点文本少一字：容差对齐仍定位（@334 场景）。改动须在锚定前缀
        （首 8 字）之后，否则锚定整体失败。"""
        entry = distinct_chars(40)
        tail = list(entry[10:30])
        tail[15] = "改"  # 个别校订差异（锚定前缀 tail[:15] 不受影响）
        end, _ = kpt.locate_tail(entry, "".join(tail))
        self.assertEqual(end, 30)

    def test_anchor_failure(self):
        entry = distinct_chars(40, 0x4E00)
        tail = distinct_chars(20, 0x9000)  # 完全不同
        end, why = kpt.locate_tail(entry, tail)
        self.assertIsNone(end)
        self.assertEqual(why, "anchor")

    def test_low_coverage(self):
        """后半段全改：锚定靠前 8 字成功，覆盖率不足拒绝。"""
        entry = distinct_chars(40)
        tail = list(entry[10:30])
        for i in range(10, 20):
            tail[i] = chr(0xA000 + i)
        end, why = kpt.locate_tail(entry, "".join(tail))
        self.assertIsNone(end)
        self.assertTrue(why.startswith("coverage"), why)

    def test_fully_included(self):
        """尾部已覆盖库文全部 → 前页完整收录（@339→340 指引路径）。"""
        entry = distinct_chars(40)
        end, why = kpt.locate_tail(entry, entry[10:])
        self.assertIsNone(end)
        self.assertEqual(why, "fully")


# ---- A4 古文前缀剥离 ----


class TestStripGuwenPrefix(unittest.TestCase):
    def test_inline_dunhao(self):
        self.assertEqual(kpt.strip_guwen_prefix("古文#𠁿、#㣋\n殘段"), "殘段")

    def test_separate_colon_label(self):
        self.assertEqual(kpt.strip_guwen_prefix("，\n古文：\n#𠁿㣋\n殘段"), "殘段")

    def test_newline_separated_definition(self):
        """换行结束大字作用域，后续释义不被吞。"""
        self.assertEqual(kpt.strip_guwen_prefix("古文\n#𠁿、㣋\n殘段"), "殘段")

    def test_standalone_variant_line(self):
        self.assertEqual(kpt.strip_guwen_prefix("古文\n#𠆤\n釋文"), "釋文")

    def test_vertical_split_guwen(self):
        """竖排把「古文」拆两行（古\n文\n#𠀚、#𠙐）。"""
        self.assertEqual(kpt.strip_guwen_prefix("古\n文\n#𠀚、#𠙐\n釋文"), "釋文")

    def test_no_prefix_untouched(self):
        self.assertEqual(kpt.strip_guwen_prefix("釋文起句"), "釋文起句")


# ---- A5 折行纯逻辑 ----


class TestFlattenBand(unittest.TestCase):
    def test_merges_lines_strips_leading_trailing_ascii_ws(self):
        """行首尾半角空白剥、行中保留。"""
        self.assertEqual(kpt._flatten_band(["A B", "\tC\t"]), "A BC")

    def test_keeps_fullwidth_space(self):
        """全角空格是内容字符（空字格 ≡*），@312 老样式实测。"""
        self.assertEqual(kpt._flatten_band(["入聲。　"]), "入聲。　")

    def test_comment_band_keeps_newlines(self):
        self.assertEqual(kpt._flatten_band(["#□", "// 註"]), "#□\n// 註")


class TestStructuralSpans(unittest.TestCase):
    def test_hash_and_comment_lines_protected(self):
        spans = kpt._structural_spans([["#丹古文#𠁿"], ["正文", "// 註釋"]])
        # band1 全行 6 字 # 起始 → (0, 6)；band2 起点 6+1=7（\u0001 分隔），
        # "// 註釋" 行内偏移 3（正文 2 字 + 换行）→ (10, 15)
        self.assertEqual(spans, [(0, 6), (10, 15)])


class TestMapGroupOffsets(unittest.TestCase):
    def test_maps_inside_blocks_and_drops_gaps(self):
        Block = type("B", (), {})  # 轻量 matching_block 替身
        b0, b1 = Block(), Block()
        b0.a, b0.b, b0.size = 0, 0, 10
        b1.a, b1.b, b1.size = 30, 20, 5
        # 偏移 5 在块0 → 5；15 在间隙 → 丢弃；22 在块1 → 30+(22-20)=32
        self.assertEqual(kpt._map_group_offsets([b0, b1], [5, 15, 22]), [5, 32])


class TestApplyFolds(unittest.TestCase):
    def test_open_bracket_moves_before(self):
        """两种开书名号都随下文起行，句号留在上文。"""
        for opening, closing in [("【", "】"), ("《", "》")]:
            with self.subTest(opening=opening):
                title = f"{opening}說文{closing}丙丁"
                # 归一化序：甲0 乙1 說2 文3 丙4 丁5；折点 2 位于书名首字。
                pieces = kpt._apply_folds("甲乙。" + title, [2], [])
                self.assertEqual(pieces, ["甲乙。", title])

    def test_close_bracket_moves_after(self):
        """闭书名号随上文收尾。"""
        for opening, closing in [("【", "】"), ("《", "》")]:
            with self.subTest(opening=opening):
                prefix = f"甲乙{opening}說文{closing}。"
                pieces = kpt._apply_folds(prefix + "丙丁", [4], [])
                self.assertEqual(pieces, [prefix, "丙丁"])

    def test_page380_open_book_bracket_follows_title(self):
        """@380 亰条：忽略标点的折点不能把《正韻》拆开。"""
        prefix = "字《字彙》不載，韻書無考。"
        title = "《正韻》十一先收原邍，亦闕亰。"
        pieces = kpt._apply_folds(prefix + title, [9], [])
        self.assertEqual(pieces, [prefix, title])

    def test_duplicate_cutpoints_collapsed(self):
        """@334 坍缩去重：重复折点不得吞掉后续折点。"""
        full = "甲乙丙丁戊己"
        pieces = kpt._apply_folds(full, [2, 2, 4], [])
        self.assertEqual(pieces, ["甲乙", "丙丁", "戊己"])

    def test_cut_inside_structural_dropped(self):
        """结构行内部折点整点丢弃（不拆字头行，@339 场景）。"""
        full = "#丁古文#𠆤續尾"  # 行首 # 才是结构行
        spans = kpt._structural_spans([[full]])
        # 归一化序：#0 丁1 古2 文3 …；折点 3（文）在字头行内部 → 丢弃
        self.assertIsNone(kpt._apply_folds(full, [3], spans))

    def test_cut_at_structural_start_allowed(self):
        """结构行起点放行：字头行与前行分开不破坏头本身（@313 振荡根因）。"""
        full = "#丁古文#𠆤續尾"
        spans = kpt._structural_spans([[full]])
        pieces = kpt._apply_folds(full, [0], spans)
        self.assertEqual(pieces, ["", full])

    def test_no_effective_cut_returns_none(self):
        self.assertIsNone(kpt._apply_folds("甲乙丙", [5], []))


class TestRebuildBands(unittest.TestCase):
    def test_empty_band_dropped_and_newlines_stripped(self):
        """切点贴带界时空带/前导换行被清理（@339 双空行实测）。
        输入是折行 pieces（\n 连接后按 \u0001 分带）。"""
        self.assertEqual(kpt._rebuild_bands(["甲乙\n\u0001\n丙"]), [["甲乙"], ["丙"]])


# ---- A6 band 重组 ----


class TestRegroupBody(unittest.TestCase):
    def test_splits_on_major_change(self):
        groups = kpt._regroup_body(["甲", "乙", "丙"], {0: 0, 1: 0, 2: 1})
        self.assertEqual(groups, [["甲", "乙"], ["丙"]])

    def test_section_header_standalone(self):
        """部题行独立成带（@312「## 子集上### 一部」振荡根因）。"""
        groups = kpt._regroup_body(["甲", "#*子集上", "乙"], {0: 0, 1: 0})
        self.assertEqual(groups, [["甲"], ["#*子集上"], ["乙"]])

    def test_comment_attaches_to_preceding_band(self):
        """// 注释附着前正文行所在带（字符流不丢）。"""
        groups = kpt._regroup_body(["甲", "// 註", "乙"], {0: 0, 1: 1})
        self.assertEqual(groups, [["甲", "// 註"], ["乙"]])


# ---- A7 band 裁点 ----


class TestLocateBandCut(unittest.TestCase):
    def test_counts_norm_chars_only(self):
        """句读不计序号、注释行跳过；char_idx 是含标点的原文偏移。"""
        bands = [["甲，乙"], ["// 註"], ["丙。"]]
        self.assertEqual(kpt._locate_band_cut(bands, 2), (2, 0, 0))  # 丙（// 带跳过）
        self.assertEqual(kpt._locate_band_cut(bands, 1), (0, 0, 2))  # 乙（，占 idx 1）

    def test_past_end_returns_none(self):
        self.assertIsNone(kpt._locate_band_cut([["甲"]], 5))


class TestCutBandsAt(unittest.TestCase):
    def test_cut_on_head_line_keeps_whole_line(self):
        bands = [["前帶"], ["#丁", "釋文"]]
        self.assertEqual(kpt._cut_bands_at(bands, (1, 0, 0)), [["前帶"], ["#丁", "釋文"]])

    def test_prior_lines_in_band_kept(self):
        """裁在大行第 2 行行首时前行属本页（@338 实测踩坑）。"""
        bands = [["前帶"], ["B1", "B2", "B3"]]
        self.assertEqual(kpt._cut_bands_at(bands, (1, 1, 0)), [["前帶"], ["B1"]])


# ---- B1 草稿组装 ----


def char_item(ord_: int, char: str | None, codepoint: int | None, k_code: str = "", svg="s.svg"):
    return {"ord": ord_, "char": char, "codepoint": codepoint, "k_code": k_code, "svg": svg}


class TestDraftBands(unittest.TestCase):
    def test_guwen_exact_merge(self):
        """K 码簇与 guwen 数量精确匹配 → 归并字头行（@331/@334 先例）。"""
        chars = [
            char_item(1, "丹", 20025),
            char_item(2, None, None, k_code="K1", svg="a.svg"),
            char_item(3, None, None, k_code="K2", svg="b.svg"),
        ]
        details = {20025: {"guwen": "𠁿、㣋", "text_paragraphs": ["段一"]}}
        bands, counts = kpt._draft_bands(chars, details)
        self.assertEqual(bands[0], ["#丹", "古文：", "#𠁿㣋"])
        self.assertEqual(counts["guwen_merged"], 1)
        self.assertEqual(counts["chars"], 1)
        self.assertEqual(counts["with_text"], 1)
        self.assertIn(["段一"], bands)

    def test_guwen_mismatch_placeholder(self):
        """数量不符 → #□ 占位 + 注释。"""
        chars = [
            char_item(1, "丹", 20025),
            char_item(2, None, None, k_code="K1"),
            char_item(3, None, None, k_code="K2"),
        ]
        details = {20025: {"guwen": "𠁿", "text_paragraphs": []}}
        bands, counts = kpt._draft_bands(chars, details)
        self.assertEqual(bands[0], ["#丹"])
        self.assertEqual(counts["unencoded"], 2)
        self.assertEqual([b[0] for b in bands if b[0] == "#□"], ["#□", "#□"])

    def test_companion_comment_only(self):
        """2 段名伴随字形只留注释行。"""
        chars = [char_item(1, "丹", 20025), char_item(2, None, None, k_code="", svg="c.svg")]
        bands, counts = kpt._draft_bands(chars, {20025: None})
        self.assertEqual(counts["companions"], 1)
        self.assertTrue(any("伴随字形" in b[0] for b in bands))

    def test_orphan_at_page_head(self):
        chars = [char_item(1, None, None, k_code="K9", svg="o.svg"), char_item(2, "丹", 20025)]
        bands, counts = kpt._draft_bands(chars, {20025: None})
        self.assertEqual(counts["unencoded"], 1)
        self.assertTrue(any("本页无前邻主字头" in b[0] for b in bands))

    def test_skip_head_and_continuation_first(self):
        chars = [char_item(1, "丹", 20025)]
        bands, counts = kpt._draft_bands(
            chars, {20025: {"guwen": "", "text_paragraphs": []}},
            continuation=["續文段"], skip_head="丹",
        )
        self.assertEqual(bands[0], ["續文段"])
        self.assertEqual(counts["skipped_dup"], 1)
        self.assertEqual(counts["chars"], 0)


# ---- B2/B3 小工具 ----


class TestIndexFromManifest(unittest.TestCase):
    def test_field_mapping_and_defaults(self):
        m = {"images_dir": "/x", "pages": [
            {"page": 312, "image": "0312.jpg", "status": "draft",
             "annotations": {"gj": "0312.gj"}, "width": 1130, "height": 1679},
            {"page": 313, "image": "0313.jpg"},  # 无 annotations/status → 缺省
        ]}
        out = kpt._index_from_manifest(m)
        self.assertEqual(out["source"], "kangxi-gold")
        self.assertEqual(out["pages"][0]["gj"], "0312.gj")
        self.assertEqual(out["pages"][1]["gj"], "0313.gj")
        self.assertEqual(out["pages"][1]["status"], "first")


class TestFetchSummary(unittest.TestCase):
    def test_stats_json(self):
        s = kpt._fetch_summary('{"pages_total": 100, "entries_total": 5}', "頁數據")
        self.assertEqual(s, "頁數據：联网补抓完成（库内 100 页 / 5 条字头）")

    def test_plain_line(self):
        self.assertEqual(kpt._fetch_summary("普通輸出", "X"), "X：普通輸出")

    def test_empty(self):
        self.assertEqual(kpt._fetch_summary("", "X"), "X：完成")


# ---- C .gj 解析 ----


class TestParseGjBands(unittest.TestCase):
    def test_head_and_bands(self):
        head, bands = kpt.parse_gj_bands("// 註\n@312\n\n#一\n\n甲\n乙\n\n丙")
        self.assertEqual(head, ["// 註", "@312"])
        self.assertEqual(bands, [["#一"], ["甲", "乙"], ["丙"]])

    def test_no_trailing_newline(self):
        _, bands = kpt.parse_gj_bands("@312\n\n甲")
        self.assertEqual(bands, [["甲"]])


class TestLineScopedType(unittest.TestCase):
    def test_flatten_keeps_type_boundaries(self):
        self.assertEqual(kpt._flatten_band(["#甲，", "古文：", "#乙丙", "正文", "續文"]), "#甲，\n古文：\n#乙丙\n正文續文")

    def test_midline_large_scope_protected(self):
        band = ["正文#甲乙", "釋文"]
        full = kpt._flatten_band(band)
        self.assertEqual(full, "正文#甲乙\n釋文")
        spans = kpt._structural_spans([band])
        self.assertEqual(spans, [(2, 5)])
        self.assertIsNone(kpt._apply_folds(full, [4], spans))

    def test_repeated_fold_preserves_large_and_small(self):
        bands = [["#甲", "古文：", "#乙丙", "釋義正文"]]
        full = kpt._flatten_band(bands[0])
        spans = kpt._structural_spans(bands)
        # Force a cut in the definition; the three earlier type boundaries remain explicit.
        cut = len(kpt._norm("#甲\n古文：\n#乙丙\n釋義"))
        pieces = kpt._apply_folds(full, [cut], spans)
        result = kpt._rebuild_bands(pieces)
        self.assertEqual(result, [["#甲", "古文：", "#乙丙", "釋義", "正文"]])
        self.assertEqual(kpt._flatten_band(result[0]), full)

    def test_titles_excluded_from_hosts(self):
        source = "#康熙字典\n\n#*子集中\n\n#**一部\n\n#一:\n正文"
        self.assertEqual(kpt.find_host_marks(source), [("一", source.index("一:") + 1)])


if __name__ == "__main__":
    unittest.main()
