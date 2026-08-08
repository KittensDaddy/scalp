"""Structured logging with secret redaction.

`SCANNER_DASHBOARD_PLAN.md` §M: API keys must never be serialized into logs. This
filter redacts any log record field whose value equals a known secret from
`Settings`, plus a regex fallback for values that look like Binance API
keys/secrets/tokens even if they arrive via an unexpected field.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scalping.config.settings import Settings

_REDACTED = "<redacted>"

# Binance API keys/secrets are 64-char base64url-ish tokens; control/unkill tokens are
# operator-defined but typically similar in shape. Conservative: only touches long
# opaque-looking strings, not short symbols/numbers.
_SECRET_LIKE = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")


class SecretRedactionFilter(logging.Filter):
    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        redacted = msg
        for secret in self._secrets:
            redacted = redacted.replace(secret, _REDACTED)
        redacted = _SECRET_LIKE.sub(
            lambda m: _REDACTED if m.group(0) in self._secrets else m.group(0), redacted
        )
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(settings: Settings, level: int = logging.INFO) -> None:
    secrets = [
        settings.binance_api_key,
        settings.binance_api_secret,
        settings.control_token,
        settings.dashboard_unkill_token,
    ]
    handler = logging.StreamHandler()
    handler.addFilter(SecretRedactionFilter(secrets))
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
