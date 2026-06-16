FROM python:3.12-slim

WORKDIR /app

# Copy dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Expose the default MCP port (SSE); the actual port is controlled by MCP_PORT
# at runtime and may be overridden via `docker run -e MCP_PORT=...`.
EXPOSE 8000

# Healthcheck: connect to the TCP port indicated by MCP_PORT env (default 8000).
# This fixes mcphub-kqx/mcphub-qmh where the healthcheck pointed to 8000 but
# the server was actually listening on a different port (8001, 8008, 8009, 8011, 8012).
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import socket, os; s=socket.create_connection(('localhost', int(os.getenv('MCP_PORT', '8000'))), 5); s.close()" || exit 1

# Run the FastMCP server via SSE
CMD ["python", "server.py"]
