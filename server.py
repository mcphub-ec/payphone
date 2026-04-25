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
from typing import Optional

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# ─────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s", "level":"%(levelname)s", "name":"%(name)s", "message":"%(message)s"}',
)s │ %(levelname)-8s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger("payphone-mcp")

# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────
load_dotenv()


BASE_URL = "https://pay.payphonetodoesposible.com/api"
HTTP_TIMEOUT = 30.0

# ─────────────────────────────────────────────────────────────────────
# MCP Server
# ─────────────────────────────────────────────────────────────────────
mcp = FastMCP(
    "Payphone",
    host="0.0.0.0",
    instructions=(
        "MCP server for Payphone payment gateway (Ecuador). "
        "Credentials are loaded from PAYPHONE_TOKEN / PAYPHONE_STORE_ID env vars. "
        "Provides tools to create direct charges, payment links, check status, and reverse charges. "
        "Provides tools to create direct charges (push notification to Payphone app), "
        "generate shareable payment links, check transaction status, and reverse charges. "
        "CRITICAL — ALL monetary parameters (amount, amountWithTax, amountWithoutTax, tax) "
        "must be integers representing CENTS. Example: $1.15 → amount=115. "
        "The invariant amountWithTax + amountWithoutTax + tax == amount must ALWAYS hold."
    ))


# ─────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────

def _resolve_token() -> str:
    """Return the Bearer token to use, preferring the explicit parameter."""
    resolved = os.getenv("PAYPHONE_TOKEN", "")
    if not resolved:
        raise ValueError(
            "No Payphone token provided. "
            "Pass `token` as a tool parameter or set PAYPHONE_TOKEN in the environment."
        )
    return resolved


def _resolve_store_id(storeId: Optional[str]) -> Optional[str]:
    """Return the storeId to use, preferring the explicit parameter."""
    resolved = storeId or os.getenv("PAYPHONE_STORE_ID", "") or None
    if resolved:
        return resolved
    return None


def _build_headers() -> dict[str, str]:
    """Build authorization headers."""
    return {
        "Authorization": f"Bearer {_resolve_token()}",
        "Content-Type": "application/json",
    }


async def _payphone_request(
    method: str,
    path: str,
    *,
    json_body: dict | None = None) -> dict:
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
                headers=_build_headers(),
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
    amount: int,
    amountWithTax: int,
    amountWithoutTax: int,
    tax: int,
    clientTransactionId: str,    storeId: str,
    clientUserId: Optional[str] = None,
    responseUrl: Optional[str] = None,
    documentId: Optional[str] = None,
    email: Optional[str] = None,
    terminalId: Optional[str] = None) -> dict:
    """Send a direct charge push notification to a customer's Payphone app — POST /Sale.

    Use this tool when the customer has the Payphone app installed on their phone.
    A push notification will appear on their device to approve the payment.
    Returns the transactionId needed to check payment status later.

    ⚠️ CRITICAL — ALL monetary parameters must be integers in CENTS.
    Example: $1.15 → amount=115, amountWithTax=100, tax=15, amountWithoutTax=0.
    The API strictly requires: amountWithTax + amountWithoutTax + tax == amount.
    If this equation does not hold, the transaction will be REJECTED.

    ⚠️ TAX CALCULATION — Always ask the user whether the amount includes VAT
    before calling this tool. Never invent or approximate tax values.

    Use these EXACT formulas (Monto_User is in dollars):

    CASE A: "Base $X WITHOUT VAT, add VAT Y% on top"
      amount           = round((Monto_User * (1 + Y/100)) * 100)
      amountWithTax    = round(Monto_User * 100)
      amountWithoutTax = 0
      tax              = amount - amountWithTax

    CASE B: "Amount $X ALREADY INCLUDES VAT Y%"
      amount           = round(Monto_User * 100)
      amountWithTax    = round(amount / (1 + Y/100))
      amountWithoutTax = 0
      tax              = amount - amountWithTax

    CASE C: "Amount $X with 0% VAT (no VAT applies)"
      amount           = round(Monto_User * 100)
      amountWithTax    = 0
      amountWithoutTax = amount
      tax              = 0

    REQUIRED PARAMETERS:
      storeId (str): Store UUID associated with the token.
      phoneNumber (str): Customer phone number WITHOUT country code. Example: "0999999999"
      countryCode (str): Country calling code. Example: "593" for Ecuador.
      reference (str): Charge description visible to the customer. Example: "Invoice #001"
      amount (int): ⚠️ TOTAL AMOUNT to charge in cents (amountWithTax + amountWithoutTax + tax). Example: 1150 for $11.50
      amountWithTax (int): ⚠️ TAXABLE BASE (Base Imponible / Subtotal 15%) in cents. DO NOT confuse with Total Amount. Example: 1000
      amountWithoutTax (int): ⚠️ ZERO-RATE BASE (Base Cero / Subtotal 0%) in cents. Example: 0
      tax (int): ⚠️ TOTAL VAT AMOUNT (IVA) in cents. Example: 150
      clientTransactionId (str): Your unique transaction ID for reconciliation.
                                  Example: "ORD-2025-0042"

    OPTIONAL PARAMETERS:
      clientUserId (str): Your internal customer identifier.
      responseUrl (str): Webhook URL for async payment status notifications.
      documentId (str): Customer cedula / RUC / passport.
      email (str): Customer email address.
      terminalId (str): POS terminal or cashier identifier.

    RETURNS:
      {"transactionId": int}  — Store this ID to poll status with get_transaction_status.
      Example: {"transactionId": 123456789}

    EXAMPLE CALL:
      create_payphone_sale(
          token="eyJ...", storeId="b3a1...",
          phoneNumber="0999999999", countryCode="593",
          reference="Invoice #001", amount=1150, amountWithTax=1000,
          amountWithoutTax=0, tax=150, clientTransactionId="ORD-2025-0042"
      )
    """
    resolved_store = _resolve_store_id(storeId)

    payload: dict = {
        "phoneNumber": phoneNumber,
        "countryCode": countryCode,
        "reference": reference,
        "amount": amount,
        "amountWithTax": amountWithTax,
        "amountWithoutTax": amountWithoutTax,
        "tax": tax,
        "clientTransactionId": clientTransactionId,
    }

    if resolved_store:
        payload["storeId"] = resolved_store
    if clientUserId:
        payload["clientUserId"] = clientUserId
    if responseUrl:
        payload["responseUrl"] = responseUrl
    if documentId:
        payload["documentId"] = documentId
    if email:
        payload["email"] = email
    if terminalId:
        payload["terminalId"] = terminalId

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
      get_transaction_status(transactionId=7891234, token="eyJ...")
    """
    return await _payphone_request("GET", f"/Sale/{transactionId}", )



@mcp.tool()
async def create_payment_link(
    amount: int,
    amountWithTax: int,
    amountWithoutTax: int,
    tax: int,
    reference: str,
    clientTransactionId: str,    storeId: str,
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

    ⚠️ CRITICAL — ALL monetary parameters must be integers in CENTS.
    Example: $10.00 with no VAT → amount=1000, amountWithoutTax=1000,
    amountWithTax=0, tax=0.
    The API strictly requires: amountWithTax + amountWithoutTax + tax == amount.

    ⚠️ TAX CALCULATION — Always ask the user whether the amount includes VAT
    before calling this tool. Never invent or approximate tax values.

    Use these EXACT formulas (Monto_User is in dollars):

    CASE A: "Base $X WITHOUT VAT, add VAT Y% on top"
      amount           = round((Monto_User * (1 + Y/100)) * 100)
      amountWithTax    = round(Monto_User * 100)
      amountWithoutTax = 0
      tax              = amount - amountWithTax

    CASE B: "Amount $X ALREADY INCLUDES VAT Y%"
      amount           = round(Monto_User * 100)
      amountWithTax    = round(amount / (1 + Y/100))
      amountWithoutTax = 0
      tax              = amount - amountWithTax

    CASE C: "Amount $X with 0% VAT (no VAT applies)"
      amount           = round(Monto_User * 100)
      amountWithTax    = 0
      amountWithoutTax = amount
      tax              = 0

    REQUIRED PARAMETERS:
      storeId (str): Store UUID associated with the token.
      amount (int): ⚠️ TOTAL AMOUNT in cents (amountWithTax + amountWithoutTax + tax). Example: 1150 for $11.50
      amountWithTax (int): ⚠️ TAXABLE BASE (Base Imponible / Subtotal 15%) in cents. DO NOT confuse with Total Amount. Example: 1000
      amountWithoutTax (int): ⚠️ ZERO-RATE BASE (Base Cero / Subtotal 0%) in cents. Example: 0
      tax (int): ⚠️ TOTAL VAT AMOUNT (IVA) in cents. Example: 150
      reference (str): Charge description. Example: "Monthly subscription"
      clientTransactionId (str): Your unique transaction ID. Example: "LINK-2025-001"

    OPTIONAL PARAMETERS:
      currency (str, default="USD"): Currency code. Required by the API.
      expireIn (int): Link expiration in minutes. Example: 1440 = 24 hours.
      notifyUrl (str): Webhook URL for async payment notifications.
      terminalId (str): POS terminal identifier.
      documentId (str): Customer cedula / RUC / passport.
      email (str): Customer email address.

    RETURNS:
      {"url": str}  — Short payment URL to share with the customer.
      Example: {"url": "https://payp.hn/x/ejemplo123"}
      Share this URL via WhatsApp, email, or SMS. The customer pays in their browser.

    EXAMPLE CALL:
      create_payment_link(
          token="eyJ...", storeId="b3a1...",
          amount=1150, amountWithTax=1000, amountWithoutTax=0,
          tax=150, reference="Invoice #001", clientTransactionId="LINK-001"
      )
    """
    resolved_store = _resolve_store_id(storeId)

    payload: dict = {
        "amount": amount,
        "amountWithTax": amountWithTax,
        "amountWithoutTax": amountWithoutTax,
        "tax": tax,
        "reference": reference,
        "clientTransactionId": clientTransactionId,
        "currency": currency,
    }

    if expireIn is not None:
        payload["expireIn"] = expireIn
    if notifyUrl:
        payload["notifyUrl"] = notifyUrl
    if resolved_store:
        payload["storeId"] = resolved_store
    if terminalId:
        payload["terminalId"] = terminalId
    if documentId:
        payload["documentId"] = documentId
    if email:
        payload["email"] = email

    return await _payphone_request("POST", "/Links", json_body=payload)


@mcp.tool()
async def reverse_transaction(
    transactionId: int) -> dict:
    """⚠️ MUTATION — Reverse (cancel and refund) a previously approved transaction — POST /Reverse.

    Use this tool to cancel a payment and return funds to the customer.
    The reversal is ALWAYS for the FULL amount of the original transaction.
    Partial reversals are not supported by this endpoint.

    REQUIRED PARAMETERS:
      transactionId (int): Numeric ID of the approved transaction to reverse.
                           Use get_transaction_status first to confirm the transaction
                           was approved before attempting a reversal.
                           Example: 7891234

    RETURNS:
      {"status": "Success",
       "message": str}  — Confirmation that the reversal was processed.
      Example: {"status": "Success", "message": "Transacción reversada exitosamente"}

    EXAMPLE CALL:
      reverse_transaction(transactionId=7891234, token="eyJ...")
    """
    resolved_token = _resolve_token()
    payload = {"transactionId": transactionId}
    return await _payphone_request("POST", "/Reverse", json_body=payload)


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
    uvicorn.run(app, host="0.0.0.0", port=port)
