"""
Payphone MCP Server v2.0.0
──────────────────────────
Model Context Protocol (MCP) server bridging the Payphone payment API (Ecuador).

Transport: Streamable HTTP  →  POST/GET/DELETE  http://<host>:8001/mcp

MULTI-ACCOUNT SUPPORT (v2.0)
  Every tool now accepts `token` and `storeId` as explicit parameters,
  allowing the agent to select the correct Payphone account per request:
    - Personal account  → use the personal token + storeId
    - Company account   → use the company token + storeId
  If not provided, the server falls back to PAYPHONE_TOKEN / PAYPHONE_STORE_ID
  environment variables (useful for single-account deployments).

OpenAPI reference: docs/openapiv3.yaml
"""

import os
import json
import logging
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Optional

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from mcp_common.security import validate_safe_url, validate_amount, MAX_AMOUNT_USD
from mcp_common.logging_filter import install as install_logging_filter

# ─────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s", "level":"%(levelname)s", "name":"%(name)s", "message":"%(message)s"}',
)
logger = logging.getLogger("payphone-mcp")
install_logging_filter()

# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────
load_dotenv()


# ---------------------------------------------------------------------------
# Motor fiscal determinista — IVA Ecuador (Payphone)
# ---------------------------------------------------------------------------
# El LLM NUNCA calcula impuestos. Solo pasa `monto` + `tipo_monto`.
# Este módulo convierte todo a centavos enteros, como exige la API de Payphone.
# ---------------------------------------------------------------------------

class TipoMonto(str, Enum):
    """Indica si el monto dado por el usuario incluye IVA o es la base imponible."""
    SUBTOTAL      = "subtotal"       # el usuario dio la base SIN IVA  (default)
    TOTAL_CON_IVA = "total_con_iva"  # el usuario dio el total CON IVA incluido


_TWO = Decimal("0.01")


def _iva_rate() -> Decimal:
    """Lee IVA_EC_PERCENTAGE del entorno. Fallback: 0.15 (15%)."""
    raw = os.environ.get("IVA_EC_PERCENTAGE", "0.15")
    try:
        rate = Decimal(raw)
        if not (Decimal(0) < rate <= Decimal(1)):
            raise ValueError()
        return rate
    except Exception:
        raise ValueError(
            f"IVA_EC_PERCENTAGE inválido: {raw!r}. "
            "Debe ser un decimal entre 0 y 1, ej. '0.15' para 15%."
        )


def _r2(v: Decimal) -> Decimal:
    """Redondeo estricto a 2 decimales (ROUND_HALF_UP)."""
    return v.quantize(_TWO, rounding=ROUND_HALF_UP)


def _calcular_centavos(monto: float, tipo: TipoMonto) -> tuple[int, int, int]:
    """Calcula (total_cents, subtotal_cents, iva_cents) como enteros.

    Payphone exige TODOS los valores monetarios como enteros en centavos.
    Este método garantiza la invariante de la API:
        total_cents == subtotal_cents + iva_cents

    Args:
        monto: El valor exacto dado por el usuario (en USD).
        tipo:  TipoMonto.SUBTOTAL      → monto es la base sin IVA.
               TipoMonto.TOTAL_CON_IVA → monto es el total ya con IVA.

    Returns:
        (total_cents, subtotal_cents, iva_cents)  — todos int.

    Ejemplos:
        _calcular_centavos(30.0, SUBTOTAL)      → (3450, 3000, 450)
        _calcular_centavos(30.0, TOTAL_CON_IVA) → (3000, 2609, 391)
    """
    if monto <= 0:
        raise ValueError(f"monto debe ser > 0. Recibido: {monto}")
    rate = _iva_rate()
    d = Decimal(str(monto))

    if tipo == TipoMonto.TOTAL_CON_IVA:
        total    = _r2(d)
        subtotal = _r2(d / (1 + rate))
        iva      = _r2(total - subtotal)
    else:  # SUBTOTAL
        subtotal = _r2(d)
        iva      = _r2(d * rate)
        total    = _r2(subtotal + iva)

    def _to_cents(x: Decimal) -> int:
        return int((x * 100).to_integral_value(rounding=ROUND_HALF_UP))

    return _to_cents(total), _to_cents(subtotal), _to_cents(iva)


# ---------------------------------------------------------------------------

BASE_URL = "https://pay.payphonetodoesposible.com/api"
HTTP_TIMEOUT = 30.0

# ─────────────────────────────────────────────────────────────────────
# MCP Server
# ─────────────────────────────────────────────────────────────────────
mcp = FastMCP(
    "Payphone",
    host=os.getenv("MCP_HOST", "0.0.0.0"),  # nosec B104 — configurable via MCP_HOST env
    instructions=(
        "MCP server for Payphone payment gateway (Ecuador). "
        "Credentials are loaded from PAYPHONE_TOKEN / PAYPHONE_STORE_ID env vars. "
        "Provides tools to create direct charges (push notification to Payphone app), "
        "generate shareable payment links, check transaction status, and reverse charges. "
        "MONETARY INPUT RULES (agent must follow strictly): "
        "  · Pass `monto` (float) with the EXACT number the user stated. "
        "  · Pass `tipo_monto`='subtotal' if the user said the amount is WITHOUT VAT (default). "
        "  · Pass `tipo_monto`='total_con_iva' if the user said the amount ALREADY INCLUDES VAT. "
        "  · NEVER calculate subtotals, IVA, or cents yourself — the server does it deterministically. "
        "The IVA rate is read from IVA_EC_PERCENTAGE env var (default 15%)."
    ))


# ─────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────

def _resolve_token(token: Optional[str] = None) -> str:
    """Return the Bearer token to use, preferring the explicit parameter."""
    resolved = (token or os.getenv("PAYPHONE_TOKEN", "")).strip()
    if not resolved:
        raise ValueError(
            "No Payphone token provided. "
            "Pass `token` as a tool parameter or set PAYPHONE_TOKEN in the environment."
        )
    return resolved


# Máximo monto permitido por transacción (en centavos): re-exportado desde mcp_common
MAX_AMOUNT_CENTS = int(MAX_AMOUNT_USD * 100)

# Re-exportar para compatibilidad con código que aún usa _validate_safe_url
def _validate_safe_url(url: Optional[str], field_name: str = "url") -> Optional[str]:
    return validate_safe_url(url, field_name)


def _resolve_store_id(storeId: Optional[str]) -> Optional[str]:
    """Return the storeId to use, preferring the explicit parameter."""
    resolved = storeId or os.getenv("PAYPHONE_STORE_ID", "") or None
    if resolved:
        return resolved
    return None


def _build_headers(token: Optional[str] = None) -> dict[str, str]:
    """Build authorization headers."""
    return {
        "Authorization": f"Bearer {_resolve_token(token)}",
        "Content-Type": "application/json",
    }


async def _payphone_request(
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    token: Optional[str] = None) -> dict:
    """
    Execute an HTTP request against the Payphone API with centralized error handling.
    Returns the JSON response or raises a descriptive RuntimeError for the MCP client.
    """
    url = f"{BASE_URL}{path}"
    logger.info("→ %s %s", method.upper(), url)

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.request(
                method,
                url,
                headers=_build_headers(token),
                json=json_body)
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"Cannot connect to Payphone API ({url}). "
            f"Check network connectivity. Detail: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"Timeout connecting to Payphone API ({url}). "
            f"Request exceeded {HTTP_TIMEOUT}s. Detail: {exc}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Unexpected HTTP error contacting Payphone API: {exc}"
        ) from exc

    if response.status_code >= 400:
        try:
            error_body = response.json()
        except Exception:
            error_body = response.text

        status = response.status_code
        if 400 <= status < 500:
            detail = (
                f"Client error ({status}) calling {path}. "
                f"Payphone API rejected the request. "
                f"Response: {json.dumps(error_body, ensure_ascii=False) if isinstance(error_body, dict) else error_body}"
            )
        else:
            detail = (
                f"Server error ({status}) in Payphone API calling {path}. "
                f"Response: {json.dumps(error_body, ensure_ascii=False) if isinstance(error_body, dict) else error_body}"
            )
        logger.error("← %s %s → %d: %s", method.upper(), url, status, detail)
        raise RuntimeError(detail)

    data = response.json()
    logger.info("← %s %s → %d OK", method.upper(), url, response.status_code)
    return data


# ─────────────────────────────────────────────────────────────────────
# MCP Tools
# ─────────────────────────────────────────────────────────────────────


@mcp.tool()
async def create_payphone_sale(
    phoneNumber: str,
    countryCode: str,
    reference: str,
    monto: float,
    clientTransactionId: str,
    tipo_monto: TipoMonto = TipoMonto.SUBTOTAL,
    storeId: str | None = None,
    token: str | None = None,
    clientUserId: Optional[str] = None,
    responseUrl: Optional[str] = None,
    documentId: Optional[str] = None,
    email: Optional[str] = None,
    terminalId: Optional[str] = None) -> dict:
    """Send a direct charge push notification to a customer's Payphone app — POST /Sale.

    Use this tool when the customer has the Payphone app installed on their phone.
    A push notification will appear on their device to approve the payment.
    Returns the transactionId needed to check payment status later.

    MONETARY INPUT (agent MUST follow this contract):
      monto (float): The EXACT amount the user stated — pass it verbatim, no rounding.
      tipo_monto (enum):
        · "subtotal"      → monto is the taxable base WITHOUT IVA (default).
        · "total_con_iva" → monto is the final price ALREADY INCLUDING IVA.

    ⚠️ DO NOT calculate subtotals, IVA amounts, or convert to cents yourself.
       The server handles all deterministic arithmetic internally.

    All monetary values (amount, amountWithTax, amountWithoutTax, tax) are computed
    by the server from monto+tipo_monto and sent to the Payphone API as integers in
    cents. The invariant amountWithTax + amountWithoutTax + tax == amount is enforced
    by the server, never by the agent.

    REQUIRED PARAMETERS:
      phoneNumber (str): Customer phone number WITHOUT country code. Example: "0999999999"
      countryCode (str): Country calling code. Example: "593" for Ecuador.
      reference (str): Charge description visible to the customer. Example: "Invoice #001"
      monto (float): Amount exactly as stated by the user. Example: 30.0
      clientTransactionId (str): Your unique transaction ID for reconciliation.
                                  Example: "ORD-2025-0042"

    OPTIONAL PARAMETERS:
      tipo_monto (str, default="subtotal"): "subtotal" | "total_con_iva".
      storeId (str): Store UUID (falls back to PAYPHONE_STORE_ID env var).
      clientUserId (str): Your internal customer identifier.
      responseUrl (str): Webhook URL for async payment status notifications.
      documentId (str): Customer cedula / RUC / passport.
      email (str): Customer email address.
      terminalId (str): POS terminal or cashier identifier.

    RETURNS:
      {"transactionId": int}  — Store this ID to poll status with get_transaction_status.
      Example: {"transactionId": 123456789}

    EXAMPLE CALLS:
      # User says "charge $30 + VAT"
      create_payphone_sale(phoneNumber="0999999999", countryCode="593",
                           reference="Invoice #001", monto=30.0, tipo_monto="subtotal",
                           clientTransactionId="ORD-2025-0042")

      # User says "charge $34.50 VAT included"
      create_payphone_sale(phoneNumber="0999999999", countryCode="593",
                           reference="Invoice #001", monto=34.50, tipo_monto="total_con_iva",
                           clientTransactionId="ORD-2025-0042")
    """
    # ── Cálculo determinista (servidor, no el LLM) ──────────────────────────
    validate_amount(monto, "monto")  # raises if > MAX_AMOUNT_USD
    amount_cents, amount_with_tax_cents, tax_cents = _calcular_centavos(monto, tipo_monto)
    amount_without_tax_cents = 0  # base cero = 0 (flujo estándar gravado)

    logger.info(
        "[create_payphone_sale] monto=%.2f tipo=%s → total=%d amountWithTax=%d tax=%d",
        monto, tipo_monto.value, amount_cents, amount_with_tax_cents, tax_cents,
    )

    resolved_store = _resolve_store_id(storeId)

    payload: dict = {
        "phoneNumber":        phoneNumber,
        "countryCode":        countryCode,
        "reference":          reference,
        "amount":             amount_cents,
        "amountWithTax":      amount_with_tax_cents,
        "amountWithoutTax":   amount_without_tax_cents,
        "tax":                tax_cents,
        "clientTransactionId": clientTransactionId,
    }

    if resolved_store:
        payload["storeId"] = resolved_store
    if clientUserId:
        payload["clientUserId"] = clientUserId
    if responseUrl:
        payload["responseUrl"] = _validate_safe_url(responseUrl, "responseUrl")
    if documentId:
        payload["documentId"] = documentId
    if email:
        payload["email"] = email
    if terminalId:
        payload["terminalId"] = terminalId

    # Reusar la sesión HTTP para no recalcular el token (si se proveyó explícito)
    token_value = _resolve_token(token)
    logger.info("[create_payphone_sale] multi-account token used: %s", "yes" if token else "no (env)")
    return await _payphone_request("POST", "/Sale", json_body=payload)


@mcp.tool()
async def get_transaction_status(
    transactionId: int) -> dict:
    """Check the status of a Payphone transaction — GET /Sale/{transactionId}.

    Use this tool to verify whether a payment was approved, rejected, or is
    still pending after creating a sale or payment link.

    REQUIRED PARAMETERS:
      transactionId (int): Numeric transaction ID returned by create_payphone_sale
                           or create_payment_link. Example: 7891234

    RETURNS:
      {"transactionId": int,
       "clientTransactionId": str,
       "transactionStatus": "Approved" | "Canceled" | "Pending" | "Rejected",
       "amount": int,          # total charged in cents
       "currency": str,        # e.g. "USD"
       "authorizationCode": str,  # bank code (if Approved)
       "message": str,
       "date": str,            # ISO datetime
       "documentId": str,
       "phoneNumber": str,
       "email": str,
       "storeId": str,
       "terminalId": str,
       "bin": str,             # first 6 digits of card (if Approved)
       "lastDigits": str,      # last 4 digits of card (if Approved)
       "cardType": str,        # "Credit" | "Debit"
       "cardBrand": str}       # "Visa" | "Mastercard" | ...

    EXAMPLE CALL:
      get_transaction_status(transactionId=7891234)
    """
    return await _payphone_request("GET", f"/Sale/{transactionId}", )



@mcp.tool()
async def create_payment_link(
    monto: float,
    reference: str,
    clientTransactionId: str,
    tipo_monto: TipoMonto = TipoMonto.SUBTOTAL,
    storeId: str | None = None,
    token: str | None = None,
    currency: str = "USD",
    expireIn: Optional[int] = None,
    notifyUrl: Optional[str] = None,
    terminalId: Optional[str] = None,
    documentId: Optional[str] = None,
    email: Optional[str] = None) -> dict:
    """Generate a shareable web payment link — POST /Links.

    Use this tool when the customer does NOT have the Payphone app installed.
    Returns a short URL (e.g. https://payp.hn/x/...) to share via WhatsApp,
    email, or any channel. The customer pays through a browser.

    MONETARY INPUT (agent MUST follow this contract):
      monto (float): The EXACT amount the user stated — pass it verbatim, no rounding.
      tipo_monto (enum):
        · "subtotal"      → monto is the taxable base WITHOUT IVA (default).
        · "total_con_iva" → monto is the final price ALREADY INCLUDING IVA.

    ⚠️ DO NOT calculate subtotals, IVA amounts, or convert to cents yourself.
       The server computes all cent values and enforces the API invariant:
       amountWithTax + amountWithoutTax + tax == amount.

    REQUIRED PARAMETERS:
      monto (float): Amount exactly as stated by the user. Example: 30.0
      reference (str): Charge description. Example: "Monthly subscription"
      clientTransactionId (str): Your unique transaction ID. Example: "LINK-2025-001"

    OPTIONAL PARAMETERS:
      tipo_monto (str, default="subtotal"): "subtotal" | "total_con_iva".
      storeId (str): Store UUID (falls back to PAYPHONE_STORE_ID env var).
      currency (str, default="USD"): Currency code.
      expireIn (int): Link expiration in minutes. Example: 1440 = 24 hours.
      notifyUrl (str): Webhook URL for async payment notifications.
      terminalId (str): POS terminal identifier.
      documentId (str): Customer cedula / RUC / passport.
      email (str): Customer email address.

    RETURNS:
      {"url": str}  — Short payment URL to share with the customer.
      Example: {"url": "https://payp.hn/x/ejemplo123"}
      Share this URL via WhatsApp, email, or SMS. The customer pays in their browser.

    EXAMPLE CALLS:
      # User says "generate a payment link for $30 + VAT"
      create_payment_link(monto=30.0, tipo_monto="subtotal",
                          reference="Invoice #001", clientTransactionId="LINK-001")

      # User says "generate a payment link for $34.50 including VAT"
      create_payment_link(monto=34.50, tipo_monto="total_con_iva",
                          reference="Invoice #001", clientTransactionId="LINK-001")
    """
    # ── Cálculo determinista (servidor, no el LLM) ──────────────────────────
    validate_amount(monto, "monto")  # raises if > MAX_AMOUNT_USD
    amount_cents, amount_with_tax_cents, tax_cents = _calcular_centavos(monto, tipo_monto)
    amount_without_tax_cents = 0  # base cero = 0

    logger.info(
        "[create_payment_link] monto=%.2f tipo=%s → total=%d amountWithTax=%d tax=%d",
        monto, tipo_monto.value, amount_cents, amount_with_tax_cents, tax_cents,
    )

    resolved_store = _resolve_store_id(storeId)

    payload: dict = {
        "amount":             amount_cents,
        "amountWithTax":     amount_with_tax_cents,
        "amountWithoutTax":  amount_without_tax_cents,
        "tax":               tax_cents,
        "reference":         reference,
        "clientTransactionId": clientTransactionId,
        "currency":          currency,
    }

    if expireIn is not None:
        payload["expireIn"] = expireIn
    if notifyUrl:
        payload["notifyUrl"] = _validate_safe_url(notifyUrl, "notifyUrl")
    if resolved_store:
        payload["storeId"] = resolved_store
    if terminalId:
        payload["terminalId"] = terminalId
    if documentId:
        payload["documentId"] = documentId
    if email:
        payload["email"] = email

    return await _payphone_request("POST", "/Links", json_body=payload, token=token)


@mcp.tool()
async def reverse_transaction(
    transactionId: int,
    token: str | None = None,
    verify_status: bool = True) -> dict:
    """⚠️ MUTATION — Reverse (cancel and refund) a previously approved transaction — POST /Reverse.

    Use this tool to cancel a payment and return funds to the customer.
    The reversal is ALWAYS for the FULL amount of the original transaction.
    Partial reversals are not supported by this endpoint.

    By default the server verifies the transaction is in `Approved` state
    before attempting the reversal. Pass `verify_status=False` to skip this
    pre-check (not recommended unless you have already verified externally).

    REQUIRED PARAMETERS:
      transactionId (int): Numeric ID of the approved transaction to reverse.
                           Example: 7891234

    OPTIONAL PARAMETERS:
      token (str): Bearer token for multi-account support. Falls back to PAYPHONE_TOKEN env.
      verify_status (bool, default=True): If True, pre-checks the transaction is Approved.

    RETURNS:
      {"status": "Success",
       "message": str,
       "pre_check": {"transactionStatus": str} | None}  — Confirmation that the reversal was processed.
      Example: {"status": "Success", "message": "Transacción reversada exitosamente"}

    EXAMPLE CALL:
      reverse_transaction(transactionId=7891234)
    """
    pre_check: dict | None = None
    if verify_status:
        try:
            status_resp = await _payphone_request(
                "GET", f"/Sale/{transactionId}", token=token
            )
            pre_check = {
                "transactionId": status_resp.get("transactionId"),
                "transactionStatus": status_resp.get("transactionStatus"),
                "amount": status_resp.get("amount"),
            }
            current_status = (status_resp.get("transactionStatus") or "").lower()
            if current_status != "approved":
                raise ValueError(
                    f"No se puede reversar la transacción {transactionId}: "
                    f"estado actual es '{status_resp.get('transactionStatus')}'. "
                    "Solo se pueden reversar transacciones en estado 'Approved'."
                )
        except ValueError:
            raise
        except Exception as exc:
            # Si el GET falla por red/timeout, fallamos conservadoramente
            raise ValueError(
                f"No se pudo verificar el estado de la transacción {transactionId} antes de reversar: {exc}. "
                "Si confirmas que está Approved, pasa verify_status=False para omitir la verificación."
            ) from exc

    payload = {"transactionId": transactionId}
    result = await _payphone_request("POST", "/Reverse", json_body=payload, token=token)
    if pre_check is not None:
        result["pre_check"] = pre_check
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("MCP_PORT", 8000))
    transport_mode = os.getenv("MCP_TRANSPORT_MODE", "sse").lower()
    print(f"Starting MCP Server on http://0.0.0.0:{port}/mcp ({transport_mode})")
    if transport_mode == "sse":
        app = mcp.sse_app()
    elif transport_mode == "http_stream":
        app = mcp.streamable_http_app()
    else:
        raise ValueError(f"Unknown transport mode: {transport_mode}")
    uvicorn.run(app, host=os.getenv("MCP_HOST", "0.0.0.0"), port=port)  # nosec B104 — configurable via MCP_HOST env
