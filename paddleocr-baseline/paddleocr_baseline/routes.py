"""FastAPI 应用：对外 API 形状与 weimo ocr-app 的 ``/ocr`` 公开端点一致。"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
from contextlib import asynccontextmanager, suppress
from typing import Any, AsyncIterator

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import storage, views
from .config import ServerConfig
from .db import ACTIVE_STATUSES, Database
from .image_metadata import InvalidImageError, extension_for_mime, sniff_image
from .provider import OcrProviderClient
from .state import AppState
from .worker import run_worker

OCR_IMAGE_UPLOAD_LIMIT_BYTES = 20 * 1024 * 1024


def build_state(config: ServerConfig, provider: OcrProviderClient | None = None) -> AppState:
    return AppState(
        config=config,
        database=Database(config.database_path),
        provider=provider or OcrProviderClient(),
    )


def create_app(state: AppState, *, start_worker: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(state.database.init)
        worker_task = asyncio.create_task(run_worker(state)) if start_worker else None
        try:
            yield
        finally:
            if worker_task is not None:
                worker_task.cancel()
                with suppress(asyncio.CancelledError):
                    await worker_task
            await state.provider.aclose()

    app = FastAPI(title="paddleocr-baseline", lifespan=lifespan)
    app.state.ocr = state
    app.add_middleware(
        CORSMiddleware,
        allow_origins=state.config.cors_allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )

    async def load_image(public_id: str) -> dict[str, Any]:
        sha256 = views.normalize_image_id(public_id)
        if sha256 is None:
            raise HTTPException(status_code=404, detail="Image not found")
        row = await asyncio.to_thread(state.database.find_by_sha256, sha256)
        if row is None:
            raise HTTPException(status_code=404, detail="OCR image not found")
        return row

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "service": "ocr"}

    @app.post("/ocr/images", status_code=201)
    async def upload_image(file: UploadFile = File(...)) -> dict[str, Any]:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="OCR image file is required")
        if len(data) > OCR_IMAGE_UPLOAD_LIMIT_BYTES:
            raise HTTPException(status_code=413, detail="OCR image file exceeds the 20 MiB limit")
        try:
            mime_type, width, height = sniff_image(data)
        except InvalidImageError as err:
            raise HTTPException(status_code=400, detail=f"Invalid OCR image file: {err}") from err

        sha256 = hashlib.sha256(data).hexdigest()
        existing = await asyncio.to_thread(state.database.find_by_sha256, sha256)
        if existing is None:
            storage_key = storage.ocr_image_storage_key(sha256, extension_for_mime(mime_type))
            path = storage.storage_path(state.config.storage_path, storage_key)
            await asyncio.to_thread(_write_upload, path, data)
            existing = await asyncio.to_thread(
                state.database.insert_image,
                sha256=sha256,
                mime_type=mime_type,
                width=width,
                height=height,
                storage_key=storage_key,
            )
        if existing["status"] in ACTIVE_STATUSES:
            state.wake_worker()
        return views.build_image_view(existing)

    @app.get("/ocr/images/{image_id}")
    async def get_image(image_id: str) -> dict[str, Any]:
        return views.build_image_view(await load_image(image_id))

    @app.get("/ocr/images/{image_id}/result")
    async def get_image_result(image_id: str) -> JSONResponse:
        row = await load_image(image_id)
        status_code = 200 if views.is_terminal(row["status"]) else 202
        return JSONResponse(views.build_result_response(row), status_code=status_code)

    @app.get("/ocr/images/{image_id}/source")
    async def get_image_source(image_id: str) -> FileResponse:
        row = await load_image(image_id)
        path = storage.storage_path(state.config.storage_path, row["image_storage_key"])
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Image source not found")
        return FileResponse(path, media_type=row["image_mime_type"])

    @app.get("/ocr/images/{image_id}/assets/{asset_path:path}")
    async def get_image_asset(image_id: str, asset_path: str) -> FileResponse:
        row = await load_image(image_id)
        normalized = storage.normalize_markdown_asset_path(asset_path)
        if normalized is None:
            raise HTTPException(status_code=404, detail="OCR markdown asset not found")
        path = storage.markdown_asset_dir(state.config.storage_path, row["id"]) / normalized
        if not path.is_file():
            raise HTTPException(status_code=404, detail="OCR markdown asset not found")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type)

    return app


def _write_upload(path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
