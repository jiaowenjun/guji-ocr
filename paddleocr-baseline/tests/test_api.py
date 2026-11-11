"""API + worker 端到端：上传 → 去重 → worker tick → 结果视图与资产。"""

import asyncio
import json
import sqlite3

from fastapi.testclient import TestClient

from paddleocr_baseline import storage
from paddleocr_baseline.provider import ProviderFetchResult
from paddleocr_baseline.routes import create_app
from paddleocr_baseline.worker import sync_due_images
from tests.conftest import tiny_png

RESULT_MARKDOWN = "https://cdn.test/1.md"
RESULT_JSON_URL = "https://cdn.test/1.json"
ASSET_URL = "https://cdn.test/imgs/figure.png"


def make_client(app_state) -> TestClient:
    return TestClient(create_app(app_state, start_worker=False))


def upload(client: TestClient, data: bytes):
    return client.post("/ocr/images", files={"file": ("sample.png", data, "image/png")})


def test_health(app_state):
    with make_client(app_state) as client:
        assert client.get("/health").json() == {"ok": True, "service": "ocr"}


def test_upload_validates_and_dedups(app_state):
    with make_client(app_state) as client:
        response = upload(client, tiny_png(640, 480))
        assert response.status_code == 201
        body = response.json()
        image_id = body["image_id"]
        assert image_id.startswith("img_") and len(image_id) == 68
        assert body["source_image"]["width"] == 640
        assert body["source_image"]["mime_type"] == "image/png"
        assert body["source_image"]["url"] == f"/ocr/images/{image_id}/source"
        assert body["result"] is None and body["error"] is None
        assert body["result_url"] == f"/ocr/images/{image_id}/result"

        # 同内容去重：仍 201，id 不变，磁盘只有一个文件
        assert upload(client, tiny_png(640, 480)).json()["image_id"] == image_id
        uploads = list((app_state.config.storage_path / "uploads/ocr-images").iterdir())
        assert len(uploads) == 1

        # 非图片 / 空 body / 超限 id
        assert upload(client, b"not an image").status_code == 400
        assert upload(client, b"").status_code == 400
        assert client.get("/ocr/images/img_notahash").status_code == 404
        assert client.get(f"/ocr/images/img_{'z' * 64}").status_code == 404


def test_result_endpoint_202_while_processing(app_state):
    with make_client(app_state) as client:
        image_id = upload(client, tiny_png()).json()["image_id"]
        response = client.get(f"/ocr/images/{image_id}/result")
        assert response.status_code == 202
        body = response.json()
        assert body["image_id"] == image_id
        assert body["result"] is None and body["error"] is None and body["finished_at"] is None


def test_worker_completes_image_end_to_end(app_state):
    app_state.provider.texts[RESULT_MARKDOWN] = "# 古籍标题\n第一行正文"
    app_state.provider.texts[RESULT_JSON_URL] = json.dumps(
        {
            "result": {
                "layoutParsingResults": [
                    {
                        "markdown": {
                            "text": "# 古籍标题",
                            "images": {"imgs/figure.png": ASSET_URL},
                        }
                    }
                ]
            }
        }
    )
    app_state.provider.binaries[ASSET_URL] = b"fake-png-bytes"

    with make_client(app_state) as client:
        image_id = upload(client, tiny_png()).json()["image_id"]

        # 第一次 tick：提交 job
        assert asyncio.run(sync_due_images(app_state)) == 1
        assert app_state.provider.submitted[0].filename.startswith("img_")
        assert client.get(f"/ocr/images/{image_id}/result").status_code == 202

        # 第二次 tick：provider 已 done → 下载并落地结果
        app_state.provider.fetch_result = ProviderFetchResult(
            provider_state="done",
            result_json_url=RESULT_JSON_URL,
            result_markdown_url=RESULT_MARKDOWN,
            error_message=None,
        )
        assert asyncio.run(sync_due_images(app_state)) == 1

        view = client.get(f"/ocr/images/{image_id}").json()
        assert view["result"]["text"] == "古籍标题"
        assert view["result"]["markdown"] == "# 古籍标题\n第一行正文"
        assert view["result"]["assets"] == [
            {"path": "imgs/figure.png", "url": f"/ocr/images/{image_id}/assets/imgs/figure.png"}
        ]

        result = client.get(f"/ocr/images/{image_id}/result")
        assert result.status_code == 200
        assert result.json()["result"]["json"]["result"]["layoutParsingResults"]

        # 原图与缓存资产可回取
        source = client.get(f"/ocr/images/{image_id}/source")
        assert source.status_code == 200 and source.content == tiny_png()
        asset = client.get(f"/ocr/images/{image_id}/assets/imgs/figure.png")
        assert asset.status_code == 200 and asset.content == b"fake-png-bytes"
        assert client.get(f"/ocr/images/{image_id}/assets/../secret").status_code == 404


def test_worker_records_provider_failure(app_state):
    with make_client(app_state) as client:
        image_id = upload(client, tiny_png()).json()["image_id"]
        asyncio.run(sync_due_images(app_state))
        app_state.provider.fetch_result = ProviderFetchResult(
            provider_state="failed", result_json_url=None, result_markdown_url=None,
            error_message="provider exploded",
        )
        asyncio.run(sync_due_images(app_state))

        body = client.get(f"/ocr/images/{image_id}/result").json()
        assert body["error"] == {"message": "provider exploded"}
        assert body["result"] is None


def test_worker_retries_transient_submit_errors(app_state, monkeypatch):
    with make_client(app_state) as client:
        image_id = upload(client, tiny_png()).json()["image_id"]

        from paddleocr_baseline.provider import ProviderHttpError

        original = app_state.provider.submit_job

        async def flaky(config, upload_payload):
            raise ProviderHttpError(503, "upstream temporarily unavailable")

        monkeypatch.setattr(app_state.provider, "submit_job", flaky)
        for expected_attempts in (1, 2, 3):
            asyncio.run(sync_due_images(app_state))
            row = app_state.database.find_by_sha256(image_id[4:])
            # transient：claim 被释放回 pending，仅累计退避
            assert row["status"] == "pending"
            assert row["sync_attempts"] == expected_attempts
            # 清掉退避时间，让下一轮 tick 立即到期
            _clear_next_sync_at(app_state)

        # 退避到期前不会再被调度；恢复后清空调度即可继续提交成功
        monkeypatch.setattr(app_state.provider, "submit_job", original)
        _clear_next_sync_at(app_state)
        asyncio.run(sync_due_images(app_state))
        row = app_state.database.find_by_sha256(image_id[4:])
        assert row["provider_job_id"] == "job-1"
        assert row["status"] in ("pending", "running")


def test_worker_fails_terminal_after_max_attempts(app_state):
    with make_client(app_state) as client:
        image_id = upload(client, tiny_png()).json()["image_id"]
        from paddleocr_baseline.provider import ProviderHttpError
        from paddleocr_baseline.retry import TRANSIENT_FAILURE_MESSAGE
        from paddleocr_baseline.worker import _handle_sync_failure

        row = app_state.database.find_by_sha256(image_id[4:])
        _set_sync_attempts(app_state, row["id"], attempts=19)
        asyncio.run(_handle_sync_failure(app_state, row, ProviderHttpError(503, "upstream boom")))

        failed = app_state.database.find_by_sha256(image_id[4:])
        assert failed["status"] == "failed"
        assert failed["error_message"] == TRANSIENT_FAILURE_MESSAGE
        assert "upstream boom" in failed["last_sync_error"]


def _clear_next_sync_at(app_state) -> None:
    with sqlite3.connect(app_state.database.path) as connection:
        connection.execute("UPDATE images SET next_sync_at = NULL")


def _set_sync_attempts(app_state, image_id: int, attempts: int) -> None:
    with sqlite3.connect(app_state.database.path) as connection:
        connection.execute("UPDATE images SET sync_attempts = ? WHERE id = ?", (attempts, image_id))
