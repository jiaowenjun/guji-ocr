"""续文与新词条统一尾裁的回归测试；真实文本夹具，I/O 隔离到临时目录。"""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
import kangxi_page_tool as kpt
import kangxi_svg_cache
from eval_continuation_replay import generated_continuation


class TestDraftContinuation(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(
            (Path(__file__).parent / "fixtures/kangxi-0406-continuation.json").read_text()
        )

    @contextmanager
    def environment(self, page=406):
        """执行真正的续入、组装、尾裁、折行和 add 写稿；替换采集与图像依赖。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ann = root / "annotations"
            ann.mkdir()
            (ann / f"{page - 1:04d}.gj").write_text(self.fixture["previous_gj"])
            scan = root / f"{page:04d}.jpg"
            scan.touch()
            store = mock.Mock()
            store.page_missing.return_value = False
            store.coded_chars_missing_entries.return_value = []
            store.get_page.return_value = {
                "scan_file": str(scan), "scan_sha256": "fixture", "scan_bytes": 0,
                "scan_width": 1130, "scan_height": 1674,
            }

            def detail(head, *_args, **_kwargs):
                return self.fixture["entries"].get(chr(head) if isinstance(head, int) else head)

            with (
                mock.patch.object(kpt, "REPO", root),
                mock.patch.object(kpt, "ANNOTATIONS", ann),
                mock.patch.object(kpt, "MANIFEST", root / "manifest.json"),
                mock.patch.object(kpt, "load_manifest", return_value={"images_dir": str(root), "pages": []}),
                mock.patch.object(kpt.kangxi_store, "KangxiStore", return_value=store),
                mock.patch.object(kpt, "page_heads", return_value=self.fixture["heads"]),
                mock.patch.object(kpt, "entry_detail", side_effect=detail),
                mock.patch.object(kpt, "_ocr_cache_read", return_value=self.fixture["ocr"]),
                mock.patch.object(kpt, "page_ocr"),
                mock.patch.object(kpt, "ocr_regroup_bands", side_effect=lambda p, b: (b, "未运行图像分列")),
                mock.patch.object(kpt, "_compare_bands", return_value={}),
                mock.patch.object(kpt, "_log_ts"),
                mock.patch.object(kpt, "prefetch_next_page"),
                mock.patch.object(kangxi_svg_cache, "pick_svg_dir", return_value=root),
                mock.patch.object(kangxi_svg_cache, "cache_page_svgs", return_value={}),
            ):
                yield store, ann

    def body(self, gj):
        _, bands = kpt.parse_gj_bands(gj)
        return kpt._norm("".join(line for band in bands for line in band))

    def test_add_preserves_missing_tail_before_next_head(self):
        """旧独立裁剪把「辨。」丢掉；实际 add 路径应完整保留且不改前页。"""
        with self.environment() as (_, ann):
            result = kpt.cmd_add(406)
            draft = (ann / "0406.gj").read_text()
            self.assertEqual((ann / "0405.gj").read_text(), self.fixture["previous_gj"])
        self.assertTrue(result["ok"])
        self.assertIn("甚矣。不可不辨。", draft)
        self.assertEqual(self.body(draft), self.body(self.fixture["expected_gj"]))

    def test_replay_and_evaluation_use_complete_continuation(self):
        with self.environment() as (store, _):
            replay = kpt.cmd_pipeline_replay(406)
            cont, info = kpt.continuation_from_prev(406, store)
            leading, _ = generated_continuation(406, store, cont, info["head"])
        self.assertEqual(leading, cont)
        for stage in replay["draft"]["stages"]:
            with self.subTest(stage=stage["name"]):
                body = kpt._norm("".join(line for band in stage["bands"] for line in band))
                self.assertEqual(body, self.body(self.fixture["expected_gj"]))

    def test_last_entry_still_trims_overflow_and_resumes_on_next_page(self):
        overflow = "".join(chr(0x6000 + i) for i in range(40))
        self.fixture["entries"]["㐰"]["text_paragraphs"].append(overflow)
        with self.environment() as (store, ann):
            kpt.cmd_add(406)
            draft = (ann / "0406.gj").read_text()
            following, info = kpt.continuation_from_prev(407, store)
        self.assertIn("甚矣。不可不辨。", draft)
        self.assertNotIn(overflow, draft)
        self.assertEqual(info["head"], "㐰")
        self.assertEqual(following, [overflow])

    def test_pure_continuation_trims_and_resumes_without_new_heads(self):
        previous = "".join(chr(0x5000 + i) for i in range(40))
        current = "".join(chr(0x6000 + i) for i in range(40))
        following = "".join(chr(0x7000 + i) for i in range(40))
        self.fixture.update(
            previous_gj=f"@331\n\n#中\n{previous}\n",
            heads=[], entries={"中": {"text_paragraphs": [previous, current, following]}},
            ocr=current,
        )
        with self.environment(page=332) as (store, ann):
            kpt.cmd_add(332)
            draft = (ann / "0332.gj").read_text()
            rest, info = kpt.continuation_from_prev(333, store)
        self.assertEqual(draft, f"@332\n\n{current}\n")
        self.assertEqual(info["host_page"], 331)
        self.assertEqual(rest, [following])

    def test_unavailable_or_unrelated_ocr_keeps_full_text(self):
        for ocr in (None, "".join(chr(0x8000 + i) for i in range(40))):
            with self.subTest(ocr=ocr):
                self.fixture["ocr"] = ocr
                with self.environment() as (_, ann):
                    result = kpt.cmd_add(406)
                    draft = (ann / "0406.gj").read_text()
                self.assertEqual(self.body(draft), self.body(self.fixture["expected_gj"]))
                self.assertTrue(any("尾裁未执行" in note for note in result["summaries"]))


if __name__ == "__main__":
    unittest.main()
