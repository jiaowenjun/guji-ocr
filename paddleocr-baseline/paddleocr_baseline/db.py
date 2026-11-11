"""SQLite 持久层：images 表与状态变迁。

对齐 weimo-ocr backend 的 ``src/db.rs`` schema 与 ``src/persistence/images`` 的
状态变迁函数。时间戳为 ``YYYY-MM-DDTHH:MM:SS.mmmZ``（UTC）字符串，可按字典序比较。

方法均为同步阻塞调用（SQLite 本地操作很快）；async 调用方用 ``asyncio.to_thread`` 包装。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

ACTIVE_STATUSES = ("pending", "running")
TERMINAL_STATUSES = ("succeeded", "failed")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT NOT NULL,
    image_mime_type TEXT NOT NULL,
    image_width INTEGER NOT NULL,
    image_height INTEGER NOT NULL,
    image_storage_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    provider_state TEXT NOT NULL DEFAULT 'pending',
    provider_job_id TEXT,
    text_preview TEXT,
    result_markdown TEXT,
    result_json TEXT,
    error_message TEXT,
    last_sync_error TEXT,
    sync_attempts INTEGER NOT NULL DEFAULT 0,
    next_sync_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_images_sha256 ON images (sha256);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _iso_plus_ms(now_iso: str, ms: int) -> str:
    moment = datetime.strptime(now_iso, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    return (moment + timedelta(milliseconds=ms)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _delay_ms(target_iso: str, now_iso: str) -> int:
    target = datetime.strptime(target_iso, "%Y-%m-%dT%H:%M:%S.%fZ")
    now = datetime.strptime(now_iso, "%Y-%m-%dT%H:%M:%S.%fZ")
    return max(0, int((target - now).total_seconds() * 1000))


class Database:
    """每次操作建立短连接并在结束时提交、关闭；WAL 在初始化时开启（持久化于库文件）。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(_SCHEMA)

    # ---- 查询 -----------------------------------------------------------

    def find_by_sha256(self, sha256: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM images WHERE sha256 = ?", (sha256,)
            ).fetchone()
        return dict(row) if row else None

    def get_image(self, image_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
        return dict(row) if row else None

    def due_image_ids(self, limit: int) -> list[int]:
        now = utc_now_iso()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id FROM images
                WHERE status IN ('pending', 'running')
                  AND (next_sync_at IS NULL OR next_sync_at <= ?)
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        return [row["id"] for row in rows]

    def next_sync_delay_ms(self) -> int | None:
        """没有任何 active 图片时返回 None；有 NULL next_sync_at（立即到期）返回 0。"""
        with self._connection() as connection:
            due_now = connection.execute(
                """
                SELECT 1 FROM images
                WHERE status IN ('pending', 'running') AND next_sync_at IS NULL
                LIMIT 1
                """
            ).fetchone()
            if due_now is not None:
                return 0
            row = connection.execute(
                "SELECT MIN(next_sync_at) AS earliest FROM images WHERE status IN ('pending', 'running')"
            ).fetchone()
        earliest = row["earliest"] if row else None
        if earliest is None:
            return None
        return _delay_ms(earliest, utc_now_iso())

    # ---- 写入 -----------------------------------------------------------

    def insert_image(
        self,
        *,
        sha256: str,
        mime_type: str,
        width: int,
        height: int,
        storage_key: str,
    ) -> dict[str, Any]:
        """按 sha256 去重：唯一索引冲突时返回已存在的记录。"""
        now = utc_now_iso()
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO images (
                        sha256, image_mime_type, image_width, image_height,
                        image_storage_key, status, provider_state,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'pending', 'pending', ?, ?)
                    """,
                    (sha256, mime_type, width, height, storage_key, now, now),
                )
                image_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            existing = self.find_by_sha256(sha256)
            assert existing is not None, "unique index violation without existing row"
            return existing
        row = self.get_image(image_id)
        assert row is not None
        return row

    def claim_image_submission(self, image_id: int, claim_ttl_ms: int) -> bool:
        """pending→running 抢占；只有还没提交过且到期的记录能被认领。"""
        now = utc_now_iso()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE images
                SET status = 'running', next_sync_at = ?, updated_at = ?
                WHERE id = ?
                  AND provider_job_id IS NULL
                  AND status IN ('pending', 'running')
                  AND (next_sync_at IS NULL OR next_sync_at <= ?)
                """,
                (_iso_plus_ms(now, claim_ttl_ms), now, image_id, now),
            )
            claimed = cursor.rowcount > 0
        return claimed

    def release_image_submission_claim(self, image_id: int) -> None:
        now = utc_now_iso()
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE images
                SET status = 'pending', next_sync_at = NULL, updated_at = ?
                WHERE id = ? AND provider_job_id IS NULL AND status = 'running'
                """,
                (now, image_id),
            )

    def mark_image_submitted(
        self,
        image_id: int,
        *,
        provider_job_id: str,
        provider_state: str,
        status: str,
        next_poll_ms: int,
    ) -> None:
        now = utc_now_iso()
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE images
                SET provider_job_id = ?, provider_state = ?, status = ?,
                    next_sync_at = ?, sync_attempts = 0, updated_at = ?
                WHERE id = ?
                """,
                (provider_job_id, provider_state, status, _iso_plus_ms(now, next_poll_ms), now, image_id),
            )

    def mark_image_running(
        self, image_id: int, *, provider_state: str, status: str, next_poll_ms: int
    ) -> None:
        now = utc_now_iso()
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE images
                SET provider_state = ?, status = ?, next_sync_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (provider_state, status, _iso_plus_ms(now, next_poll_ms), now, image_id),
            )

    def record_sync_retry(self, image_id: int, *, attempts: int, backoff_s: int, detail: str) -> None:
        now = utc_now_iso()
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE images
                SET sync_attempts = ?, last_sync_error = ?, next_sync_at = ?, updated_at = ?
                WHERE id = ? AND status IN ('pending', 'running')
                """,
                (attempts, detail, _iso_plus_ms(now, backoff_s * 1000), now, image_id),
            )

    def finish_succeeded(
        self,
        image_id: int,
        *,
        text_preview: str | None,
        result_markdown: str | None,
        result_json: str | None,
    ) -> None:
        now = utc_now_iso()
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE images
                SET status = 'succeeded', provider_state = 'done',
                    text_preview = ?, result_markdown = ?, result_json = ?,
                    next_sync_at = NULL, finished_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (text_preview, result_markdown, result_json, now, now, image_id),
            )

    def finish_failed(self, image_id: int, *, public_message: str, detail: str | None) -> None:
        now = utc_now_iso()
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE images
                SET status = 'failed', error_message = ?, last_sync_error = ?,
                    next_sync_at = NULL, finished_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (public_message, detail, now, now, image_id),
            )
