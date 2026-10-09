#!/usr/bin/env bash
set -euo pipefail

# Deployment script for Media Inventory MCP Server on Ubuntu
INSTALL_DIR="/documents/media-inventory/mcp"
SERVICE_NAME="media-inventory-mcp"

echo "=== Deploying Media Inventory MCP Server ==="

# 1. Ensure target directory exists
mkdir -p "${INSTALL_DIR}"

# 2. Copy application files
rsync -av --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.env' ./ "${INSTALL_DIR}/"

# 3. Ensure virtual environment exists
if [ ! -d "${INSTALL_DIR}/.venv" ]; then
    echo "Creating virtual environment..."
    python3.12 -m venv "${INSTALL_DIR}/.venv"
fi

# 4. Install / upgrade dependencies
echo "Installing dependencies..."
"${INSTALL_DIR}/.venv/bin/pip" install --upgrade pip
"${INSTALL_DIR}/.venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

# 5. Check environment file
if [ ! -f "${INSTALL_DIR}/.env" ]; then
    echo "Warning: ${INSTALL_DIR}/.env not found! Creating from example..."
    cp "${INSTALL_DIR}/.env.example" "${INSTALL_DIR}/.env"
    chmod 600 "${INSTALL_DIR}/.env"
    echo "Please edit ${INSTALL_DIR}/.env with production credentials."
fi

# 6. Install systemd service
if [ -d "/etc/systemd/system" ]; then
    echo "Installing systemd service unit..."
    sudo cp "${INSTALL_DIR}/deploy/media-inventory-mcp.service" "/etc/systemd/system/${SERVICE_NAME}.service"
    sudo systemctl daemon-reload
    sudo systemctl enable "${SERVICE_NAME}"
    sudo systemctl restart "${SERVICE_NAME}"
    sudo systemctl status "${SERVICE_NAME}" --no-pager
    echo "=== Service successfully restarted ==="
else
    echo "Warning: /etc/systemd/system not found (non-systemd environment). Skipping daemon reload."
fi
