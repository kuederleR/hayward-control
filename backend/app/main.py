import asyncio
import io
import json
import logging
import os
import socket
import subprocess
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

import qrcode
import qrcode.image.svg
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

from .models import ManualTemperature, RelayCommand, StatusResponse, ThermostatConfig
from .relay import relay
from .temperature import sensor

logger = logging.getLogger(__name__)

target_temperature: float = 28.0
auto_mode: bool = False
demo_mode: bool = os.getenv("DEMO_MODE", "false").strip().lower() == "true"
heating_active: bool = False


async def thermostat_loop():
    global auto_mode, heating_active
    while True:
        try:
            if auto_mode:
                reading = sensor.read(demo_mode)
                if reading.temperature is not None:
                    if reading.temperature < target_temperature - 0.5:
                        if not relay.state:
                            relay.on()
                        heating_active = True
                    elif reading.temperature >= target_temperature:
                        if relay.state:
                            relay.off()
                        heating_active = False
            else:
                heating_active = relay.state
        except Exception as e:
            logger.error("Thermostat error: %s", e)
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(thermostat_loop())
    yield
    relay.cleanup()


app = FastAPI(title="Hayward HeatPro Control", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(html_path) as f:
        return HTMLResponse(f.read())


@app.get("/api/status", response_model=StatusResponse)
def get_status():
    temp = sensor.read(demo_mode)
    return StatusResponse(
        temperature=temp.temperature,
        sensor_connected=temp.connected,
        target_temperature=target_temperature,
        relay_on=relay.state,
        relay_heating=relay.state,
        auto_mode=auto_mode,
        demo_mode=demo_mode,
    )


@app.get("/api/temperature")
def get_temperature():
    temp = sensor.read(demo_mode)
    return {"temperature": temp.temperature, "humidity": None, "connected": temp.connected}


@app.get("/api/relay")
def get_relay():
    return {"state": relay.state}


@app.post("/api/relay")
def set_relay(cmd: RelayCommand):
    global auto_mode
    if cmd.state:
        relay.on()
    else:
        relay.off()
    auto_mode = False
    return {"state": relay.state}


@app.get("/api/relay/on")
@app.post("/api/relay/on")
def relay_on():
    global auto_mode
    relay.on()
    auto_mode = False
    return PlainTextResponse("OK")


@app.get("/api/relay/off")
@app.post("/api/relay/off")
def relay_off():
    global auto_mode
    relay.off()
    auto_mode = False
    return PlainTextResponse("OK")


@app.get("/api/thermostat")
def get_thermostat():
    return {
        "target_temperature": target_temperature,
        "enabled": auto_mode,
        "heating": relay.state if auto_mode else False,
    }


@app.post("/api/thermostat")
def set_thermostat(config: ThermostatConfig):
    global target_temperature, auto_mode
    if config.target_temperature is not None:
        target_temperature = config.target_temperature
    if config.enabled is not None:
        auto_mode = config.enabled
    return {
        "target_temperature": target_temperature,
        "enabled": auto_mode,
    }


@app.post("/api/thermostat/toggle")
def toggle_thermostat():
    global auto_mode
    auto_mode = not auto_mode
    if not auto_mode:
        relay.off()
    return {"enabled": auto_mode}


@app.get("/api/mode")
def get_mode():
    return {"demo": demo_mode}


@app.post("/api/mode")
def set_mode(data: dict):
    global demo_mode
    demo_mode = data.get("demo", False)
    if demo_mode:
        relay.off()
    return {"demo": demo_mode}


@app.post("/api/temperature/manual")
def set_manual_temperature(data: ManualTemperature):
    sensor.set_manual(data.temperature)
    return {"temperature": data.temperature}


HOMEBRIDGE_CONFIG = {
    "name": "Hayward HeatPro",
    "pin": "031-45-154",
    "username": "CC:22:3D:E3:CE:30",
}

# ── provisioning ───────────────────────────────────────────────────────────

PROVISIONING_DIR = Path(os.getenv("PROVISIONING_DIR", "/data/provisioning"))


def _read_provisioning_status() -> dict | None:
    """Read status from the daemon's status.json file."""
    try:
        f = PROVISIONING_DIR / "status.json"
        if f.exists():
            return json.loads(f.read_text())
    except Exception:
        pass
    return None


def _host_wifi_status() -> dict:
    ssid = None
    try:
        result = subprocess.run(
            ["iwgetid", "-r"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            ssid = result.stdout.strip()
    except Exception:
        pass
    return {"ssid": ssid, "connected": ssid is not None}


def _write_trigger_file(name: str, data: dict) -> dict:
    """Write a trigger file for the host provisioning daemon."""
    try:
        PROVISIONING_DIR.mkdir(parents=True, exist_ok=True)
        (PROVISIONING_DIR / name).write_text(json.dumps(data))
        return {"ok": True, "message": f"Trigger '{name}' written"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.get("/api/provisioning/status")
def get_provisioning_status():
    result = _read_provisioning_status()
    if result is None:
        result = _host_wifi_status()
    result.setdefault("ap_ssid", "Hayward-HeatPro-Setup")
    return result


@app.post("/api/provisioning/trigger")
def trigger_ap_mode():
    """Trigger AP mode on the host provisioning daemon."""
    return _write_trigger_file("trigger_ap.json", {"triggered": True})


@app.post("/api/provisioning/wifi")
def set_provisioning_wifi(data: dict):
    ssid = data.get("ssid", "").strip()
    password = data.get("password", "").strip()
    if not ssid:
        return {"ok": False, "message": "SSID is required"}
    return _write_trigger_file("wifi_request.json", {"ssid": ssid, "password": password})


def _generate_qr_svg(data: str) -> str:
    factory = qrcode.image.svg.SvgPathImage
    img = qrcode.make(data, image_factory=factory)
    return img.to_string()


def _generate_setup_code(pincode: str, category: int, setup_id: str) -> str:
    value_low = int(pincode.replace("-", "")) | (1 << 28)
    value_high = category >> 1

    if category & 1:
        value_low |= 1 << 31

    combined = (value_high << 32) | value_low
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if combined == 0:
        encoded = "0"
    else:
        parts = []
        n = combined
        while n:
            parts.append(alphabet[n % 36])
            n //= 36
        encoded = "".join(reversed(parts))
    encoded = encoded.zfill(9)
    return f"X-HM://{encoded}{setup_id}"


def _read_accessory_info() -> dict | None:
    accessory_id = HOMEBRIDGE_CONFIG["username"].replace(":", "").upper()
    candidates = [
        f"/homebridge/persist/AccessoryInfo.{accessory_id}.json",
        f"/var/lib/homebridge/persist/AccessoryInfo.{accessory_id}.json",
    ]
    for path in candidates:
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, PermissionError):
            continue
        except Exception as e:
            logger.warning("failed to read %s: %s", path, e)
    return None


def _fetch_setup_code_via_api() -> str | None:
    base = "http://localhost:8581"
    try:
        req = urllib.request.Request(f"{base}/api/server/pairing", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = json.loads(resp.read())
        return body.get("setupCode")
    except Exception:
        return None


def _fetch_homebridge_setup_uri() -> str | None:
    info = _read_accessory_info()
    if info:
        try:
            uri = _generate_setup_code(info["pincode"], info["category"], info["setupID"])
            logger.info("read setup code from AccessoryInfo file")
            return uri
        except Exception as e:
            logger.warning("failed to generate setup code from file: %s", e)

    uri = _fetch_setup_code_via_api()
    if uri:
        return uri

    return None


@app.get("/api/homekit/setup")
def get_homekit_setup():
    config = HOMEBRIDGE_CONFIG
    setup_uri = _fetch_homebridge_setup_uri()
    qr_data = setup_uri or config["pin"]
    qr_svg = _generate_qr_svg(qr_data)
    return {
        "name": config["name"],
        "pin": config["pin"],
        "username": config["username"],
        "setupUri": setup_uri,
        "qrSvg": qr_svg,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
