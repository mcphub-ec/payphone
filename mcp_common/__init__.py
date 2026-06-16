"""
mcp_common — shared helpers for mcphub-ec MCP servers.

This package centralizes security and validation primitives used across
all payment and accounting MCPs. Each MCP server can either:
  (a) install this package via `pip install mcp-common`, or
  (b) vendor a copy locally in its own tree.

The audit and bd issues `mcphub-6bz` and `mcphub-ijk` track the migration
to (a) for production deployments.
"""
from .security import (
    MAX_AMOUNT_USD,
    validate_safe_url,
    validate_amount,
)
from .logging_filter import SensitiveDataFilter

__version__ = "0.1.0"
__all__ = [
    "MAX_AMOUNT_USD",
    "validate_safe_url",
    "validate_amount",
    "SensitiveDataFilter",
]
