#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Installing Hayward HeatPro Bluetooth provisioning service"

# 1. Copy the provisioning server
echo "  → Installing /usr/local/bin/hayward-provisioning-server"
sudo cp "$SCRIPT_DIR/provisioning_server.py" /usr/local/bin/hayward-provisioning-server
sudo chmod 755 /usr/local/bin/hayward-provisioning-server

# 2. Install systemd service
echo "  → Installing systemd service"
sudo cp "$SCRIPT_DIR/hayward-provisioning.service" /etc/systemd/system/
sudo systemctl daemon-reload

# 3. Enable and start
echo "  → Enabling service"
sudo systemctl enable hayward-provisioning
sudo systemctl restart hayward-provisioning

# 4. Show status
echo ""
echo "==> Service status:"
sudo systemctl status hayward-provisioning --no-pager

echo ""
echo "==> Bluetooth provisioning installed."
echo "  - Pair with 'Hayward-HeatPro' from your phone's Bluetooth settings"
echo "  - Connect with a serial terminal app (channel 1, SPP)"
echo "  - Send: {\"ssid\":\"MyNetwork\",\"password\":\"secret\"}"
echo "  - Or from the terminal: echo '{\"ssid\":\"...\",\"password\":\"...\"}' | sudo tee /dev/rfcomm0"
echo ""
echo "  - View logs: journalctl -u hayward-provisioning -f"
