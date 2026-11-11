"""图片格式嗅探：PNG / JPEG / WebP 的 mime 类型与尺寸（不引第三方图像库）。

对齐 weimo-ocr backend 的 ``src/image_metadata.rs`` 的行为边界：
- 只接受 PNG / JPEG / WebP；
- 尺寸必须非零，否则视为非法图片。
"""

from __future__ import annotations

import struct

MIME_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


class InvalidImageError(ValueError):
    """图片格式不受支持或尺寸非法。"""


def sniff_image(data: bytes) -> tuple[str, int, int]:
    """返回 (mime_type, width, height)；不支持的格式抛 InvalidImageError。"""
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        if width == 0 or height == 0:
            raise InvalidImageError("OCR image dimensions are required")
        return "image/png", width, height
    if len(data) >= 4 and data.startswith(b"\xff\xd8"):
        size = _jpeg_size(data)
        if size is None:
            raise InvalidImageError("Unsupported OCR image file: jpeg")
        return "image/jpeg", *size
    if len(data) >= 30 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        size = _webp_size(data)
        if size is None:
            raise InvalidImageError("Unsupported OCR image file: webp")
        return "image/webp", *size
    raise InvalidImageError("Unsupported OCR image file")


def extension_for_mime(mime_type: str) -> str:
    try:
        return MIME_EXTENSIONS[mime_type]
    except KeyError as err:
        raise InvalidImageError(f"Unsupported OCR image mime type: {mime_type}") from err


def canonical_image_filename(sha256: str, mime_type: str) -> str:
    return f"img_{sha256}.{extension_for_mime(mime_type)}"


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    offset = 2
    while offset + 9 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        if marker == 0xFF:  # 填充字节
            offset += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        if offset + 4 > len(data):
            return None
        segment_length = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
        if (
            marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF)
            and offset + 9 <= len(data)
        ):
            height, width = struct.unpack(">HH", data[offset + 5 : offset + 9])
            if width == 0 or height == 0:
                return None
            return width, height
        offset += 2 + segment_length
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
    elif chunk == b"VP8 " and len(data) >= 30:
        width = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        height = struct.unpack("<H", data[28:30])[0] & 0x3FFF
    elif chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        width = 1 + ((data[22] & 0x3F) << 8 | data[21])
        height = 1 + ((data[24] & 0x0F) << 10 | data[23] << 2 | (data[22] & 0xC0) >> 6)
    else:
        return None
    if width == 0 or height == 0:
        return None
    return width, height
