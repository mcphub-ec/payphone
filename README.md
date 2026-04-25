# Payphone MCP Server

Servidor [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) de producción implementado en Python con el SDK `mcp` (FastMCP).  
Expone 4 herramientas para que un agente de IA interactúe con la pasarela de pagos **Payphone** (Ecuador).

---

## Herramientas Expuestas

| # | Tool                      | Endpoint                    | Descripción |
|---|---------------------------|-----------------------------|-------------|
| 1 | `create_payphone_sale`    | `POST /Sale`                | Crear cobro directo — envía notificación push al smartphone del usuario. |
| 2 | `get_transaction_status`  | `GET /Sale/{transactionId}` | Consultar estado de una transacción (Approved / Pending / Rejected / Canceled). |
| 3 | `create_payment_link`     | `POST /Links`               | Generar link de pago web (no requiere app Payphone). |
| 4 | `reverse_transaction`     | `POST /Reverse`             | Reversar una transacción aprobada (monto total). |

> **Regla de negocio**: Todos los montos (`amount`, `amountWithTax`, `amountWithoutTax`, `tax`) se envían como **enteros en centavos**.  
> Ejemplo: `$1.15` → `amount=115`.

---

## Arquitectura

```
┌──────────────┐   Streamable HTTP   ┌─────────────────┐   HTTPS/JSON   ┌────────────────────┐
│  OpenWebUI   │ ──── POST /mcp ──── │ Payphone MCP    │ ──────────────│ pay.payphone...    │
│  u otro LLM  │                     │ Server (:8001)  │               │ /api               │
└──────────────┘                     └─────────────────┘               └────────────────────┘
```

- **Transporte**: Streamable HTTP → `POST/GET/DELETE http://<host>:8001/mcp`
- **Autenticación**: Bearer token vía variable de entorno `PAYPHONE_TOKEN`
- **Referencia OpenAPI**: [`docs/openapiv3.yaml`](docs/openapiv3.yaml)

---

## Despliegue en Linux (Debian / LXC)

### 1. Dependencias del sistema

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv -y
```

### 2. Crear entorno virtual

```bash
cd /root/mcp/payphone
python3 -m venv venv
source venv/bin/activate
```

### 3. Instalar dependencias Python

```bash
pip install "mcp[cli]" httpx python-dotenv uvicorn
```

### 4. Configurar variables de entorno

Crea un archivo `.env` en la raíz del proyecto:

```env
PAYPHONE_TOKEN=tu_token_de_acceso_aqui
# Opcional: Requerido si el token maneja múltiples sucursales
# PAYPHONE_STORE_ID=8dbfxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

> ⚠ **Si `PAYPHONE_TOKEN` no está definido, el servidor NO arrancará.**

### 5. Ejecutar (modo desarrollo)

```bash
python server.py
```

Verás en los logs:
```
Iniciando Payphone MCP Server en http://0.0.0.0:8001/mcp (Streamable HTTP)
```

### 6. Servicio systemd (producción)

```bash
sudo nano /etc/systemd/system/payphone-mcp.service
```

```ini
[Unit]
Description=Payphone MCP Server
After=network.target

[Service]
User=root
WorkingDirectory=/root/mcp/payphone
Environment="PATH=/root/mcp/payphone/venv/bin:$PATH"
ExecStart=/root/mcp/payphone/venv/bin/python server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now payphone-mcp.service
sudo systemctl status payphone-mcp.service
```

---

## Configurar el Cliente (OpenWebUI)

| Campo           | Valor |
|-----------------|-------|
| **Tipo**        | Streamable HTTP |
| **URL**         | `http://<IP>:8001/mcp` |

Asegúrate de que el puerto `8001` no esté bloqueado por el firewall.

---

## Estructura del Proyecto

```
payphone/
├── server.py            # Servidor MCP principal
├── .env                 # Variables de entorno (no versionado)
├── .env.example         # Plantilla de ejemplo
├── .gitignore
├── LICENSE
├── README.md
└── docs/
    └── openapiv3.yaml   # Especificación OpenAPI 3.0
```

---

## Licencia

MIT
# payphone
