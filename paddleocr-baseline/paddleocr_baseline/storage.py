"""磁盘存储布局与 markdown 资产路径归一。

对齐 weimo-ocr backend 的 ``src/storage.rs`` 与 ``src/ocr_domain/assets.rs``：
- 原图：``{storage}/uploads/ocr-images/img_<sha256>.<ext>``
- markdown 资产：``{storage}/uploads/ocr-markdown-assets/<内部id>/<asset_path>``
"""

from __future__ import annotations

from pathlib import Path

OCR_IMAGE_DIR = "uploads/ocr-images"
MARKDOWN_ASSET_DIR = "uploads/ocr-markdown-assets"


def storage_path(root: Path, storage_key: str) -> Path:
    return root / storage_key


def ocr_image_storage_key(sha256: str, extension: str) -> str:
    return f"{OCR_IMAGE_DIR}/img_{sha256}.{extension}"


def markdown_asset_dir(root: Path, image_id: int) -> Path:
    return root / MARKDOWN_ASSET_DIR / str(image_id)


def normalize_markdown_asset_path(path: str) -> str | None:
    """反斜杠归一为 ``/``；拒绝空路径、绝对路径与 ``.``/``..`` 段。"""
    normalized = path.replace("\\", "/")
    if not normalized.strip() or normalized.startswith("/"):
        return None
    segments = normalized.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        return None
    return normalized


def write_markdown_asset(root: Path, image_id: int, asset_path: str, data: bytes) -> Path:
    normalized = normalize_markdown_asset_path(asset_path)
    if normalized is None:
        raise ValueError(f"Invalid markdown asset path: {asset_path!r}")
    target = markdown_asset_dir(root, image_id) / normalized
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target
