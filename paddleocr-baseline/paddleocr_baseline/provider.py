"""PaddleOCR provider 客户端：提交 job、轮询状态、下载结果。

对齐 weimo-ocr backend 的 ``src/ocr_domain/provider.rs``：
- 提交/轮询带 ``Authorization: Bearer <token>``，结果下载不带。
- provider 状态只有 pending / running / done / failed。
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

OPTIONAL_PAYLOAD = '{"useDocOrientationClassify":false,"useDocUnwarping":false,"useChartRecognition":false}'
PROVIDER_STATES = ("pending", "running", "done", "failed")
HTTP_TIMEOUT = httpx.Timeout(30.0, read=120.0)


class OcrError(Exception):
    """OCR 链路错误；permanent/internal 由 retry 分类，message 会进入日志。"""


class ProviderHttpError(OcrError):
    """provider 返回非 2xx；携带状态码与响应体供错误分类。"""

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(body or f"OCR provider error: {status_code}")
        self.status_code = status_code
        self.body = body


@dataclass(frozen=True)
class ProviderConfig:
    job_url: str
    api_token: str
    model: str


@dataclass(frozen=True)
class ImageUpload:
    filename: str
    mime_type: str
    bytes: bytes


@dataclass(frozen=True)
class SubmitResult:
    job_id: str
    provider_state: str


@dataclass(frozen=True)
class ProviderFetchResult:
    provider_state: str
    result_json_url: str | None
    result_markdown_url: str | None
    error_message: str | None


def _data_object(payload: object) -> dict:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return {}


def _non_empty(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


class OcrProviderClient:
    """异步客户端；httpx.Client 般可注入 transport 以便测试。"""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(timeout=HTTP_TIMEOUT, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def submit_job(self, config: ProviderConfig, upload: ImageUpload) -> SubmitResult:
        form = {"model": config.model, "optionalPayload": OPTIONAL_PAYLOAD}
        files = {"file": (upload.filename, upload.bytes, upload.mime_type)}
        try:
            response = await self._client.post(
                config.job_url,
                data=form,
                files=files,
                headers={"Authorization": f"Bearer {config.api_token}"},
            )
        except httpx.HTTPError as err:
            raise OcrError(f"Submit OCR job failed: {err}") from err
        if response.status_code >= 400:
            raise ProviderHttpError(response.status_code, response.text)
        data = _data_object(response.json())
        job_id = _non_empty(data.get("jobId"))
        if job_id is None:
            raise OcrError("OCR provider response missing jobId")
        state = data.get("state")
        provider_state = state if state in PROVIDER_STATES else "pending"
        return SubmitResult(job_id=job_id, provider_state=provider_state)

    async def fetch_job(self, config: ProviderConfig, provider_job_id: str) -> ProviderFetchResult:
        fetch_url = f"{config.job_url.rstrip('/')}/{provider_job_id}"
        try:
            response = await self._client.get(
                fetch_url, headers={"Authorization": f"Bearer {config.api_token}"}
            )
        except httpx.HTTPError as err:
            raise OcrError(f"Fetch OCR job failed: {err}") from err
        if response.status_code >= 400:
            raise ProviderHttpError(response.status_code, response.text)
        data = _data_object(response.json())
        state = data.get("state")
        provider_state = state if state in PROVIDER_STATES else "pending"
        result_url = data.get("resultUrl")
        json_url = None
        markdown_url = None
        if isinstance(result_url, dict):
            json_url = _non_empty(result_url.get("jsonUrl"))
            markdown_url = _non_empty(result_url.get("markdownUrl"))
        return ProviderFetchResult(
            provider_state=provider_state,
            result_json_url=json_url,
            result_markdown_url=markdown_url,
            error_message=_non_empty(data.get("errorMsg")),
        )

    async def download_text(self, url: str) -> str:
        try:
            response = await self._client.get(url)
        except httpx.HTTPError as err:
            raise OcrError(f"Download OCR result failed: {err}") from err
        if response.status_code >= 400:
            raise ProviderHttpError(response.status_code, response.text)
        return response.text

    async def download_binary(self, url: str) -> bytes:
        try:
            response = await self._client.get(url)
        except httpx.HTTPError as err:
            raise OcrError(f"Download OCR asset failed: {err}") from err
        if response.status_code >= 400:
            raise ProviderHttpError(response.status_code, response.text)
        return response.content


def absolutize_provider_url(provider_base: str, url: str) -> str:
    """相对 URL 基于 provider job URL 拼接；绝对 URL 原样返回。"""
    if url.startswith(("http://", "https://")):
        return url
    return urljoin(f"{provider_base.rstrip('/')}/", url)


def local_status_from_provider_state(provider_state: str) -> str:
    if provider_state in ("pending", "running", "failed"):
        return provider_state
    return "pending"
