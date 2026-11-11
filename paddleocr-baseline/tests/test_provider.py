"""provider.py：用 httpx.MockTransport 模拟提交/轮询/下载。"""

import asyncio

import httpx
import pytest

from paddleocr_baseline.provider import (
    ImageUpload,
    OcrError,
    OcrProviderClient,
    ProviderHttpError,
    absolutize_provider_url,
    local_status_from_provider_state,
)
from tests.conftest import PROVIDER_CONFIG

JOB_URL = PROVIDER_CONFIG.job_url


def make_client(handler) -> OcrProviderClient:
    return OcrProviderClient(transport=httpx.MockTransport(handler))


def test_submit_job_sends_multipart_with_bearer():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["content_type"] = request.headers.get("Content-Type")
        body = request.content.decode("utf-8", errors="replace")
        captured["model"] = "PaddleOCR-VL-1.6" in body
        captured["optional_payload"] = "optionalPayload" in body
        captured["file"] = "img_test.png" in body
        return httpx.Response(200, json={"data": {"jobId": "job-9", "state": "pending"}})

    client = make_client(handler)
    result = asyncio.run(
        client.submit_job(PROVIDER_CONFIG, ImageUpload("img_test.png", "image/png", b"fake-png"))
    )
    asyncio.run(client.aclose())

    assert result.job_id == "job-9"
    assert result.provider_state == "pending"
    assert captured["auth"] == "Bearer test-token"
    assert captured["content_type"].startswith("multipart/form-data")
    assert captured["model"] and captured["optional_payload"] and captured["file"]


def test_fetch_job_parses_result_urls_and_error():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{JOB_URL}/job-9"
        assert request.headers.get("Authorization") == "Bearer test-token"
        return httpx.Response(
            200,
            json={
                "data": {
                    "state": "done",
                    "resultUrl": {"jsonUrl": "results/9.json", "markdownUrl": ""},
                    "errorMsg": None,
                }
            },
        )

    client = make_client(handler)
    fetched = asyncio.run(client.fetch_job(PROVIDER_CONFIG, "job-9"))
    asyncio.run(client.aclose())
    assert fetched.provider_state == "done"
    assert fetched.result_json_url == "results/9.json"
    assert fetched.result_markdown_url is None
    assert fetched.error_message is None


def test_download_text_has_no_bearer():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        return httpx.Response(200, text="# markdown")

    client = make_client(handler)
    assert asyncio.run(client.download_text("https://cdn.test/a.md")) == "# markdown"
    asyncio.run(client.aclose())


def test_non_2xx_raises_provider_http_error_with_body():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid token")

    client = make_client(handler)
    with pytest.raises(ProviderHttpError) as excinfo:
        asyncio.run(client.submit_job(PROVIDER_CONFIG, ImageUpload("a.png", "image/png", b"x")))
    asyncio.run(client.aclose())
    assert excinfo.value.status_code == 401
    assert "invalid token" in str(excinfo.value)


def test_missing_job_id_raises_ocr_error():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"state": "pending"}})

    client = make_client(handler)
    with pytest.raises(OcrError, match="missing jobId"):
        asyncio.run(client.submit_job(PROVIDER_CONFIG, ImageUpload("a.png", "image/png", b"x")))
    asyncio.run(client.aclose())


def test_absolutize_provider_url():
    assert absolutize_provider_url(JOB_URL, "https://cdn.test/a.png") == "https://cdn.test/a.png"
    assert absolutize_provider_url(JOB_URL, "/files/a.png") == "https://paddleocr.test/files/a.png"
    assert (
        absolutize_provider_url(JOB_URL, "files/a.png")
        == "https://paddleocr.test/api/v2/ocr/jobs/files/a.png"
    )


def test_local_status_mapping():
    assert local_status_from_provider_state("pending") == "pending"
    assert local_status_from_provider_state("running") == "running"
    assert local_status_from_provider_state("failed") == "failed"
    assert local_status_from_provider_state("done") == "pending"
    assert local_status_from_provider_state("weird") == "pending"
