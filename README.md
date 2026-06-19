# Hayward HeatPro Control

Dockerized pool heater controller for Raspberry Pi Zero 2W with wireless
control, HomeKit integration, and a mobile-friendly web interface. Also runs
on any Docker host for development and testing.

## Features

- **Web UI** — Modern, mobile-friendly dashboard for temperature monitoring and
  heater control (FastAPI + vanilla JS)
- **HomeKit** — HomeBridge container exposes temperature sensor and heater switch
  for iOS widgets, Siri, and Home automations
- **Thermostat** — Set a target temperature; auto-mode cycles the relay to
  maintain it (0.5&deg;C hysteresis)
- **Temperature probe** — Reads a DS18B20 digital sensor over 1-Wire; gracefully
  reports when not connected
- **Demo mode** — Actuates the relay in software and allows manual temperature
  entry for testing without physical hardware
- **Docker Compose** — Two containers orchestrated together: backend + HomeBridge
- **Cross-platform** — Same compose file works on Mac, Linux, and RPi; RPi
  overlay adds hardware support

## Hardware Requirements

| Item | Notes |
|------|-------|
| Raspberry Pi Zero 2W | Runs Raspberry Pi OS Lite (64-bit recommended) |
| DS18B20 temperature sensor | Waterproof probe, 4.7 k&Omega; pull-up resistor on data line |
| 5 V relay module | Active low or high — set via wiring |
| Jumper wires | For GPIO, 1-Wire, and relay connections |
| 5 V power supply | Sufficient for Pi + relay |

### Wiring

```
DS18B20              Pi Zero 2W
───────              ──────────
VDD (red)       →    3.3 V (pin 1)
GND (black)     →    GND (pin 6)
DATA (yellow)   →    GPIO 4 (pin 7) — with 4.7 kΩ pull-up to 3.3 V

Relay Module         Pi Zero 2W
────────────         ──────────
VCC             →    5 V (pin 2 or 4)
GND             →    GND (pin 6)
IN              →    GPIO 17 (pin 11) — configurable via RELAY_GPIO_PIN
```

### Enable 1-Wire

Add to `/boot/config.txt` (or `/boot/firmware/config.txt` on newer images) and
reboot:

```ini
dtoverlay=w1-gpio
```

Verify the sensor is detected:

```bash
ls /sys/bus/w1/devices/
# Should show a 28-xxxxxxxxxxxx directory
```

## Quick Start

### Prerequisites

- Docker Engine 24+
- Docker Compose plugin (v2.20+)

### 1. Clone and configure

```bash
git clone <this-repo> /home/pi/hayward-control
cd /home/pi/hayward-control
cp .env.example .env
```

Edit `.env` to match your environment:

```env
RELAY_GPIO_PIN=17
DEMO_MODE=false
TARGET=rpi          # "rpi" for Raspberry Pi, "dev" for laptop testing
```

### 2. Launch

**On Raspberry Pi** — includes GPIO and 1-Wire support:

```bash
docker compose -f docker-compose.yml -f docker-compose.rpi.yml up -d
```

**On a laptop / development machine** — no hardware required:

```bash
docker compose up -d
```

The backend auto-detects the missing hardware and falls back to simulated GPIO
and sensor. Set `DEMO_MODE=true` in `.env` or toggle it in the web UI to enable
manual temperature input.

### 3. Access

| Service | URL |
|---------|-----|
| Web UI | http://&lt;host&gt;:8000 |
| HomeBridge admin | http://&lt;host&gt;:8581 (default: `admin` / `admin`) |

### 4. Pair with HomeKit

Open the Home app on your iOS device &rarr; Add Accessory &rarr; scan the QR
code shown in the HomeBridge logs:

```bash
docker compose logs homebridge | grep "QR Code"
```

Or enter the setup code **031-45-154** manually.

### 5. Stop

```bash
docker compose down
```

## Usage

### Web App

- **Pool Temperature** — displayed at the top; shows &ldquo;Not
  Connected&rdquo; when the DS18B20 is absent
- **Thermostat** — tap +/− to set the target temperature; enable Auto Mode to
  let the system cycle the heater automatically
- **Heater** — manual override toggle; disables Auto Mode when toggled
- **Developer Options** — Demo Mode actuates the relay in software and reveals a
  manual temperature input for testing

### HomeKit

Two accessories are exposed via HomeBridge:

| Accessory | Type | Purpose |
|-----------|------|---------|
| Pool Temperature | Temperature sensor | Read-only current temperature |
| Pool Heater | Switch | Turn heating on/off |

Use them in widgets, scenes, and automations (e.g., &ldquo;If Pool Temperature
drops below 24&deg;C, turn on Pool Heater&rdquo;).

## Development

### Run the backend locally

GPIO is auto-mocked when `RPi.GPIO` is unavailable, so the backend runs on any
OS without hardware:

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 in your browser.

### Demo mode

Toggle Demo Mode in the web UI's Developer Options panel, or set
`DEMO_MODE=true` in `.env` before starting. This enables:

- Software-only relay actuation (GPIO pins are never touched)
- Manual temperature input field for simulating sensor readings

### RPi overlay

The file `docker-compose.rpi.yml` provides the RPi-specific configuration:

- `privileged: true` — required for GPIO and 1-Wire access
- `/sys/bus/w1` and `/sys/devices/w1_bus_master1` mounts — DS18B20 sensor

Without this overlay, the backend starts in a limited mode: no GPIO access, no
1-Wire, and the sensor reads as &ldquo;Not Connected&rdquo;.

## Project Structure

```
hayward-control/
├── docker-compose.yml           # Base orchestration (any platform)
├── docker-compose.rpi.yml       # RPi overlay (privileged + 1-Wire mounts)
├── .env                         # Runtime configuration
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py              # FastAPI routes + thermostat logic
│       ├── models.py            # Pydantic schemas
│       ├── temperature.py       # DS18B20 reader (auto mock fallback)
│       ├── relay.py             # GPIO relay controller (auto mock fallback)
│       └── templates/
│           └── index.html       # Web UI (inline CSS/JS, dark mode)
├── homebridge/
│   ├── Dockerfile
│   └── config.json              # HomeBridge accessories config
└── README.md
```

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/status` | Full system state |
| `GET` | `/api/temperature` | Current temperature + sensor status |
| `GET` | `/api/relay` | Relay state |
| `POST` | `/api/relay` | Set relay on/off (body: `{"state": bool}`) |
| `POST` | `/api/relay/on` | Turn relay on |
| `POST` | `/api/relay/off` | Turn relay off |
| `GET` | `/api/thermostat` | Thermostat config |
| `POST` | `/api/thermostat` | Set target temp / auto mode |
| `POST` | `/api/thermostat/toggle` | Toggle auto mode |
| `GET` | `/api/mode` | Demo mode status |
| `POST` | `/api/mode` | Set demo mode |
| `POST` | `/api/temperature/manual` | Set manual temperature input |

All POST bodies are JSON. The `/api/relay/on` and `/api/relay/off` endpoints
return plain text for HomeBridge compatibility.

## License

MIT
