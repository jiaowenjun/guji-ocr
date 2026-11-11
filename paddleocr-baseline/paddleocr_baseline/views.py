"""对外 JSON 视图：字段名与 weimo ocr-app 的 ImageView / ImageResultResponse 一致。"""

from __future__ import annotations

import json
import re
from typing import Any

from . import result as result_module
from .db import TERMINAL_STATUSES

_IMAGE_ID_PATTERN = re.compile(r"^img_([0-9a-fA-F]{64})$")


def image_id_for(sha256: str) -> str:
    return f"img_{sha256}"


def normalize_image_id(public_id: str) -> str | None:
    """合法的公开 id 是 ``img_`` + 64 位 hex；返回小写 sha256，否则 None。"""
    match = _IMAGE_ID_PATTERN.match(public_id)
    return match.group(1).lower() if match else None


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def build_image_view(row: dict[str, Any]) -> dict[str, Any]:
    image_id = image_id_for(row["sha256"])
    return {
        "image_id": image_id,
        "source_image": {
            "mime_type": row["image_mime_type"],
            "width": row["image_width"],
            "height": row["image_height"],
            "url": f"/ocr/images/{image_id}/source",
        },
        "result_url": f"/ocr/images/{image_id}/result",
        "result": build_result(row),
        "error": build_error(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "finished_at": row["finished_at"],
    }


def build_result_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "image_id": image_id_for(row["sha256"]),
        "result": build_result(row),
        "error": build_error(row),
        "finished_at": row["finished_at"],
    }


def build_result(row: dict[str, Any]) -> dict[str, Any] | None:
    if row["status"] != "succeeded":
        return None
    result_json = _parse_stored_json(row.get("result_json"))
    assets = [
        {"path": path, "url": f"/ocr/images/{image_id_for(row['sha256'])}/assets/{path}"}
        for path in sorted(result_module.extract_markdown_image_urls(result_json))
    ]
    return {
        "text": row.get("text_preview"),
        "markdown": row.get("result_markdown"),
        "json": result_json,
        "assets": assets,
    }


def build_error(row: dict[str, Any]) -> dict[str, Any] | None:
    if row["status"] != "failed":
        return None
    return {"message": row.get("error_message") or "OCR failed"}


def _parse_stored_json(value: str | None) -> Any | None:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None
