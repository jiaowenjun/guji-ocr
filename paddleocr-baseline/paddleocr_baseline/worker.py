"""后台同步 worker：提交 pending 图片、轮询 provider job、落地结果。

对齐 weimo-ocr backend 的 ``src/image_sync``：
- 没有 provider_job_id → 提交；有 → 轮询。
- 提交前 claim，防止重复提交；提交失败释放 claim。
- done → 下载 markdown/json、缓存 markdown 图片资产、写库；failed → 记录 provider 错误。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from . import result as result_module
from . import retry, storage
from .db import ACTIVE_STATUSES
from .image_metadata import canonical_image_filename
from .provider import (
    ImageUpload,
    OcrError,
    ProviderFetchResult,
    absolutize_provider_url,
    local_status_from_provider_state,
)
from .state import AppState

logger = logging.getLogger(__name__)

WORKER_BATCH_LIMIT = 25
WORKER_IDLE_FALLBACK_SCAN_S = 60.0


async def run_worker(state: AppState) -> None:
    while True:
        try:
            await sync_due_images(state)
        except Exception:  # noqa: BLE001 - worker 不能因单次 tick 失败退出
            logger.exception("Image worker tick failed")

        idle_sleep = await _worker_idle_sleep(state)
        if idle_sleep <= 0:
            continue
        try:
            await asyncio.wait_for(state.wake.wait(), timeout=idle_sleep)
        except asyncio.TimeoutError:
            pass
        state.wake.clear()


async def sync_due_images(state: AppState, limit: int = WORKER_BATCH_LIMIT) -> int:
    """同步一批到期图片，返回处理的数量。"""
    image_ids = await asyncio.to_thread(state.database.due_image_ids, limit)
    for image_id in image_ids:
        try:
            await sync_image_once(state, image_id)
        except Exception:  # noqa: BLE001 - 单张失败不影响同批其他图片
            logger.exception("Sync OCR image failed: internal_image_id=%s", image_id)
    return len(image_ids)


async def sync_image_once(state: AppState, image_id: int) -> None:
    row = await asyncio.to_thread(state.database.get_image, image_id)
    if row is None or row["status"] not in ACTIVE_STATUSES:
        return
    if row["provider_job_id"]:
        await _sync_provider_backed_image(state, row)
    else:
        await _submit_pending_image(state, row)


async def _submit_pending_image(state: AppState, row: dict[str, Any]) -> None:
    database = state.database
    image_id = row["id"]
    path = storage.storage_path(state.config.storage_path, row["image_storage_key"])
    try:
        data = await asyncio.to_thread(path.read_bytes)
    except OSError as err:
        await _handle_sync_failure(state, row, OcrError(f"Read OCR upload failed: {err}"))
        return

    poll_ms = state.config.worker_poll_interval_ms
    if not await asyncio.to_thread(database.claim_image_submission, image_id, poll_ms):
        logger.info("Skipping submit, another sync claimed it: internal_image_id=%s", image_id)
        return

    logger.info("Submitting OCR image to provider: internal_image_id=%s bytes=%s", image_id, len(data))
    upload = ImageUpload(
        filename=canonical_image_filename(row["sha256"], row["image_mime_type"]),
        mime_type=row["image_mime_type"],
        bytes=data,
    )
    try:
        submitted = await state.provider.submit_job(state.config.provider, upload)
    except Exception as err:  # noqa: BLE001 - 统一走失败分类
        await asyncio.to_thread(database.release_image_submission_claim, image_id)
        await _handle_sync_failure(state, row, err)
        return

    status = local_status_from_provider_state(submitted.provider_state)
    await asyncio.to_thread(
        database.mark_image_submitted,
        image_id,
        provider_job_id=submitted.job_id,
        provider_state=submitted.provider_state,
        status=status,
        next_poll_ms=poll_ms,
    )
    logger.info(
        "Submitted OCR image: internal_image_id=%s provider_job_id=%s provider_state=%s",
        image_id,
        submitted.job_id,
        submitted.provider_state,
    )


async def _sync_provider_backed_image(state: AppState, row: dict[str, Any]) -> None:
    database = state.database
    image_id = row["id"]
    try:
        fetched = await state.provider.fetch_job(state.config.provider, row["provider_job_id"])
    except Exception as err:  # noqa: BLE001
        await _handle_sync_failure(state, row, err)
        return

    logger.info(
        "Polled OCR image: internal_image_id=%s provider_state=%s", image_id, fetched.provider_state
    )
    if fetched.provider_state == "done":
        try:
            await _finish_succeeded_image(state, row, fetched)
        except Exception as err:  # noqa: BLE001
            await _handle_sync_failure(state, row, err)
    elif fetched.provider_state == "failed":
        message = fetched.error_message or "Image provider failed"
        await asyncio.to_thread(
            database.finish_failed, image_id, public_message=message, detail=message
        )
        logger.warning("OCR image failed at provider: internal_image_id=%s", image_id)
    else:
        await asyncio.to_thread(
            database.mark_image_running,
            image_id,
            provider_state=fetched.provider_state,
            status=local_status_from_provider_state(fetched.provider_state),
            next_poll_ms=state.config.worker_poll_interval_ms,
        )


async def _finish_succeeded_image(
    state: AppState, row: dict[str, Any], fetched: ProviderFetchResult
) -> None:
    job_url = state.config.provider.job_url
    markdown_text = None
    if fetched.result_markdown_url:
        markdown_text = await state.provider.download_text(
            absolutize_provider_url(job_url, fetched.result_markdown_url)
        )
    result_json_text = None
    if fetched.result_json_url:
        result_json_text = await state.provider.download_text(
            absolutize_provider_url(job_url, fetched.result_json_url)
        )
    try:
        result_json = result_module.parse_result_json_text(result_json_text)
    except json.JSONDecodeError as err:
        raise OcrError(f"Parse OCR result JSON failed: {err}") from err

    if result_json is not None:
        await _cache_markdown_assets(state, row["id"], result_json)

    await asyncio.to_thread(
        state.database.finish_succeeded,
        row["id"],
        text_preview=result_module.build_text_preview(markdown_text, result_json),
        result_markdown=markdown_text,
        result_json=json.dumps(result_json, ensure_ascii=False) if result_json is not None else None,
    )
    logger.info("Stored OCR image result: internal_image_id=%s", row["id"])


async def _cache_markdown_assets(state: AppState, image_id: int, result_json: Any) -> None:
    job_url = state.config.provider.job_url
    for path, url in result_module.extract_markdown_image_urls(result_json).items():
        try:
            data = await state.provider.download_binary(absolutize_provider_url(job_url, url))
            await asyncio.to_thread(
                storage.write_markdown_asset, state.config.storage_path, image_id, path, data
            )
        except Exception as err:  # noqa: BLE001 - 资产缓存失败不阻断结果入库
            logger.warning(
                "Cache OCR markdown asset failed: internal_image_id=%s asset_path=%s error=%s",
                image_id,
                path,
                err,
            )


async def _handle_sync_failure(state: AppState, row: dict[str, Any], error: BaseException) -> None:
    database = state.database
    image_id = row["id"]
    detail = str(error)
    kind = retry.classify_failure(error)
    # 重新读取当前 attempts，避免使用 tick 开始时的旧快照
    current = await asyncio.to_thread(database.get_image, image_id) or row
    attempts = current["sync_attempts"] + 1
    if kind is retry.FailureKind.TRANSIENT and not retry.should_fail_terminal(attempts):
        backoff_s = retry.backoff_seconds(attempts)
        await asyncio.to_thread(
            database.record_sync_retry, image_id, attempts=attempts, backoff_s=backoff_s, detail=detail
        )
        logger.warning(
            "OCR image sync will retry: internal_image_id=%s attempts=%s backoff_s=%s error=%s",
            image_id,
            attempts,
            backoff_s,
            detail,
        )
        return
    await asyncio.to_thread(
        database.finish_failed,
        image_id,
        public_message=retry.public_failure_message(kind),
        detail=detail,
    )
    logger.error(
        "OCR image failed terminally: internal_image_id=%s kind=%s error=%s",
        image_id,
        kind.value,
        detail,
    )


async def _worker_idle_sleep(state: AppState) -> float:
    try:
        delay_ms = await asyncio.to_thread(state.database.next_sync_delay_ms)
    except Exception:  # noqa: BLE001
        logger.exception("Load next OCR image sync delay failed")
        return WORKER_IDLE_FALLBACK_SCAN_S
    if delay_ms is None:
        return WORKER_IDLE_FALLBACK_SCAN_S
    return min(delay_ms / 1000.0, WORKER_IDLE_FALLBACK_SCAN_S)
