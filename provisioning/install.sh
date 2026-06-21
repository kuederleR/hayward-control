#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Installing Hayward HeatPro WiFi AP provisioning service"

# 0. Install packages
echo "  → Installing hostapd and dnsmasq"
sudo apt-get update -qq && sudo apt-get install -y --no-install-recommends \
  hostapd dnsmasq wireless-tools
sudo systemctl stop hostapd dnsmasq 2>/dev/null || true
sudo systemctl disable hostapd dnsmasq 2>/dev/null || true

# 1. Create shared directories
echo "  → Creating /var/run/hayward and /data/provisioning"
sudo mkdir -p /var/run/hayward /data/provisioning
sudo chmod 755 /var/run/hayward /data/provisioning

# 2. Copy the provisioning server
echo "  → Installing /usr/local/bin/hayward-provisioning-server"
sudo cp "$SCRIPT_DIR/provisioning_server.py" /usr/local/bin/hayward-provisioning-server
sudo chmod 755 /usr/local/bin/hayward-provisioning-server

# 3. Install systemd service
echo "  → Installing systemd service"
sudo cp "$SCRIPT_DIR/hayward-provisioning.service" /etc/systemd/system/
sudo systemctl daemon-reload

# 4. Enable and start
echo "  → Enabling and starting service"
sudo systemctl enable hayward-provisioning
sudo systemctl restart hayward-provisioning

# 5. Show status
echo ""
echo "==> Service status:"
sudo systemctl status hayward-provisioning --no-pager

echo ""
echo "==> WiFi AP provisioning installed."
echo "  - Look for 'Hayward-HeatPro-Setup' in your phone's WiFi list"
echo "  - Connect to it, then open http://192.168.4.1"
echo "  - Enter your WiFi credentials and submit"
echo ""
echo "  - View logs: journalctl -u hayward-provisioning -f"
