"""测试夹具：最小 PNG 字节与内存版假 provider。"""

from __future__ import annotations

import struct
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from paddleocr_baseline.config import ServerConfig
from paddleocr_baseline.db import Database
from paddleocr_baseline.provider import (
    ImageUpload,
    ProviderConfig,
    ProviderFetchResult,
    SubmitResult,
)
from paddleocr_baseline.state import AppState

PROVIDER_CONFIG = ProviderConfig(
    job_url="https://paddleocr.test/api/v2/ocr/jobs", api_token="test-token", model="PaddleOCR-VL-1.6"
)


def tiny_png(width: int = 4, height: int = 3) -> bytes:
    """只包含签名 + IHDR 的 PNG 头（嗅探只读前 24 字节）。"""
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height)


class FakeProvider:
    """内存版 provider：提交后按 fetch_result 返回状态，文本/资产按 URL 字典返回。"""

    def __init__(self) -> None:
        self.submitted: list[ImageUpload] = []
        self.fetch_result = ProviderFetchResult("running", None, None, None)
        self.texts: dict[str, str] = {}
        self.binaries: dict[str, bytes] = {}

    async def submit_job(self, config: ProviderConfig, upload: ImageUpload) -> SubmitResult:
        self.submitted.append(upload)
        return SubmitResult(job_id="job-1", provider_state="pending")

    async def fetch_job(self, config: ProviderConfig, provider_job_id: str) -> ProviderFetchResult:
        return self.fetch_result

    async def download_text(self, url: str) -> str:
        return self.texts[url]

    async def download_binary(self, url: str) -> bytes:
        return self.binaries[url]

    async def aclose(self) -> None:
        return None


@pytest.fixture
def app_state(tmp_path: Path) -> AppState:
    # worker_poll_interval_ms=0 让 worker tick 之间无需真实等待
    config = ServerConfig(
        provider=PROVIDER_CONFIG, storage_path=tmp_path / "ocr", worker_poll_interval_ms=0
    )
    state = AppState(config=config, database=Database(config.database_path), provider=FakeProvider())
    state.database.init()
    return state
