#!/usr/bin/env python3
"""康熙字典爬取数据的 SQLite 存储层：原始数据入库、字段级去重、页→字头索引。

设计（依据 docs/research/2026-11-12-kangxizidian-网站结构调研.md）：
- 文本类原始数据与解析结果存库：阅读页 HTML（含字头索引来源）、详情页
  原始 HTML、结构化记录 JSON；整页 JPG 等大二进制留在文件系统，库内只存
  绝对路径 + sha256 + 尺寸（避免数 GB BLOB，全书约 4GB 图）；
- 去重：pages 以页码、entries 以 Unicode 码位为主键；page_missing() 支持
  「缺什么补什么」的字段级增量抓取（如已有图缺 HTML 只补 HTML），
  二次运行对已有数据零网络请求；
- 采纳（adopt）：磁盘上已有的旧缓存（NNNN.html / NNNN.jpg / {码位}.json）
  可直接登记入库，不重新联网；
- WAL + 每操作短连接，可被演示服务器多线程共用；
- fetch_log 记录每次动作（fetch/adopt/skip-db/update），可审计重复抓取。

被 scripts/fetch_kangxi_page.py、fetch_kangxi_entry.py、kangxi_crawl_demo.py 共用。
仅依赖标准库。
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "datasets" / "kangxi-crawl.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
  page                INTEGER PRIMARY KEY,   -- 站点页码 1-7738
  reading_html        TEXT,                  -- 阅读页原始 HTML（BOM 已剥）
  reading_sha256      TEXT,
  reading_fetched_at  TEXT,
  scan_url            TEXT,                  -- 整页原图直链（解析自阅读页或模板）
  scan_file           TEXT,                  -- 原图绝对路径（二进制不入库）
  scan_sha256         TEXT,
  scan_bytes          INTEGER,
  scan_width          INTEGER,
  scan_height         INTEGER,
  scan_fetched_at     TEXT
);
CREATE TABLE IF NOT EXISTS entries (
  codepoint  INTEGER PRIMARY KEY,            -- Unicode 码位整数
  sword      TEXT NOT NULL,                  -- 字头字符
  raw_html   TEXT,                           -- 详情页原始 HTML（采纳旧 JSON 时可能为空）
  html_sha256 TEXT,
  record_json TEXT NOT NULL,                 -- parse_detail 产出的结构化记录
  fetched_at  TEXT,
  source_url  TEXT
);
CREATE TABLE IF NOT EXISTS page_chars (      -- 页→字头索引（缩略图列解析）
  page      INTEGER NOT NULL,
  ord       INTEGER NOT NULL,                -- 列内出现顺序（阅读页自上而下）
  page_seq  INTEGER,                         -- 文件名第 2 段；未编码字与编码字可重复
  entry_no  TEXT,                            -- 全典字头流水号（4 段名第 3 段）
  k_code    TEXT,                            -- 站内 K 编号（…-K####.svg 形态）
  codepoint INTEGER,                         -- 可空：真·未编码字（含 2 段名 …-NN.svg）
  char      TEXT,
  svg       TEXT NOT NULL,                   -- 缩略图文件名（页内唯一）
  PRIMARY KEY (page, svg)
);
CREATE INDEX IF NOT EXISTS idx_page_chars_codepoint ON page_chars(codepoint);
CREATE TABLE IF NOT EXISTS fetch_log (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  at     TEXT NOT NULL,
  kind   TEXT NOT NULL,                      -- page / entry
  key    TEXT NOT NULL,
  action TEXT NOT NULL                       -- fetch / adopt / skip-db / update
);
"""

THUMB_PAIR_RE = re.compile(
    r"sword=&#x([0-9A-Fa-f]*)['\"][^>]*>\s*<img[^>]*?src=['\"]?([^'\"\s>]+\.svg)"
)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_thumb_items(page_html: str) -> list[dict]:
    """解析阅读页缩略图列 → page_chars 行（字段与表一致，含未编码字）。

    依据调研第 3 节及实测补充：缩略图文件名有三种形态——
    4 段 {页}-{序}-{流水号}-{码位}.svg（主字头）、3 段 {页}-{序}-K####.svg、
    2 段 {页}-{序}.svg（后两类为未编码字，链接实体破损 &#x）；
    未编码字与编码字可能共用同一 page_seq，页内唯一键是 svg 文件名。
    """
    items = []
    for ord_, m in enumerate(THUMB_PAIR_RE.finditer(page_html)):
        hexcode, svg = m.group(1), m.group(2).split("/")[-1]
        stem = svg[:-4].split("-") if svg.endswith(".svg") else svg.split("-")
        entry_no = stem[2] if len(stem) >= 3 else None
        k_code = entry_no if entry_no and entry_no.startswith("K") else None
        items.append({
            "page": int(stem[0]),
            "ord": ord_,
            "page_seq": int(stem[1]) if len(stem) >= 2 and stem[1].isdigit() else None,
            "entry_no": None if k_code else entry_no,
            "k_code": k_code,
            "codepoint": int(hexcode, 16) if hexcode else None,
            "char": chr(int(hexcode, 16)) if hexcode else None,
            "svg": svg,
        })
    return items


class KangxiStore:
    def __init__(self, db_path: Path | str = DEFAULT_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)
            c.execute("PRAGMA user_version = 2")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- 审计 ----

    def log(self, kind: str, key, action: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO fetch_log (at, kind, key, action) VALUES (?,?,?,?)",
                (_now(), kind, str(key), action),
            )

    def stats(self) -> dict:
        with self._conn() as c:
            one = lambda sql: c.execute(sql).fetchone()[0]  # noqa: E731
            return {
                "pages_total": one("SELECT COUNT(*) FROM pages"),
                "pages_with_scan": one("SELECT COUNT(*) FROM pages WHERE scan_sha256 IS NOT NULL"),
                "pages_with_reading": one("SELECT COUNT(*) FROM pages WHERE reading_html IS NOT NULL"),
                "entries_total": one("SELECT COUNT(*) FROM entries"),
                "entries_with_raw_html": one("SELECT COUNT(*) FROM entries WHERE raw_html IS NOT NULL"),
                "page_chars_total": one("SELECT COUNT(*) FROM page_chars"),
                "page_chars_unencoded": one("SELECT COUNT(*) FROM page_chars WHERE codepoint IS NULL"),
            }

    # ---- pages ----

    def get_page(self, page: int) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM pages WHERE page=?", (page,)).fetchone()
            return dict(row) if row else None

    def next_missing_page(self, start: int = 1, total: int = 7738) -> int | None:
        """最小的未完成页（缺阅读页 HTML 或原图）；全部完成返回 None。"""
        with self._conn() as c:
            row = c.execute(
                """WITH RECURSIVE seq(x) AS (SELECT ? UNION ALL SELECT x+1 FROM seq WHERE x < ?)
                   SELECT MIN(x) FROM seq WHERE NOT EXISTS (
                     SELECT 1 FROM pages
                     WHERE page=x AND reading_html IS NOT NULL AND scan_sha256 IS NOT NULL)""",
                (start, total),
            ).fetchone()
        return row[0] if row else None

    def coded_chars_missing_entries(self, page: int) -> list[str]:
        """该页有码位、但 entries 表尚无详情的字头（增量抓详情用）。"""
        with self._conn() as c:
            rows = c.execute(
                """SELECT pc.char FROM page_chars pc
                   WHERE pc.page=? AND pc.codepoint IS NOT NULL
                     AND NOT EXISTS (SELECT 1 FROM entries e WHERE e.codepoint=pc.codepoint)
                   ORDER BY pc.ord""",
                (page,),
            ).fetchall()
        return [r[0] for r in rows]

    def page_missing(self, page: int, parts=("scan",)) -> set[str]:
        """返回 page 行缺失的部分 ⊆ {'scan', 'reading'}；行不存在则返回 parts 全集。"""
        row = self.get_page(page)
        if row is None:
            return set(parts)
        missing = set()
        if "scan" in parts and not (row.get("scan_sha256") and row.get("scan_file")):
            missing.add("scan")
        if "reading" in parts and not row.get("reading_html"):
            missing.add("reading")
        return missing

    def save_reading(self, page: int, html_bytes: bytes) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO pages (page, reading_html, reading_sha256, reading_fetched_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(page) DO UPDATE SET
                     reading_html=excluded.reading_html,
                     reading_sha256=excluded.reading_sha256,
                     reading_fetched_at=excluded.reading_fetched_at""",
                (page, html_bytes.decode("utf-8-sig", "replace"), sha256_of(html_bytes), _now()),
            )

    def save_scan(self, page: int, jpg_bytes: bytes, file: Path, url: str | None = None,
                  dims: tuple[int, int] | None = None, action: str = "fetch") -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO pages (page, scan_url, scan_file, scan_sha256,
                                      scan_bytes, scan_width, scan_height, scan_fetched_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(page) DO UPDATE SET
                     scan_url=COALESCE(excluded.scan_url, scan_url),
                     scan_file=excluded.scan_file,
                     scan_sha256=excluded.scan_sha256,
                     scan_bytes=excluded.scan_bytes,
                     scan_width=excluded.scan_width,
                     scan_height=excluded.scan_height,
                     scan_fetched_at=excluded.scan_fetched_at""",
                (page, url, str(file), sha256_of(jpg_bytes), len(jpg_bytes),
                 dims[0] if dims else None, dims[1] if dims else None, _now()),
            )
        self.log("page", page, action)

    def adopt_scan(self, page: int, file: Path, url: str | None = None,
                   dims: tuple[int, int] | None = None) -> bool:
        """把磁盘上已有的有效原图登记入库（不联网）。"""
        data = file.read_bytes()
        self.save_scan(page, data, file, url, dims, action="adopt")
        return True

    # ---- page_chars ----

    def save_page_chars(self, page: int, items: list[dict]) -> int:
        with self._conn() as c:
            c.execute("DELETE FROM page_chars WHERE page=?", (page,))
            c.executemany(
                """INSERT INTO page_chars
                   (page, ord, page_seq, entry_no, k_code, codepoint, char, svg)
                   VALUES (:page,:ord,:page_seq,:entry_no,:k_code,:codepoint,:char,:svg)""",
                items,
            )
        return len(items)

    def get_page_chars(self, page: int) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM page_chars WHERE page=? ORDER BY ord", (page,))]

    # ---- entries ----

    def get_entry(self, codepoint: int) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM entries WHERE codepoint=?", (codepoint,)).fetchone()
            return dict(row) if row else None

    def get_entry_by_char(self, char: str) -> dict | None:
        return self.get_entry(ord(char)) if len(char) == 1 else None

    def save_entry(self, sword: str, record: dict, raw_html: str | None = None,
                   source_url: str | None = None, action: str = "fetch") -> None:
        codepoint = ord(sword)
        record = dict(record)
        record.pop("trace", None)  # 演示轨迹不入库
        with self._conn() as c:
            c.execute(
                """INSERT INTO entries (codepoint, sword, raw_html, html_sha256,
                                        record_json, fetched_at, source_url)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(codepoint) DO UPDATE SET
                     sword=excluded.sword,
                     raw_html=COALESCE(excluded.raw_html, raw_html),
                     html_sha256=COALESCE(excluded.html_sha256, html_sha256),
                     record_json=excluded.record_json,
                     fetched_at=excluded.fetched_at,
                     source_url=COALESCE(excluded.source_url, source_url)""",
                (codepoint, sword, raw_html,
                 sha256_of(raw_html.encode("utf-8")) if raw_html else None,
                 json.dumps(record, ensure_ascii=False), _now(), source_url),
            )
        self.log("entry", f"U+{codepoint:04X}", action)

    def adopt_entry_json(self, path: Path) -> str | None:
        """把磁盘上旧爬取器产出的 {码位}.json 登记入库（不联网）。

        返回采纳的字头；无 record/text 的损坏文件返回 None。
        """
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            sword = record.get("sword")
            if not sword or not record.get("text_paragraphs"):
                return None
            self.save_entry(sword, record, action="adopt")
            return sword
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            return None


if __name__ == "__main__":  # 简易检查：python3 kangxi_store.py [db]
    import sys

    store = KangxiStore(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB)
    print(json.dumps(store.stats(), ensure_ascii=False, indent=2))
