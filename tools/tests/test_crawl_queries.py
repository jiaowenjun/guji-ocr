"""本地爬取查询契约：真实临时 SQLite，零网络，不依赖清单或导出快照。"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))
import kangxi_page_tool as kpt


class CrawlQueriesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "crawl.sqlite3"
        self.store = kpt.kangxi_store.KangxiStore(self.db)

    def test_heads_preserve_page_order_and_unencoded_glyphs(self):
        self.store.save_reading(367, b"<html>collected</html>")
        rows = [
            {"page": 367, "ord": 1, "page_seq": 1, "entry_no": None,
             "k_code": "K123", "codepoint": None, "char": None, "svg": "0000s/0367-01-K123.svg"},
            {"page": 367, "ord": 0, "page_seq": 1, "entry_no": "00182",
             "k_code": None, "codepoint": ord("互"), "char": "互", "svg": "0000s/0367-01-00182-4E92.svg"},
        ]
        self.store.save_page_chars(367, rows)
        with patch.object(kpt, "load_manifest", side_effect=AssertionError("must not read manifest")), \
             patch.object(kpt, "run_fetch", side_effect=AssertionError("must not crawl")):
            result = kpt.cmd_crawl_heads(367, db_path=self.db)
        self.assertEqual(result["heads"], list(reversed(rows)))

    def test_empty_collected_page_is_distinct_from_missing_reading(self):
        self.store.save_reading(332, b"<html>continuation</html>")
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO pages(page, scan_file) VALUES(333, '333.jpg')")
        self.assertEqual(kpt.cmd_crawl_heads(332, db_path=self.db)["heads"], [])
        self.assertIsNone(kpt.cmd_crawl_heads(333, db_path=self.db)["heads"])
        self.assertIsNone(kpt.cmd_crawl_heads(334, db_path=self.db)["heads"])

    def test_entry_uses_unicode_codepoint_and_returns_current_record(self):
        char = "𠀀"
        self.assertIsNone(kpt.cmd_crawl_entry(ord(char), db_path=self.db)["entry"])
        self.store.save_entry(char, {"head": char, "text_paragraphs": ["初文"]}, raw_html="raw secret")
        self.assertEqual(kpt.cmd_crawl_entry(ord(char), db_path=self.db)["entry"],
                         {"head": char, "text_paragraphs": ["初文"]})
        self.store.save_entry(char, {"head": char, "text_paragraphs": ["补录"]})
        self.assertEqual(kpt.cmd_crawl_entry(ord(char), db_path=self.db)["entry"]["text_paragraphs"], ["补录"])

    def test_queries_do_not_initialize_or_change_existing_database(self):
        self.store.save_reading(367, b"<html>collected</html>")
        with sqlite3.connect(self.db) as conn:
            conn.execute("PRAGMA user_version = 99")
        before = self.db.read_bytes()
        kpt.cmd_crawl_heads(367, db_path=self.db)
        kpt.cmd_crawl_entry(ord("互"), db_path=self.db)
        self.assertEqual(self.db.read_bytes(), before)
        readonly = kpt.kangxi_store.KangxiStore(self.db, readonly=True)
        with self.assertRaises(sqlite3.OperationalError):
            readonly.save_reading(368, b"must not write")

    def test_missing_database_is_an_error_and_is_not_created(self):
        missing = Path(self.tmp.name) / "absent" / "crawl.sqlite3"
        for query in (lambda: kpt.cmd_crawl_heads(367, db_path=missing),
                      lambda: kpt.cmd_crawl_entry(ord("互"), db_path=missing)):
            with self.assertRaises(sqlite3.OperationalError):
                query()
        self.assertFalse(missing.parent.exists())

    def test_corrupt_entry_is_an_error_not_a_missing_record(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO entries(codepoint, sword, record_json) VALUES(?, ?, ?)",
                         (ord("互"), "互", "invalid JSON"))
        with self.assertRaises(json.JSONDecodeError):
            kpt.cmd_crawl_entry(ord("互"), db_path=self.db)

    def test_invalid_page_and_codepoint_are_rejected(self):
        for page in (0, -1, 7739):
            with self.assertRaises(ValueError):
                kpt.cmd_crawl_heads(page, db_path=self.db)
        for cp in (0, -1, 0xD800, 0xDFFF, 0x110000):
            with self.assertRaises(ValueError):
                kpt.cmd_crawl_entry(cp, db_path=self.db)


if __name__ == "__main__":
    unittest.main()
