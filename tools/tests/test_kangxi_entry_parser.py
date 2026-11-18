"""来源卡片回归：真实 HTML 摘录、错选/误删边界及旧缓存的生成链路。"""
import html
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / p) for p in ("crawl", "dataset")]
import kangxi_entry_parser as parser
import kangxi_page_tool as kpt
from kangxi_store import KangxiStore

FIXTURES = json.loads((Path(__file__).parent / "fixtures/kangxi-entry-cards.json").read_text())


def parsed(head, **selection):
    return parser.select_entry(parser.parse_detail(FIXTURES[head]["html"], head), **selection)


def source(query, og, cards):
    parts = [f'<meta property="og:description" content="{html.escape(query + ":" + og, quote=True)}">',
             f'字頭：<font color=blue>{query}</font>']
    for head, page, body in cards:
        parts.append(f'''<img src=../kxzt/0000s/{page:04d}-01-00001-{ord(head):X}.svg>
<font48>{head}</font48>部首：一<br>
<a>武英殿本</a>：{page}頁，第1字
<p><font20><font color=000000>{body}
<P align='right'>《論壇交流》</p>''')
    return "\n".join(parts)


class SourceCardsTest(unittest.TestCase):
    def test_pu_definition_and_guwen_belong_to_their_own_cards(self):
        entry = parsed("仆", page=402)
        self.assertEqual(kpt._norm("".join(entry["text_paragraphs"])),
                         "唐韻集韻韻會芳遇切正韻芳故切𠀤音赴偃也僵也唐書房杜傳贊興仆植僵又集韻普木切音攴義同又集韻韻會正韻𠀤敷救切否去聲頓也")
        self.assertIsNone(entry["guwen"])
        other = parser.select_entry(entry, head="僕", page=514)
        self.assertEqual(other["guwen"], "䑑")
        self.assertIn("給事者", "".join(other["text_paragraphs"]))
        self.assertEqual(entry["parser_version"], parser.PARSER_VERSION)

    def test_inline_attachment_and_its_guwen_and_editorial_are_separate(self):
        for head, page, length, own_guwen, other in [
            ("仅", 402, 25, None, "僅"), ("万", 316, 51, None, "萬"),
            ("丰", 334, 72, "𫵮", "豐"), ("乱", 356, 6, None, "亂"),
        ]:
            with self.subTest(head=head):
                entry = parsed(head, page=page)
                self.assertEqual(len(kpt._norm("".join(entry["text_paragraphs"]))), length)
                self.assertEqual(entry["guwen"], own_guwen)
                self.assertIn(other, [p.get("head") for p in entry["attached_segments"]])
                self.assertNotIn("考證", "".join(entry["text_paragraphs"]))
        self.assertTrue(any(p["kind"] == "editorial" for p in parsed("丰")["attached_segments"]))

    def test_same_codepoint_requires_source_page_and_splits_duplicate_subsection(self):
        unresolved = parsed("𠂳")
        self.assertEqual(unresolved["selection_status"], "unresolved")
        for page, text in [(350, "集韻總古作𠂳註詳糸部十一畫"), (4396, "集韻總古作𠂳註詳十一畫")]:
            self.assertEqual(kpt._norm("".join(parsed("𠂳", page=page)["text_paragraphs"])), text)
        entry = parsed("𠂳", svg="0000s/0350-05-00106-200B3.svg")
        self.assertEqual(entry["wuying_edition"]["page"], 350)
        mismatch = parser.select_entry(entry, page=4396, svg=entry["source_svg"])
        self.assertEqual(mismatch["selection_status"], "unresolved")
        self.assertNotIn("source_svg", mismatch)
        self.assertEqual(mismatch["text_paragraphs"], FIXTURES["𠂳"]["legacy"]["text_paragraphs"])

    def test_editorial_relocation_and_website_notes_are_not_rewritten(self):
        cloud = parsed("云", page=366)
        text = "".join(cloud["text_paragraphs"])
        self.assertIn("伊誰云憎", text)
        self.assertLess(text.index("秦文公"), text.index("陸佃"))  # 本任务不擅自还原引文移位
        self.assertNotIn("謹將此十七字", text)
        self.assertEqual(parsed("𠅬")["text_paragraphs"], FIXTURES["𠅬"]["legacy"]["text_paragraphs"])
        self.assertIn("仲尼曰", "".join(parsed("于")["text_paragraphs"]))

    def test_unmapped_html_supplement_keeps_original_and_reports_uncertainty(self):
        entry = parsed("刂", page=628)
        self.assertEqual(entry["selection_status"], "unresolved")
        self.assertEqual(entry["text_paragraphs"], FIXTURES["刂"]["legacy"]["text_paragraphs"])
        self.assertNotIn("飛火", "".join(entry["text_paragraphs"]))

    def test_repeated_og_copy_can_resolve_to_one_complete_card(self):
        entry = parsed("却")
        self.assertEqual(entry["selection_status"], "selected")
        self.assertEqual(entry["text_paragraphs"], ["《唐韻》俗卻字。"])

    def test_ordinary_parentheses_and_unproven_attachment_are_preserved(self):
        own = "正文有（乙）二字。"
        unproven = "（乙）另有未證的說法。"
        other = "另一詞條正文不相同。"
        raw = source("甲", own + unproven + other,
                     [("甲", 10, own + "<p>" + unproven), ("乙", 20, other)])
        entry = parser.parse_detail(raw, "甲")
        self.assertEqual("".join(entry["text_paragraphs"]), own + unproven)
        self.assertEqual(entry["attached_segments"], [])

    def test_matching_inline_text_is_not_deleted_without_subsection_boundary(self):
        own = "正文引另一詞條正文不相同。"
        other = "另一詞條正文不相同。"
        raw = source("甲", own + other, [("甲", 10, own), ("乙", 20, other)])
        self.assertEqual("".join(parser.parse_detail(raw, "甲")["text_paragraphs"]), own)

    def test_unlabelled_paragraph_matching_a_different_head_is_not_enough(self):
        own, quote = "本條正文。", "另一詞條正文不相同。"
        raw = source("甲", own + quote + quote,
                     [("甲", 10, own + "<p>" + quote), ("乙", 20, quote)])
        entry = parser.parse_detail(raw, "甲")
        self.assertEqual("".join(entry["text_paragraphs"]), own + quote)
        self.assertEqual(entry["attached_segments"], [])

    def test_entities_and_apostrophes_preserve_text_and_book_frames(self):
        og = "【書】can't&amp;字。"
        raw = source("甲", html.unescape(og), [("甲", 10, '<span class="rcornertext">書</span>can&#39;t&amp;字。')])
        entry = parser.parse_detail(raw, "甲")
        self.assertEqual(entry["text_paragraphs"], ["【書】can't&字。"])

    def test_leading_parenthesis_survives_a_card_slice(self):
        own, other = "（甲）本條正文。", "另一詞條正文。"
        raw = source("甲", own + other, [("甲", 10, own), ("乙", 20, other)])
        self.assertEqual(parser.parse_detail(raw, "甲")["text_paragraphs"], [own])


class CachedSourceIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "crawl.db"
        self.store = KangxiStore(self.db)

    def test_existing_legacy_cache_is_used_without_network_or_database_writes(self):
        f = FIXTURES["仆"]
        self.store.save_entry("仆", f["legacy"], raw_html=f["html"])
        before = self.db.read_bytes()
        read = KangxiStore(self.db, readonly=True)
        with patch.object(kpt, "run_fetch", side_effect=AssertionError("no network")):
            entry = kpt.entry_detail("仆", read, page=402)
        self.assertIsNone(entry["guwen"])
        self.assertEqual(len(kpt._norm("".join(entry["text_paragraphs"]))), 57)
        entry["cards"][0]["text_paragraphs"].append("不能污染缓存")
        self.assertNotIn("不能污染缓存", repr(kpt.entry_detail("仆", read, page=402)))
        self.assertEqual(self.db.read_bytes(), before)

    def test_legacy_without_html_is_preserved(self):
        original = {"head": "甲", "text_paragraphs": ["既有人工文本。"]}
        self.store.save_entry("甲", original)
        self.assertEqual(kpt.entry_detail("甲", self.store, page=10), original)

    def test_new_draft_uses_page_card_and_has_no_foreign_tail(self):
        head = "𠂳"
        f = FIXTURES[head]
        self.store.save_entry(head, f["legacy"], raw_html=f["html"])
        self.store.save_page_chars(350, [{"page": 350, "ord": 0, "page_seq": 5,
            "entry_no": "00106", "k_code": None, "codepoint": ord(head), "char": head,
            "svg": "0000s/0350-05-00106-200B3.svg"}])
        with patch.object(kpt, "_ocr_cache_read", return_value=None):
            draft, _ = kpt.build_draft_gj(350, self.store, fold=False)
        self.assertEqual(kpt._norm(draft.partition("#𠂳")[2]), "集韻總古作𠂳註詳糸部十一畫")

    def test_continuation_selects_host_page_not_current_or_first_card(self):
        original = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥天地玄黃宇宙洪荒。"
        other = "另一頁不同正文，不可混入。"
        raw = source("甲", other + original, [("甲", 20, other), ("甲", 10, original)])
        self.store.save_entry("甲", parser._legacy_detail(raw, "甲"), raw_html=raw)
        annotations = Path(self.tmp.name) / "annotations"
        annotations.mkdir()
        (annotations / "0010.gj").write_text("@10\n#甲\n" + original[:24] + "\n")
        with patch.object(kpt, "ANNOTATIONS", annotations):
            continuation, info = kpt.continuation_from_prev(11, self.store)
        self.assertEqual(info["host_page"], 10)
        self.assertEqual("".join(continuation), original[24:])


if __name__ == "__main__":
    unittest.main()
