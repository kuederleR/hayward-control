import asyncio
import io
import json
import logging
import os
import socket
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
PROVISIONING_SOCKET = Path("/tmp/hayward-provisioning.sock")


def _provisioning_via_socket(ssid: str, password: str) -> dict:
    """Send WiFi credentials to the host provisioning service via Unix socket."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(str(PROVISIONING_SOCKET))
        sock.send(json.dumps({
            "action": "set_wifi", "ssid": ssid, "password": password,
        }).encode())
        resp = sock.recv(4096)
        return json.loads(resp.decode())
    except Exception as e:
        return {"ok": False, "message": str(e)}
    finally:
        sock.close()


def _provisioning_status_via_socket() -> dict:
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(str(PROVISIONING_SOCKET))
        sock.send(json.dumps({"action": "status"}).encode())
        resp = sock.recv(4096)
        return json.loads(resp.decode())
    except Exception:
        return {"connected": None, "ssid": None, "advertising": None,
                "note": "Provisioning service not reachable"}
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _provisioning_save_file(ssid: str, password: str) -> dict:
    """Fallback: save credentials to a file for the host service to pick up."""
    try:
        PROVISIONING_DIR.mkdir(parents=True, exist_ok=True)
        (PROVISIONING_DIR / "wifi_request.json").write_text(json.dumps({
            "ssid": ssid, "password": password,
        }))
        return {"ok": True, "message": "Credentials saved to provisioning directory"}
    except PermissionError:
        return {"ok": False, "message": "Cannot write provisioning directory — install the host provisioning service (see README)"}
    except OSError:
        return {"ok": False, "message": "Provisioning directory not available — install the host provisioning service (see README)"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.get("/api/provisioning/status")
def get_provisioning_status():
    result = _provisioning_status_via_socket()
    # Also note whether we can save requests
    result["request_dir"] = str(PROVISIONING_DIR)
    result["request_dir_writable"] = os.access(str(PROVISIONING_DIR), os.W_OK) if PROVISIONING_DIR.exists() else False
    return result


@app.post("/api/provisioning/wifi")
def set_provisioning_wifi(data: dict):
    ssid = data.get("ssid", "").strip()
    password = data.get("password", "").strip()
    if not ssid:
        return {"ok": False, "message": "SSID is required"}

    # Try Unix socket first (provisioning service running on host)
    result = _provisioning_via_socket(ssid, password)
    if result.get("ok"):
        return result

    # Fallback: save to file for host-side service
    result = _provisioning_save_file(ssid, password)
    return result


def _generate_qr_svg(data: str) -> str:
    factory = qrcode.image.svg.SvgPathImage
    img = qrcode.make(data, image_factory=factory)
    return img.to_string()


def _fetch_homebridge_setup_uri() -> str | None:
    base = "http://localhost:8581"

    # Strategy 1: try without auth (config-ui-x disableLocalAuth may allow it)
    try:
        req = urllib.request.Request(f"{base}/api/status/pairing", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = json.loads(resp.read())
        uri = body.get("setupUri")
        if uri:
            return uri
    except Exception:
        pass

    # Strategy 2: try JWT login with admin/admin
    try:
        login_body = json.dumps({"username": "admin", "password": "admin"}).encode()
        req = urllib.request.Request(
            f"{base}/api/auth/login",
            data=login_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            token = json.loads(resp.read()).get("access_token")
        if token:
            req = urllib.request.Request(
                f"{base}/api/status/pairing",
                headers={"Authorization": f"Bearer {token}"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                body = json.loads(resp.read())
            uri = body.get("setupUri")
            if uri:
                return uri
    except Exception:
        pass

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
