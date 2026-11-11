"""OCR 结果解析：JSONL 归一、markdown 图片资产提取、文本预览。

对齐 weimo-ocr backend 的 ``src/ocr_domain/result.rs``。
"""

from __future__ import annotations

import json
from typing import Any

TEXT_PREVIEW_MAX_CHARS = 120


def parse_result_json_text(value: str | None) -> Any | None:
    """单行按 JSON 解析；多行按 JSONL 归一为 JSON 数组；空值返回 None。"""
    if value is None:
        return None
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return None
    if len(lines) == 1:
        return json.loads(lines[0])
    return [json.loads(line) for line in lines]


def extract_markdown_image_urls(value: Any) -> dict[str, str]:
    """从结果 JSON 的 markdown.images 里收集 {资产路径: provider URL}。"""
    urls: dict[str, str] = {}
    for item in _json_items(value):
        _collect_markdown_images(_get(item, "markdown"), urls)
        result = _get(item, "result")
        _collect_markdown_images(_get(result, "markdown"), urls)
        layouts = _get(result, "layoutParsingResults")
        if isinstance(layouts, list):
            for layout in layouts:
                _collect_markdown_images(_get(layout, "markdown"), urls)
    return urls


def build_text_preview(markdown_text: str | None, result_json: Any | None) -> str | None:
    """第一个非空行（去掉 markdown 标题符号），截断到 120 字符。"""
    lines: list[str] = []
    if markdown_text:
        lines.extend(markdown_text.splitlines())
    lines.extend(_markdown_texts_from_result_json(result_json))
    for line in lines:
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned[:TEXT_PREVIEW_MAX_CHARS]
    return None


def _json_items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _get(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None


def _collect_markdown_images(markdown: Any, urls: dict[str, str]) -> None:
    images = _get(markdown, "images")
    if not isinstance(images, dict):
        return
    for path, url in images.items():
        if not isinstance(path, str) or not path.strip():
            continue
        if not isinstance(url, str) or not url.strip():
            continue
        urls[path.strip()] = url.strip()


def _markdown_texts_from_result_json(result_json: Any) -> list[str]:
    texts: list[str] = []
    for item in _json_items(result_json):
        layouts = _get(_get(item, "result"), "layoutParsingResults")
        if not isinstance(layouts, list):
            continue
        for layout in layouts:
            text = _get(_get(layout, "markdown"), "text")
            if isinstance(text, str):
                texts.append(text)
    return texts
