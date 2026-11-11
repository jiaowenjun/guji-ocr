"""服务配置。provider 的 URL 与模型是常量；token 只从 OCR_TOKEN 或 --token 读取，不内置。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .provider import ProviderConfig

JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
MODEL = "PaddleOCR-VL-1.6"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8010
DEFAULT_STORAGE = "./data/ocr"
DEFAULT_WORKER_POLL_INTERVAL_MS = 1_000
DEFAULT_CORS_ORIGINS = [
    f"http://{host}:{port}"
    for port in (5173, 5177, 4173, 4177)
    for host in ("localhost", "127.0.0.1")
]

TOKEN_REQUIRED_MESSAGE = "OCR token is required; set OCR_TOKEN or pass --token"


def default_provider_config() -> ProviderConfig:
    """占位配置（空 token）；生产路径经 load_config 校验，缺失即启动失败。"""
    return ProviderConfig(job_url=JOB_URL, api_token="", model=MODEL)


@dataclass(frozen=True)
class ServerConfig:
    provider: ProviderConfig = field(default_factory=default_provider_config)
    storage_path: Path = Path(DEFAULT_STORAGE)
    bind_host: str = DEFAULT_HOST
    bind_port: int = DEFAULT_PORT
    worker_poll_interval_ms: int = DEFAULT_WORKER_POLL_INTERVAL_MS
    cors_allowed_origins: list[str] = field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))

    @property
    def database_path(self) -> Path:
        return self.storage_path / "ocr.sqlite3"


def load_config(
    *,
    token: str | None = None,
    storage: str | None = None,
    host: str | None = None,
    port: int | None = None,
) -> ServerConfig:
    """显式参数优先，其次环境变量；token 无默认值，缺失即失败。"""
    api_token = (token or os.environ.get("OCR_TOKEN") or "").strip()
    if not api_token:
        raise ValueError(TOKEN_REQUIRED_MESSAGE)
    storage_path = storage or os.environ.get("OCR_STORAGE_PATH") or DEFAULT_STORAGE
    return ServerConfig(
        provider=ProviderConfig(job_url=JOB_URL, api_token=api_token, model=MODEL),
        storage_path=Path(storage_path).expanduser(),
        bind_host=host or os.environ.get("OCR_HOST") or DEFAULT_HOST,
        bind_port=port or int(os.environ.get("OCR_PORT") or DEFAULT_PORT),
    )
