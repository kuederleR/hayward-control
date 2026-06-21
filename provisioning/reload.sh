#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Reloading hayward-provisioning service"
sudo cp "$SCRIPT_DIR/provisioning_server.py" /usr/local/bin/hayward-provisioning-server
sudo chmod 755 /usr/local/bin/hayward-provisioning-server
sudo mkdir -p /var/run/hayward
sudo mkdir -p /data/provisioning
sudo cp "$SCRIPT_DIR/hayward-provisioning.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart hayward-provisioning
sudo systemctl status hayward-provisioning --no-pager
