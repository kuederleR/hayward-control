#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Installing Hayward HeatPro Bluetooth provisioning service"

# 0. Install Bluetooth packages if missing
echo "  → Installing Bluetooth packages"
sudo apt-get update -qq && sudo apt-get install -y --no-install-recommends \
  bluez bluez-tools rfkill
echo "  → Ensuring pi user is in bluetooth group"
sudo usermod -aG bluetooth pi

# 1. Copy the provisioning server
echo "  → Installing /usr/local/bin/hayward-provisioning-server"
sudo cp "$SCRIPT_DIR/provisioning_server.py" /usr/local/bin/hayward-provisioning-server
sudo chmod 755 /usr/local/bin/hayward-provisioning-server

# 2. Install systemd service
echo "  → Installing systemd service"
sudo cp "$SCRIPT_DIR/hayward-provisioning.service" /etc/systemd/system/
sudo systemctl daemon-reload

# 3. Enable and start
echo "  → Enabling and starting service"
sudo systemctl enable hayward-provisioning
sudo systemctl restart hayward-provisioning

# 4. Show status
echo ""
echo "==> Service status:"
sudo systemctl status hayward-provisioning --no-pager

echo ""
echo "==> Bluetooth provisioning installed."
echo "  - Look for 'Hayward-HeatPro' in your phone's Bluetooth settings"
echo "  - Pair from your phone's Bluetooth settings"
echo "  - Connect with a serial terminal app (channel 1, SPP)"
echo "  - Send: {\"ssid\":\"MyNetwork\",\"password\":\"secret\"}"
echo ""
echo "  - View logs: journalctl -u hayward-provisioning -f"
echo "  - Check adapter: hciconfig -a"
