# ==============================================================================
# Production Dockerfile for Media Inventory MCP Server
# ==============================================================================
FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MCP_SERVER_HOST=0.0.0.0 \
    MCP_SERVER_PORT=8090

# Install runtime dependencies (curl for container health probes, ca-certificates for AWS SSL).
# gosu drops from root to appuser after the export directory is made writable.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root system user and group
RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -s /bin/bash -m appuser

WORKDIR /app

# Copy dependency definition first to leverage Docker layer caching
COPY requirements.txt .

# Install Python packages
RUN pip install -r requirements.txt

# Copy application source code
COPY mcp_server/ mcp_server/
COPY competitor/ competitor/
COPY exports/ exports/
COPY README.md .

COPY docker/entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Ensure correct permissions for the non-root application user.
# The process starts as root so the entrypoint can chown the bind-mounted
# /app/exports directory, then gosu switches to appuser.
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh \
    && chown -R appuser:appuser /app

# Expose MCP server port
EXPOSE 8090

# Container health probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8090/health || exit 1

# Root entrypoint repairs /app/exports, then runs the server as appuser.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "mcp_server.server:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "2", "--timeout-keep-alive", "65"]
