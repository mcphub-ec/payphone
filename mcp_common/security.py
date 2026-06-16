"""
mcp_common.security
──────────────────
URL validation (anti-SSRF) and monetary amount limits for all MCP servers.

Centralizes:
  - validate_safe_url: blocks private IPs, loopback, link-local, metadata endpoints,
    non-HTTPS schemes — used to validate webhook URLs (responseUrl, notifyUrl, etc.)
  - validate_amount: enforces a maximum per-transaction limit to prevent
    accidental large charges from typos.
  - MAX_AMOUNT_USD: 10,000 USD default cap (overridable via env MCP_MAX_AMOUNT_USD).

Reference: bd issues mcphub-55i (SSRF), mcphub-l4q (amount limit).
"""
from __future__ import annotations

import ipaddress
import os
from typing import Optional
from urllib.parse import urlparse

MAX_AMOUNT_USD: float = float(os.environ.get("MCP_MAX_AMOUNT_USD", "10000"))

# Webhooks MUST be HTTPS to encrypt tokenized payment data in transit.
_ALLOWED_WEBHOOK_SCHEMES = ("https",)

# Block loopback, link-local, cloud metadata endpoints, and well-known private ranges.
_BLOCKED_WEBHOOK_HOSTS = frozenset((
    "localhost",
    "ip6-localhost",
    "ip6-loopback",
    "metadata.google.internal",
    "metadata.azure.com",
    "169.254.169.254",  # AWS / GCP / Azure / DigitalOcean / OpenStack metadata
))


def validate_safe_url(url: Optional[str], field_name: str = "url") -> Optional[str]:
    """Validate that a webhook URL is safe (no SSRF).

    Returns the URL unchanged if safe. Raises ValueError on:
      - non-HTTPS scheme
      - empty hostname
      - loopback / private / link-local / reserved IP
      - well-known metadata hostnames
      - URL parse failure

    A None or empty input returns None (caller can decide whether it's required).
    """
    if url is None or url == "":
        return None
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise ValueError(f"{field_name}: URL inválida ({exc})") from exc
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_WEBHOOK_SCHEMES:
        raise ValueError(
            f"{field_name}: esquema '{scheme}' no permitido. "
            f"Solo se aceptan: {', '.join(_ALLOWED_WEBHOOK_SCHEMES)}"
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError(f"{field_name}: host vacío en la URL")
    if host in _BLOCKED_WEBHOOK_HOSTS:
        raise ValueError(
            f"{field_name}: host '{host}' bloqueado por política anti-SSRF"
        )
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError(
                f"{field_name}: IP '{host}' en rango privado/bloqueado, no permitida"
            )
    except ValueError as exc:
        msg = str(exc)
        if "no permitida" in msg or "bloqueado" in msg or "vacío" in msg:
            raise
        # Not a valid IP literal — must be a public hostname. We don't do DNS
        # resolution here to avoid TOCTOU; production deployments should add
        # a private-IP check at egress (firewall / proxy).
    return url


def validate_amount(amount_usd: float, field_name: str = "monto") -> None:
    """Validate that a monetary amount is positive and within the global cap.

    Raises ValueError on:
      - non-numeric / NaN / infinity
      - amount <= 0
      - amount > MAX_AMOUNT_USD (default 10,000 USD)
    """
    if amount_usd is None:
        raise ValueError(f"{field_name}: monto requerido")
    try:
        v = float(amount_usd)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}: no es un número ({amount_usd!r})") from exc
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError(f"{field_name}: monto no finito")
    if v <= 0:
        raise ValueError(f"{field_name} debe ser > 0. Recibido: {v}")
    if v > MAX_AMOUNT_USD:
        raise ValueError(
            f"{field_name} excede el máximo permitido por transacción: "
            f"${v:.2f} > ${MAX_AMOUNT_USD:.2f}. "
            "Si necesitas procesar montos mayores, configura MCP_MAX_AMOUNT_USD "
            "o contacta al administrador."
        )
