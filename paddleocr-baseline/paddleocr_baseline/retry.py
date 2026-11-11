"""同步失败分类与退避策略。

对齐 weimo-ocr backend 的 ``src/retry_policy.rs``（取其常用子集）：
- transient：网络/超时/限流/队列满/5xx → 退避重试，超过上限转终态失败。
- permanent：token/权限/请求本身错误 → 直接终态失败。
- internal：本地读写/解析错误 → 终态失败。
对外错误消息使用固定文案，不透出 provider 细节。
"""

from __future__ import annotations

from enum import Enum

from .provider import OcrError, ProviderHttpError

MAX_TRANSIENT_SYNC_ATTEMPTS = 20

TRANSIENT_FAILURE_MESSAGE = (
    "OCR provider is temporarily unavailable. The OCR image was retried but did not complete."
)
PERMANENT_FAILURE_MESSAGE = (
    "OCR provider rejected the request. Check the token, image, or model configuration."
)
INTERNAL_FAILURE_MESSAGE = "OCR image failed before it could be submitted. Please retry the upload."

# 依次匹配；先判 permanent 再判 transient，命中即返回。
_TRANSIENT_MARKERS = (
    "任务提交队列已满",
    "10010",
    "429",
    "too many requests",
    "queue",
    "temporarily unavailable",
    "timeout",
    "timed out",
    "error sending request",
    "connection reset",
    "connection refused",
    "dns",
    "tls",
    "500",
    "502",
    "503",
    "504",
)
_PERMANENT_MARKERS = (
    "401",
    "403",
    "unauthorized",
    "forbidden",
    "invalid token",
    "api token",
    "api key",
    "bad request",
    "400",
    "model not found",
    "unsupported image",
    "invalid image",
    "provider token is required",
)
_INTERNAL_MARKERS = (
    "read ocr upload failed",
    "parse ocr",
    "parse result json",
    "database",
    "missing jobid",
)


class FailureKind(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    INTERNAL = "internal"


def classify_failure(error: BaseException) -> FailureKind:
    if isinstance(error, ProviderHttpError):
        message = f"{error.status_code} {error.body}".lower()
    elif isinstance(error, OcrError):
        message = str(error).lower()
    else:
        message = str(error).lower()
    for marker in _INTERNAL_MARKERS:
        if marker in message:
            return FailureKind.INTERNAL
    for marker in _PERMANENT_MARKERS:
        if marker in message:
            return FailureKind.PERMANENT
    for marker in _TRANSIENT_MARKERS:
        if marker in message:
            return FailureKind.TRANSIENT
    # 与 Rust 实现一致：网络异常（无状态码）默认按 transient 重试。
    if not isinstance(error, ProviderHttpError):
        return FailureKind.TRANSIENT
    # 带状态码但未命中标记：4xx 视为 permanent，其余按 transient。
    if isinstance(error, ProviderHttpError) and 400 <= error.status_code < 500:
        return FailureKind.PERMANENT
    return FailureKind.TRANSIENT


def public_failure_message(kind: FailureKind) -> str:
    if kind is FailureKind.TRANSIENT:
        return TRANSIENT_FAILURE_MESSAGE
    if kind is FailureKind.PERMANENT:
        return PERMANENT_FAILURE_MESSAGE
    return INTERNAL_FAILURE_MESSAGE


def backoff_seconds(attempts: int) -> int:
    """attempts 为本次失败后的累计尝试次数（从 1 开始）。"""
    if attempts <= 1:
        return 15
    if attempts == 2:
        return 30
    if attempts == 3:
        return 60
    if attempts == 4:
        return 120
    return 300


def should_fail_terminal(attempts: int) -> bool:
    return attempts >= MAX_TRANSIENT_SYNC_ATTEMPTS
