#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/kuederleR/hayward-control.git"
INSTALL_DIR="/home/pi/hayward-control"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}=>${NC} $1"; }
ok()    { echo -e "${GREEN}  OK${NC} $1"; }
warn()  { echo -e "${YELLOW}  !!${NC} $1"; }

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (sudo ./install.sh)" >&2
  exit 1
fi

IS_RPI=false
if grep -qi "raspberry" /proc/cpuinfo 2>/dev/null; then
  IS_RPI=true
else
  warn "Not a Raspberry Pi — skipping hardware steps"
fi

# ── 1-Wire ──────────────────────────────────────────────────────────
CONFIG_FILE=""
if $IS_RPI; then
  for f in /boot/config.txt /boot/firmware/config.txt; do
    [ -f "$f" ] && CONFIG_FILE="$f" && break
  done
  if [ -n "$CONFIG_FILE" ]; then
    if grep -q "^dtoverlay=w1-gpio" "$CONFIG_FILE" 2>/dev/null; then
      ok "1-Wire already enabled in $CONFIG_FILE"
    else
      echo "dtoverlay=w1-gpio" >> "$CONFIG_FILE"
      ok "Added dtoverlay=w1-gpio to $CONFIG_FILE (reboot required)"
    fi
  fi
fi

# ── Docker ──────────────────────────────────────────────────────────
info "Checking Docker"
if command -v docker &>/dev/null; then
  ok "$(docker --version)"
else
  info "Installing Docker"
  curl -fsSL https://get.docker.com | sh
  systemctl enable docker
  ok "Docker installed and enabled on boot"
fi

# Make sure pi user is in docker group
if id pi &>/dev/null; then
  usermod -aG docker pi
fi

info "Checking Docker Compose"
if ! docker compose version &>/dev/null; then
  apt-get update && apt-get install -y docker-compose-plugin
fi
ok "$(docker compose version)"

# ── System packages ─────────────────────────────────────────────────
info "Installing system dependencies"
apt-get update && apt-get install -y --no-install-recommends \
  wireless-tools bluetooth bluez pi-bluetooth python3-pip
ok "System dependencies installed"

# ── Clone / update repo ──────────────────────────────────────────────
if [ -d "$INSTALL_DIR" ]; then
  info "Updating existing installation in $INSTALL_DIR"
  cd "$INSTALL_DIR"
  git pull
else
  info "Cloning repository to $INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi

# ── Environment ─────────────────────────────────────────────────────
if [ -f .env ]; then
  ok ".env exists — keeping existing"
else
  info "Creating .env from .env.example"
  cp .env.example .env
  sed -i 's/^TARGET=.*/TARGET=rpi/' .env
  ok ".env created (edit RELAY_GPIO_PIN if needed)"
fi

# ── Build and launch ────────────────────────────────────────────────
info "Building and starting containers"
docker compose -f docker-compose.yml -f docker-compose.rpi.yml build --pull
docker compose -f docker-compose.yml -f docker-compose.rpi.yml up -d
docker compose -f docker-compose.yml -f docker-compose.rpi.yml restart
ok "Containers are running"

# ── Bluetooth provisioning (optional) ───────────────────────────────
if [ -f provisioning/install.sh ]; then
  echo ""
  echo -e "${YELLOW}------------------------------------------------------------${NC}"
  echo -e "${YELLOW}Bluetooth provisioning lets you change WiFi from your phone${NC}"
  echo -e "${YELLOW}when you cannot reach the Pi over the network.${NC}"
  echo -e "${YELLOW}Install it now?${NC}"
  echo -e "${YELLOW}------------------------------------------------------------${NC}"
  echo -n "Install Bluetooth provisioning? [y/N] "
  read -r ans
  if [[ "$ans" =~ ^[yY] ]]; then
    info "Installing Bluetooth provisioning service"
    (cd provisioning && bash install.sh)
    ok "Bluetooth provisioning installed"
  fi
fi

# ── Summary ──────────────────────────────────────────────────────────
HOSTNAME=$(hostname -I | awk '{print $1}')
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  Hayward HeatPro Control is running!${NC}"
echo -e "${GREEN}${NC}"
echo -e "${GREEN}  Web UI:      http://${HOSTNAME}:8000${NC}"
echo -e "${GREEN}  HomeBridge:  http://${HOSTNAME}:8581${NC}"
echo -e "${GREEN}${NC}"
echo -e "${GREEN}  HomeKit pin: 031-45-154${NC}"
echo -e "${GREEN}${NC}"
echo -e "${GREEN}  View logs:   docker compose logs -f${NC}"
echo -e "${GREEN}  Stop:        docker compose down${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""

if [ -n "$CONFIG_FILE" ] && grep -q "^dtoverlay=w1-gpio" "$CONFIG_FILE" 2>/dev/null; then
  echo -e "${YELLOW}  !! 1-Wire was enabled — reboot required for DS18B20 sensor${NC}"
  echo -e "${YELLOW}     Run: sudo reboot${NC}"
  echo ""
fi
