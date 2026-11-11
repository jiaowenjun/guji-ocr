"""result.py：JSONL 归一、markdown 资产提取、文本预览。"""

import json

import pytest

from paddleocr_baseline.result import (
    build_text_preview,
    extract_markdown_image_urls,
    parse_result_json_text,
)


def test_parse_none_and_empty():
    assert parse_result_json_text(None) is None
    assert parse_result_json_text("  \n  \n") is None


def test_parse_single_line_json():
    assert parse_result_json_text('{"a": 1}') == {"a": 1}


def test_parse_jsonl_lines_to_array():
    value = parse_result_json_text('{"a": 1}\n{"b": 2}\n')
    assert value == [{"a": 1}, {"b": 2}]


def test_parse_invalid_json_raises():
    with pytest.raises(json.JSONDecodeError):
        parse_result_json_text("{not json}")


def test_extract_markdown_image_urls_from_all_levels():
    payload = {
        "markdown": {"images": {"top.png": "https://cdn.test/top.png"}},
        "result": {
            "markdown": {"images": {"mid.png": "https://cdn.test/mid.png"}},
            "layoutParsingResults": [
                {"markdown": {"images": {"deep.png": "https://cdn.test/deep.png"}}},
                {"markdown": {"images": {"": "https://cdn.test/skip.png", "bad": ""}}},
            ],
        },
    }
    urls = extract_markdown_image_urls(payload)
    assert urls == {
        "top.png": "https://cdn.test/top.png",
        "mid.png": "https://cdn.test/mid.png",
        "deep.png": "https://cdn.test/deep.png",
    }


def test_extract_from_array_of_items():
    payload = [{"markdown": {"images": {"a.png": "u1"}}}, {"markdown": {"images": {"b.png": "u2"}}}]
    assert extract_markdown_image_urls(payload) == {"a.png": "u1", "b.png": "u2"}


def test_text_preview_prefers_markdown_first_line():
    assert build_text_preview("\n#  标题行\n正文", None) == "标题行"


def test_text_preview_truncates_to_120_chars():
    assert len(build_text_preview("字" * 200, None)) == 120


def test_text_preview_falls_back_to_result_json():
    result_json = {
        "result": {
            "layoutParsingResults": [
                {"markdown": {"text": "# 第一段"}},
                {"markdown": {"text": "第二段"}},
            ]
        }
    }
    assert build_text_preview(None, result_json) == "第一段"


def test_text_preview_empty_when_nothing_available():
    assert build_text_preview(None, None) is None
    assert build_text_preview("  \n# \n", None) is None
