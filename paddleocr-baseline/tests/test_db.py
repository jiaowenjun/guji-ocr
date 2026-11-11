"""db.py：去重插入、claim/release 抢占、状态变迁与到期调度。"""

from paddleocr_baseline.db import Database


def make_database(tmp_path) -> Database:
    database = Database(tmp_path / "ocr.sqlite3")
    database.init()
    return database


def insert(database: Database, sha: str) -> dict:
    return database.insert_image(
        sha256=sha,
        mime_type="image/png",
        width=4,
        height=3,
        storage_key=f"uploads/ocr-images/img_{sha}.png",
    )


def test_insert_dedups_by_sha256(tmp_path):
    database = make_database(tmp_path)
    first = insert(database, "a" * 64)
    again = insert(database, "a" * 64)
    assert first["id"] == again["id"]
    assert first["status"] == "pending"
    assert first["provider_job_id"] is None


def test_claim_then_release_allows_reclaim(tmp_path):
    database = make_database(tmp_path)
    row = insert(database, "b" * 64)

    assert database.claim_image_submission(row["id"], claim_ttl_ms=60_000) is True
    # claim 未过期时不能重复认领
    assert database.claim_image_submission(row["id"], claim_ttl_ms=60_000) is False
    assert database.get_image(row["id"])["status"] == "running"

    database.release_image_submission_claim(row["id"])
    assert database.get_image(row["id"])["status"] == "pending"
    assert database.claim_image_submission(row["id"], claim_ttl_ms=60_000) is True


def test_mark_submitted_resets_attempts(tmp_path):
    database = make_database(tmp_path)
    row = insert(database, "c" * 64)
    database.record_sync_retry(row["id"], attempts=3, backoff_s=60, detail="boom")
    database.mark_image_submitted(
        row["id"], provider_job_id="job-1", provider_state="running", status="running", next_poll_ms=1000
    )
    updated = database.get_image(row["id"])
    assert updated["provider_job_id"] == "job-1"
    assert updated["sync_attempts"] == 0
    assert updated["next_sync_at"] is not None


def test_finish_succeeded_and_failed_are_terminal(tmp_path):
    database = make_database(tmp_path)
    ok = insert(database, "d" * 64)
    database.finish_succeeded(
        ok["id"], text_preview="预览", result_markdown="# md", result_json='[{"a": 1}]'
    )
    finished = database.get_image(ok["id"])
    assert finished["status"] == "succeeded"
    assert finished["provider_state"] == "done"
    assert finished["finished_at"] is not None
    assert finished["next_sync_at"] is None

    bad = insert(database, "e" * 64)
    database.finish_failed(bad["id"], public_message="OCR failed", detail="boom")
    failed = database.get_image(bad["id"])
    assert failed["status"] == "failed"
    assert failed["error_message"] == "OCR failed"
    assert failed["last_sync_error"] == "boom"


def test_due_ids_respect_next_sync_at(tmp_path):
    database = make_database(tmp_path)
    due = insert(database, "1" * 64)
    later = insert(database, "2" * 64)
    database.record_sync_retry(later["id"], attempts=1, backoff_s=300, detail="slow down")

    ids = database.due_image_ids(limit=10)
    assert ids == [due["id"]]

    # 把 due 也 claim 到 60s 后，整体延迟受 MIN 约束（later 退避 300s，due 60s）
    database.claim_image_submission(due["id"], claim_ttl_ms=60_000)
    delay = database.next_sync_delay_ms()
    assert delay is not None and 0 < delay <= 60_000


def test_next_sync_delay_none_when_no_active(tmp_path):
    database = make_database(tmp_path)
    row = insert(database, "3" * 64)
    assert database.next_sync_delay_ms() == 0
    database.finish_failed(row["id"], public_message="x", detail=None)
    assert database.next_sync_delay_ms() is None
