"""
mcp_common.logging_filter
─────────────────────────
Logging filter that redacts sensitive parameters (tokens, passwords, IDs)
from log records before they are emitted.

Attach to any logger:

    import logging
    from mcp_common.logging_filter import SensitiveDataFilter

    flt = SensitiveDataFilter()
    logging.getLogger().addFilter(flt)

Or use the ``secure_log`` helper to register it globally in one call.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

# Keys whose values should be redacted wherever they appear in log messages.
DEFAULT_SENSITIVE_KEYS: frozenset[str] = frozenset((
    "token", "access_token", "refresh_token", "id_token",
    "password", "pwd", "pass", "secret",
    "api_key", "apikey", "api-key",
    "bearer", "authorization", "auth",
    "private_key", "private-key", "priv_key",
    "certificate_password", "p12_password",
    "ruc", "cedula", "identification", "identificacion",
    "card", "cvv", "pan",
))

# Regex patterns for inline redaction in free-text log messages.
_PATTERN_TOKEN_BEARER = re.compile(
    r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}", re.IGNORECASE
)
_PATTERN_LONG_HEX = re.compile(r"\b[A-Fa-f0-9]{32,}\b")


class SensitiveDataFilter(logging.Filter):
    """Filter that redacts sensitive values in log records."""

    def __init__(
        self,
        keys: Iterable[str] = DEFAULT_SENSITIVE_KEYS,
        replace_with: str = "***REDACTED***",
    ) -> None:
        super().__init__()
        self._keys = frozenset(k.lower() for k in keys)
        self._replace = replace_with

    def _scrub_message(self, msg: str) -> str:
        if not isinstance(msg, str):
            return msg
        msg = _PATTERN_TOKEN_BEARER.sub(r"\1" + self._replace, msg)
        msg = _PATTERN_LONG_HEX.sub(self._replace, msg)
        return msg

    def _scrub_args(self, args) -> tuple:
        if not args:
            return args
        scrubbed = []
        for a in args:
            if isinstance(a, str):
                scrubbed.append(self._scrub_message(a))
            elif isinstance(a, dict):
                scrubbed.append({
                    k: (self._replace if k.lower() in self._keys else v)
                    for k, v in a.items()
                })
            else:
                scrubbed.append(a)
        return tuple(scrubbed)

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            if isinstance(record.msg, str):
                record.msg = self._scrub_message(record.msg)
            if record.args:
                record.args = self._scrub_args(record.args)
        except Exception:
            # Never raise from a log filter
            pass
        return True


def install(log_level: int = logging.INFO) -> None:
    """Install the global sensitive-data filter on the root logger."""
    root = logging.getLogger()
    if not any(isinstance(f, SensitiveDataFilter) for f in root.filters):
        root.addFilter(SensitiveDataFilter())
    if root.level == logging.NOTSET:
        root.setLevel(log_level)
