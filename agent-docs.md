# Agent-First Documentation: Payphone MCP Server (v2.0)

## 1. Contexto General
Servidor MCP para el gateway de pagos Payphone (Ecuador). Implementado con `fastmcp` + `streamable_http_app`.

**Novedad v2.0 — Soporte multi-cuenta:** Cada herramienta acepta `token` y `storeId` como parámetros explícitos, permitiendo al agente alternar entre la cuenta personal y la cuenta de empresa en cualquier llamada, sin depender de variables de entorno fijas.

## 2. Tecnologías Principales
- **FastMCP**: Servidor base con transporte Streamable HTTP (`mcp.streamable_http_app()`).
- **httpx**: Peticiones HTTP asincrónicas.
- **Uvicorn**: Servidor ASGI (default `0.0.0.0:8001`).

## 3. Credenciales por Llamada (MULTI-CUENTA)

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `token`   | str  | ✅ Sí | Bearer token de Payphone. Distintos por cuenta (personal / empresa). |
| `storeId` | str  | ✅ Sí (Sale y Links) | UUID de la tienda asociada al `token`. |

**Regla para el agente:** Antes de llamar cualquier herramienta, confirma con el usuario qué cuenta usar e incluye las credenciales correspondientes en la llamada.

Fallback: si `token` o `storeId` no se proveen (vacío/None), el servidor usa `PAYPHONE_TOKEN` / `PAYPHONE_STORE_ID` del entorno (compatible con despliegues de cuenta única).

## 4. Reglas de Negocio Estrictas

### Montos Monetarios
Todos los parámetros de dinero (`amount`, `amountWithTax`, `amountWithoutTax`, `tax`) **DEBEN** ser enteros en **centavos**.
- $1.15 → `115`. NUNCA enviar flotantes.
- Invariante SIEMPRE requerida: `amountWithTax + amountWithoutTax + tax == amount`

### IVA — Cuándo preguntar
Antes de calcular, pregunta al usuario si el monto **ya incluye IVA** o si el IVA debe agregarse encima.

## 5. Herramientas Disponibles

| Tool | Endpoint | Propósito |
|------|----------|-----------|
| `create_payphone_sale` | POST /Sale | Cobro directo vía app Payphone (push notification) |
| `create_payment_link` | POST /Links | Link de pago web (sin app requerida) |
| `get_transaction_status` | GET /Sale/{id} | Consultar estado de transacción |
| `reverse_transaction` | POST /Reverse | Reverso completo de un cobro aprobado |

## 6. Instrucciones para Edición de Código
- No modificar el flujo de `_payphone_request`; el `RuntimeError` que lanza es legible por el cliente MCP.
- `_resolve_token()` y `_resolve_store_id()` centralizan la lógica de prioridad parámetro → env.
- Mantener siempre el transporte `streamable_http_app` activo.
- Agregar anotaciones de tipo completas a todos los campos de `@mcp.tool()`.
