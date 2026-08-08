from __future__ import annotations

import logging

from scalping.monitoring.logging import SecretRedactionFilter


def test_secret_redaction_filter_masks_known_secret():
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="using key abcdefghij1234567890ABCDEFGHIJ12", args=(), exc_info=None,
    )
    f = SecretRedactionFilter(["abcdefghij1234567890ABCDEFGHIJ12"])
    f.filter(record)
    assert "abcdefghij1234567890ABCDEFGHIJ12" not in record.getMessage()
    assert "<redacted>" in record.getMessage()


def test_secret_redaction_filter_leaves_other_text_alone():
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="signal for BTCUSDT strength=0.42", args=(), exc_info=None,
    )
    f = SecretRedactionFilter(["somesecret1234567890somesecret1"])
    f.filter(record)
    assert record.getMessage() == "signal for BTCUSDT strength=0.42"
