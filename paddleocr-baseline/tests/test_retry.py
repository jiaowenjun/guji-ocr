"""retry.py：失败分类、退避表与终态阈值。"""

import pytest

from paddleocr_baseline.provider import OcrError, ProviderHttpError
from paddleocr_baseline.retry import (
    FailureKind,
    backoff_seconds,
    classify_failure,
    public_failure_message,
    should_fail_terminal,
)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ProviderHttpError(429, "too many requests"), FailureKind.TRANSIENT),
        (ProviderHttpError(503, "upstream unavailable"), FailureKind.TRANSIENT),
        (OcrError("Submit OCR job failed: connection reset by peer"), FailureKind.TRANSIENT),
        (ProviderHttpError(401, "unauthorized"), FailureKind.PERMANENT),
        (ProviderHttpError(400, "bad request"), FailureKind.PERMANENT),
        (OcrError("Read OCR upload failed: nope"), FailureKind.INTERNAL),
        (OcrError("OCR provider response missing jobId"), FailureKind.INTERNAL),
        (OcrError("Parse OCR result JSON failed: bad"), FailureKind.INTERNAL),
        (ProviderHttpError(418, "teapot, unclassified"), FailureKind.PERMANENT),
    ],
)
def test_classify_failure(error, expected):
    assert classify_failure(error) is expected


@pytest.mark.parametrize(
    ("attempts", "seconds"),
    [(1, 15), (2, 30), (3, 60), (4, 120), (5, 300), (20, 300)],
)
def test_backoff_table(attempts, seconds):
    assert backoff_seconds(attempts) == seconds


def test_terminal_threshold():
    assert not should_fail_terminal(19)
    assert should_fail_terminal(20)


def test_public_messages_distinct():
    messages = {public_failure_message(kind) for kind in FailureKind}
    assert len(messages) == 3
