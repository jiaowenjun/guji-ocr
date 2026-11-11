"""config.py：token 只来自 OCR_TOKEN 或显式参数，缺失即失败。"""

import pytest

from paddleocr_baseline.config import JOB_URL, MODEL, load_config


def test_load_config_requires_token(monkeypatch):
    monkeypatch.delenv("OCR_TOKEN", raising=False)
    with pytest.raises(ValueError, match="OCR token is required"):
        load_config()


def test_load_config_rejects_blank_token(monkeypatch):
    monkeypatch.setenv("OCR_TOKEN", "   ")
    with pytest.raises(ValueError, match="OCR token is required"):
        load_config()


def test_load_config_reads_env_and_explicit_token(monkeypatch, tmp_path):
    monkeypatch.setenv("OCR_TOKEN", "env-token")
    from_env = load_config(storage=str(tmp_path))
    assert from_env.provider.api_token == "env-token"
    assert from_env.provider.job_url == JOB_URL
    assert from_env.provider.model == MODEL

    explicit = load_config(token="cli-token", storage=str(tmp_path))
    assert explicit.provider.api_token == "cli-token"
