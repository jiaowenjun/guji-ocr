"""运行时共享状态：配置、数据库、provider 客户端与 worker 唤醒事件。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .config import ServerConfig
from .db import Database
from .provider import OcrProviderClient


@dataclass
class AppState:
    config: ServerConfig
    database: Database
    provider: OcrProviderClient
    wake: asyncio.Event = field(default_factory=asyncio.Event)

    def wake_worker(self) -> None:
        """上传或命中去重后立即唤醒 worker。"""
        self.wake.set()
