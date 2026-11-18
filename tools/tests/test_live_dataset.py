"""Live sources: manifest, .gj, OCR status and glyph identity have no sync prerequisite."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/dataset"))
sys.path.insert(0, str(ROOT / "kangxi-gold/scripts"))
import kangxi_page_tool as kpt
from annotation_source import derive_annotations
from eval_cer import evaluate


class LiveDatasetTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "annotations").mkdir()
        self.manifest = self.root / "manifest.json"
        self.data = {"images_dir": "images", "pages": [{"page": 367, "image": "0367.jpg",
                     "annotations": {"gj": "0367.gj"}, "status": "draft"}]}
        self.manifest.write_text(json.dumps(self.data))
        shutil.copy(ROOT / "kangxi-gold/dataset-config.json", self.root)
        self.gj = self.root / "annotations/0367.gj"
        self.gj.write_text("@367\n\n#互\n天地\n")

    def test_index_observes_manifest_and_config_updates_without_writes(self):
        with patch.object(kpt, "MANIFEST", self.manifest):
            self.assertEqual(kpt.cmd_dataset_index()["pages"][0]["status"], "draft")
            self.data["pages"][0]["status"] = "first"
            self.manifest.write_text(json.dumps(self.data))
            config = self.root / "dataset-config.json"
            c = json.loads(config.read_text()); c["label"] = "updated"
            config.write_text(json.dumps(c))
            before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
            response = kpt.cmd_dataset_index()
            self.assertEqual(response["pages"][0]["status"], "first")
            self.assertEqual(response["config"]["label"], "updated")
            self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_evaluation_uses_current_gj_even_with_missing_or_stale_exports(self):
        rows = evaluate(self.root / "annotations", self.root / "ocr")
        self.assertEqual([(r["page"], r["n_ref"], r["status"]) for r in rows], [(367, 3, "missing")])
        (self.root / "annotations/0367.txt").write_text("old")
        self.gj.write_text("@367\n\n#互\n天地玄黃\n")
        self.assertEqual(evaluate(self.root / "annotations", self.root / "ocr")[0]["n_ref"], 5)
        self.assertFalse((self.root / "annotations/0367.json").exists())

    def test_missing_source_and_wrong_marker_fail_instead_of_omitting_pages(self):
        self.gj.unlink()
        with self.assertRaises(subprocess.CalledProcessError):
            derive_annotations(self.root)
        self.gj.write_text("@368\n\n#互\n")
        with self.assertRaises(subprocess.CalledProcessError):
            derive_annotations(self.root)

    def test_explicit_export_never_rewrites_source_or_manifest(self):
        before = self.gj.read_bytes(), self.manifest.read_bytes()
        subprocess.run(["node", str(ROOT / "kangxi-gold/scripts/build_annotations.ts"), "--root", str(self.root)],
                       check=True, capture_output=True, text=True)
        self.assertEqual(before, (self.gj.read_bytes(), self.manifest.read_bytes()))
        row = derive_annotations(self.root)[367]
        self.assertEqual(json.loads((self.root / "annotations/0367.json").read_text()), row["ir"])
        self.assertEqual((self.root / "annotations/0367.txt").read_text(), row["text"])

    def test_ocr_queries_do_not_submit_or_write_and_partial_run_keeps_steps(self):
        db = self.root / "crawl.sqlite3"
        store = kpt.kangxi_store.KangxiStore(db)
        store.save_reading(367, b"collected")
        with patch.object(kpt.kangxi_store, "KangxiStore", return_value=store), \
             patch.object(kpt, "_page_sha", return_value="sha"), \
             patch.object(kpt.paths, "OCR_CACHE_DIR", self.root / "cache"), \
             patch.object(kpt, "ocr_submit_markdown", side_effect=AssertionError("query submitted OCR")):
            self.assertIsNone(kpt.cmd_ocr_view(367)["markdown"])
            response = kpt.cmd_prefetch_status(367)
            self.assertIsNone(response["markdown"])
            self.assertFalse(response["steps"]["ocr"]["ok"])
            self.assertFalse((self.root / "cache").exists())
        steps = [{"step": "ocr", "ok": False, "detail": "offline"}]
        with patch.object(kpt, "_prefetch_pipeline", return_value=steps):
            response = kpt.cmd_prefetch_run(367)
            self.assertTrue(response["ok"])
            self.assertFalse(response["completed"])
            self.assertEqual(response["steps"], steps)

    def test_glyph_override_precedence_fallback_and_source_updates(self):
        db = self.root / "crawl.sqlite3"
        store = kpt.kangxi_store.KangxiStore(db)
        store.save_page_chars(367, [{"page": 367, "ord": 0, "svg": "0000s/raw.svg", "char": "互", "codepoint": ord("互"),
                                     "page_seq": 1, "entry_no": None, "k_code": None}])
        manual = self.root / "unencoded/kangxi-unencoded"
        (manual / "svg").mkdir(parents=True)
        raw = self.root / "raw"
        (raw / "0000s").mkdir(parents=True)
        (raw / "0000s/raw.svg").write_text("<svg/>")
        (manual / "svg/report.svg").write_text("<svg/>")
        (manual / "svg/patch.svg").write_text("<svg/>")
        query = lambda: kpt.cmd_crawl_glyphs([ord("互"), ord("甲")], db_path=db)["glyphs"]
        with patch.object(kpt.paths, "UNENCODED_DIR", self.root / "unencoded"), \
             patch.object(kpt.paths, "RAW_KANGXI_SVG", raw):
            self.assertEqual(query(), {"互": "/dataset/head-svg/0000s/raw.svg"})
            (manual / "report.json").write_text(json.dumps({"items": [{"base_char": "互", "svg": "report.svg"}]}))
            self.assertEqual(query()["互"], "/dataset/unencoded-svg/report.svg")
            (manual / "font-patches.jsonl").write_text(json.dumps({"svg": "patch.svg", "results": [{"cp": "U+4E92"}]}))
            self.assertEqual(query()["互"], "/dataset/unencoded-svg/patch.svg")
            (manual / "font-patches.jsonl").unlink()
            self.assertEqual(query()["互"], "/dataset/unencoded-svg/report.svg")
            (manual / "svg/report.svg").unlink()
            self.assertEqual(query()["互"], "/dataset/head-svg/0000s/raw.svg")
            (raw / "0000s/raw.svg").unlink()
            self.assertEqual(query(), {})
