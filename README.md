# 🇪🇨 MCP Payphone

Servidor Model Context Protocol (MCP) para la integración con **Payphone Ecuador**.

Parte del ecosistema oficial de [MCP Hub Ecuador](https://github.com/mcphub-ec/hub).

> [!IMPORTANT]
> **🤖 Nota para Agentes IA:** Antes de interactuar con este servidor, por favor revisa el [Agent Cheatsheet](https://github.com/mcphub-ec/hub/blob/main/agent-cheatsheet.md) en nuestro Hub principal para comprender las reglas de negocio, cálculo de IVA (15%) y formatos de identificación de Ecuador.

## 🚀 Características

-   Generación de links de pago web.
-   Notificaciones push al celular del usuario (Payphone Sale).
-   Reversos de transacciones automáticos.
-   **Arquitectura Enterprise:** Imágenes Docker ultra-ligeras con _Healthchecks_ nativos, logs estructurados en JSON y validación continua de seguridad.

## 🛠️ Herramientas Disponibles

-   `create_payment_link`: Genera una URL web para que el usuario pague.
-   `create_payphone_sale`: Envía una notificación Push directamente al celular del cliente.
-   `get_transaction_status`: Verifica si el pago fue exitoso o rechazado.
-   `reverse_transaction`: Cancela un pago y devuelve los fondos.

## 📦 Instalación y Configuración

### 1\. Variables de Entorno

Este servidor es completamente _stateless_. Copia el archivo `.env.example` a `.env` y configura tus datos. **Nunca hagas commit de este archivo.**

```env
PAYPHONE_TOKEN="tu_token_bearer_aqui"
```

### 2\. Despliegue con Docker (Recomendado)

Para entornos de producción o pruebas limpias, recomendamos usar nuestra imagen oficial alojada en GitHub Container Registry (`ghcr.io`).

**Vía Docker CLI:**

```bash
docker run -d \
  --name mcp-payphone \
  --env-file .env \
  ghcr.io/mcphub-ec/mcp-payphone:latest
```

**Vía Docker Compose:**

```yaml
services:
  mcp-payphone:
    image: ghcr.io/mcphub-ec/mcp-payphone:latest
    container_name: mcp-payphone
    env_file:
      - .env
    restart: unless-stopped
```

### 3\. Uso con Claude Desktop (Local)

Si deseas conectarlo directamente a tu cliente de Claude para desarrollo local, añade la siguiente configuración a tu archivo `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mcp-payphone": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "--env-file",
        "/ruta/absoluta/a/tu/.env",
        "ghcr.io/mcphub-ec/mcp-payphone:latest"
      ]
    }
  }
}
```

_(Nota: También puedes correrlo directamente con `python -m server` si clonas el repositorio y manejas tu propio entorno virtual)._

## 🔒 Seguridad y Gobernanza

Este proyecto sigue estándares estrictos de seguridad:

-   **Stateless:** No almacena credenciales ni certificados en bases de datos.
-   **Escaneo de Vulnerabilidades:** Cada Pull Request es analizado automáticamente con `bandit` y `detect-secrets`.
-   **Responsible Disclosure:** Si encuentras una vulnerabilidad, por favor no abras un Issue público. Revisa nuestro [SECURITY.md](https://github.com/mcphub-ec/hub/blob/main/SECURITY.md) y contáctanos directamente a `security@mcphub.ec`.

## 🤝 Contribuir

Si deseas proponer mejoras, por favor revisa nuestra [Guía de Contribución](https://github.com/mcphub-ec/hub/blob/main/CONTRIBUTING.md) en el repositorio central. ¡Todos los Pull Requests que pasen los checks de CI/CD son bienvenidos!
