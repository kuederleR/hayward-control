#!/usr/bin/env python3
"""
WiFi AP provisioning daemon for Hayward HeatPro.

When WiFi is unavailable or the user triggers a network change from the web UI:
  1. This daemon sets up an access point "Hayward-HeatPro-Setup"
  2. Runs hostapd + dnsmasq (DHCP + DNS redirect for captive portal)
  3. Serves a form on port 80 for entering new WiFi credentials
  4. Saves credentials to wpa_supplicant and restores client mode

Normal mode: listens on a Unix socket for status queries and wifi-set commands.
AP mode: spawned as a subprocess when triggered; returns to normal mode after
the user submits credentials or after a timeout.
"""

import json
import logging
import os
import random
import socket
import subprocess
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote_plus

CONFIG_DIR = Path("/etc/hayward-control")
PROVISIONING_DIR = Path("/data/provisioning")
WPA_FILE = Path("/etc/wpa_supplicant/wpa_supplicant.conf")
WPA_FILE_ALT = Path("/etc/wpa_supplicant/wpa_supplicant-wlan0.conf")

UNIX_SOCKET_PATH = Path("/var/run/hayward/provisioning.sock")
AP_IFACE = "wlan0"
AP_SSID = "Hayward-HeatPro-Setup"
AP_GW = "192.168.4.1"
AP_NETMASK = "255.255.255.0"
AP_DHCP_RANGE = "192.168.4.2,192.168.4.100,255.255.255.0,24h"
HTTP_PORT = 80

HOSTAPD_CONF = Path("/tmp/hayward-hostapd.conf")
DNSMASQ_CONF = Path("/tmp/hayward-dnsmasq.conf")

logger = logging.getLogger("hayward-provisioning")

# ── State ────────────────────────────────────────────────────────────────────

_credentials_received = None  # (ssid, password) set by HTTP server in AP mode
_exit_ap_mode = threading.Event()


# ── WiFi helpers ─────────────────────────────────────────────────────────────

def current_wifi_ssid() -> str | None:
    try:
        r = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def wpa_path() -> Path | None:
    for p in [WPA_FILE, WPA_FILE_ALT]:
        if p.exists():
            return p
    return None


def apply_wifi_config(ssid: str, password: str) -> tuple[bool, str]:
    """Write new credentials and restart wpa_supplicant."""
    try:
        wpa_path().parent.mkdir(parents=True, exist_ok=True)
        psk_line = f'\tpsk="{password}"\n' if password else "\tkey_mgmt=NONE\n"
        wpa_conf = f"""ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US

network={{
\tssid="{ssid}"
{psk_line}}}
"""
        target = wpa_path() or WPA_FILE
        target.write_text(wpa_conf)
        subprocess.run(["wpa_cli", "-i", "wlan0", "reconfigure"], capture_output=True, timeout=10)
        return True, f"WiFi config written to {target}"
    except Exception as e:
        return False, str(e)


# ── AP mode ──────────────────────────────────────────────────────────────────

def _write_hostapd_conf():
    HOSTAPD_CONF.write_text(f"""interface={AP_IFACE}
driver=nl80211
ssid={AP_SSID}
hw_mode=g
channel={random.choice([1, 6, 11])}
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=0
""")


def _write_dnsmasq_conf():
    DNSMASQ_CONF.write_text(f"""interface={AP_IFACE}
dhcp-range={AP_DHCP_RANGE}
dhcp-option=3,{AP_GW}
dhcp-option=6,{AP_GW}
address=/#/{AP_GW}
log-dhcp
""")


CAPTIVE_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Hayward HeatPro — WiFi Setup</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#121212;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh}}
.card{{background:#1e1e1e;border-radius:16px;padding:32px;width:92%;max-width:400px;box-shadow:0 4px 24px rgba(0,0,0,.4)}}
h1{{font-size:1.25rem;margin-bottom:4px;color:#fff}}
.sub{{font-size:.8125rem;color:#888;margin-bottom:20px}}
input{{width:100%;padding:12px 14px;margin-bottom:12px;border:1px solid #333;border-radius:10px;background:#2a2a2a;color:#e0e0e0;font-size:1rem;outline:none}}
input:focus{{border-color:#4a9eff}}
button{{width:100%;padding:14px;background:#4a9eff;color:#fff;border:none;border-radius:10px;font-size:1rem;font-weight:600;cursor:pointer}}
button:active{{opacity:.8}}
.msg{{margin-top:12px;font-size:.875rem;text-align:center;color:#888}}
.msg.ok{{color:#4caf50}}
.msg.err{{color:#ff5252}}
</style>
</head>
<body>
<div class="card">
<h1>Hayward HeatPro</h1>
<p class="sub">Enter your WiFi network to continue</p>
<form id="form" method="post" action="/">
<input type="text" id="ssid" name="ssid" placeholder="WiFi SSID" autocomplete="off" required>
<input type="password" id="password" name="password" placeholder="Password (optional)">
<button type="submit">Connect</button>
</form>
<div id="msg" class="msg"></div>
</div>
<script>
document.getElementById('form').addEventListener('submit',async(e)=>{{
e.preventDefault();const m=document.getElementById('msg');
m.textContent='Connecting...';m.className='msg';
try{{const r=await fetch('/',{{method:'POST',
headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{ssid:e.target.ssid.value,password:e.target.password.value}})}});
const d=await r.json();
if(d.ok){{m.textContent='Connected! The device will restart shortly.';m.className='msg ok'}}
else{{m.textContent=d.message||'Failed';m.className='msg err'}}}}
catch(e){{m.textContent='Error: '+e.message;m.className='msg err'}}}});
</script>
</body>
</html>
"""


class CaptivePortalHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(CAPTIVE_PAGE.encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="replace")

        global _credentials_received
        try:
            data = json.loads(body)
            ssid = data.get("ssid", "").strip()
            password = data.get("password", "")
        except (json.JSONDecodeError, UnicodeDecodeError):
            # HTML form-urlencoded fallback
            params = {}
            for part in body.split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[unquote_plus(k)] = unquote_plus(v)
            ssid = params.get("ssid", "").strip()
            password = params.get("password", "")

        if not ssid:
            self._respond(400, {"ok": False, "message": "SSID is required"})
            return

        ok, msg = apply_wifi_config(ssid, password)
        if ok:
            _credentials_received = (ssid, password)
            self._respond(200, {"ok": True, "message": "Connected! Device will reconnect shortly."})
            _exit_ap_mode.set()
        else:
            self._respond(500, {"ok": False, "message": msg})

    def _respond(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # quiet


def _run_http_server():
    server = HTTPServer(("0.0.0.0", HTTP_PORT), CaptivePortalHandler)
    server.timeout = 1.0
    logger.info("HTTP server listening on %s:%d", AP_GW, HTTP_PORT)
    while not _exit_ap_mode.is_set():
        server.handle_request()
    server.server_close()


def _ap_up():
    """Bring up the access point."""
    logger.info("Starting AP mode: SSID=%s, IP=%s", AP_SSID, AP_GW)

    _write_hostapd_conf()
    _write_dnsmasq_conf()

    # Free wlan0 from wpa_supplicant and set AP mode
    subprocess.run(["systemctl", "stop", "wpa_supplicant"], capture_output=True, timeout=30)
    subprocess.run(["rfkill", "unblock", "wifi"], capture_output=True, timeout=5)
    subprocess.run(["iw", "reg", "set", "US"], capture_output=True, timeout=5)
    subprocess.run(["ip", "link", "set", AP_IFACE, "down"], capture_output=True, timeout=10)
    subprocess.run(["iw", "dev", AP_IFACE, "set", "type", "ap"], capture_output=True, timeout=10)
    subprocess.run(["ip", "addr", "flush", "dev", AP_IFACE], capture_output=True, timeout=10)
    subprocess.run(["ip", "link", "set", AP_IFACE, "up"], capture_output=True, timeout=10)
    subprocess.run(["ip", "addr", "add", f"{AP_GW}/24", "dev", AP_IFACE], capture_output=True, timeout=10)

    time.sleep(1)

    # Start hostapd
    hostapd_proc = subprocess.Popen(
        ["hostapd", str(HOSTAPD_CONF)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )

    # Start dnsmasq
    dnsmasq_proc = subprocess.Popen(
        ["dnsmasq", "-C", str(DNSMASQ_CONF), "--no-daemon", "--bind-dynamic"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )

    # Wait for hostapd to be ready and wlan0 to appear
    for _ in range(10):
        if hostapd_proc.poll() is not None:
            break
        r = subprocess.run(["ip", "link", "show", AP_IFACE], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and "UP" in r.stdout and "LOWER_UP" in r.stdout:
            break
        time.sleep(1)
    else:
        stderr = hostapd_proc.stderr.read().decode() if hostapd_proc.stderr else ""
        logger.error("hostapd did not bring up wlan0:\n%s", stderr[:500])
        raise RuntimeError("hostapd failed to bring up wlan0")

    if hostapd_proc.poll() is not None:
        stderr = hostapd_proc.stderr.read().decode() if hostapd_proc.stderr else ""
        logger.error("hostapd failed to start:\n%s", stderr[:500])
        _ap_down(hostapd_proc, dnsmasq_proc)
        raise RuntimeError(f"hostapd exited with code {hostapd_proc.returncode}")

    # Log interface info for diagnostics
    for cmd in [
        ["iw", "dev", AP_IFACE, "info"],
        ["iw", "dev", AP_IFACE, "link"],
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if r.stdout:
                logger.info("%s:\n%s", " ".join(cmd), r.stdout.strip())
            if r.stderr:
                logger.warning("%s stderr: %s", " ".join(cmd), r.stderr.strip())
        except Exception as e:
            logger.warning("diagnostic cmd failed: %s", e)

    logger.info("AP mode is up")
    return hostapd_proc, dnsmasq_proc


def _ap_down(hostapd_proc, dnsmasq_proc):
    """Tear down the access point."""
    logger.info("Tearing down AP mode")

    for proc in [hostapd_proc, dnsmasq_proc]:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    subprocess.run(["killall", "-9", "hostapd", "dnsmasq"], capture_output=True, timeout=5)

    # Restore wlan0 to managed mode
    subprocess.run(["ip", "link", "set", AP_IFACE, "down"], capture_output=True, timeout=10)
    subprocess.run(["iw", "dev", AP_IFACE, "set", "type", "managed"], capture_output=True, timeout=10)
    subprocess.run(["ip", "addr", "flush", "dev", AP_IFACE], capture_output=True, timeout=10)
    subprocess.run(["ip", "link", "set", AP_IFACE, "up"], capture_output=True, timeout=10)

    # Restart networking
    subprocess.run(["systemctl", "start", "wpa_supplicant"], capture_output=True, timeout=30)
    time.sleep(3)
    subprocess.run(["wpa_cli", "-i", AP_IFACE, "reconfigure"], capture_output=True, timeout=10)
    # Try dhclient, fall back to dhcpcd
    r = subprocess.run(["dhclient", "-v", AP_IFACE], capture_output=True, timeout=30)
    if r.returncode != 0:
        subprocess.run(["dhcpcd", "-n", AP_IFACE], capture_output=True, timeout=30)

    # Clean up temp files
    for f in [HOSTAPD_CONF, DNSMASQ_CONF]:
        try:
            f.unlink()
        except Exception:
            pass


def ap_mode_handler() -> dict:
    """Enter AP mode, block until credentials received or timeout (10 min)."""
    global _credentials_received, _exit_ap_mode
    _credentials_received = None
    _exit_ap_mode.clear()

    _write_status(ap_mode=True, ssid=None)

    try:
        hostapd_proc, dnsmasq_proc = _ap_up()
    except Exception as e:
        logger.error("Failed to start AP mode: %s", e)
        _write_status(ap_mode=False)
        return {"ok": False, "message": f"Failed to start AP mode: {e}"}

    http_thread = threading.Thread(target=_run_http_server, daemon=True)
    http_thread.start()

    # Wait for credentials (up to 10 minutes)
    timeout = 600
    _exit_ap_mode.wait(timeout=timeout)

    _ap_down(hostapd_proc, dnsmasq_proc)

    if _credentials_received:
        return {"ok": True, "ssid": _credentials_received[0], "message": "Credentials received and applied"}

    return {"ok": False, "message": "Timed out waiting for credentials"}


def _write_status(ap_mode: bool = False, ssid: str | None = None):
    """Update status.json for the Docker backend to read."""
    if ssid is None:
        ssid = current_wifi_ssid()
    try:
        PROVISIONING_DIR.mkdir(parents=True, exist_ok=True)
        (PROVISIONING_DIR / "status.json").write_text(json.dumps({
            "connected": ssid is not None,
            "ssid": ssid,
            "ap_mode": ap_mode,
            "ap_ssid": AP_SSID if ap_mode else None,
            "timestamp": time.time(),
        }))
    except Exception:
        pass


# ── File-based watcher (for Docker backend communication) ────────────────────

def _file_watcher():
    """Poll for trigger files from the Docker backend every 2 seconds."""
    while True:
        time.sleep(2)

        # AP mode trigger
        trigger = PROVISIONING_DIR / "trigger_ap.json"
        if trigger.exists():
            try:
                data = json.loads(trigger.read_text())
                trigger.unlink()
                logger.info("AP mode triggered via file")
                result = ap_mode_handler()
                (PROVISIONING_DIR / "ap_result.json").write_text(json.dumps(result))
            except Exception as e:
                logger.error("AP trigger error: %s", e)

        # WiFi config request
        wifi_req = PROVISIONING_DIR / "wifi_request.json"
        if wifi_req.exists():
            try:
                data = json.loads(wifi_req.read_text())
                wifi_req.unlink()
                ok, msg = apply_wifi_config(data.get("ssid", ""), data.get("password", ""))
                (PROVISIONING_DIR / "wifi_result.json").write_text(json.dumps({"ok": ok, "message": msg}))
            except Exception as e:
                logger.error("WiFi request error: %s", e)

        _write_status()


# ── Unix socket handler (normal mode) ────────────────────────────────────────

def _handle_unix_connection(conn):
    try:
        raw = conn.recv(4096)
        payload = json.loads(raw.decode("utf-8").strip())
        action = payload.get("action", "")

        if action == "status":
            ssid = current_wifi_ssid()
            conn.send(json.dumps({
                "connected": ssid is not None,
                "ssid": ssid,
            }).encode())

        elif action == "set_wifi":
            ok, msg = apply_wifi_config(
                payload.get("ssid", ""),
                payload.get("password", ""),
            )
            conn.send(json.dumps({"ok": ok, "message": msg}).encode())

        elif action == "enter_ap_mode":
            conn.send(json.dumps({"ok": True, "message": "Entering AP mode", "ssid": AP_SSID}).encode())
            conn.close()
            result = ap_mode_handler()
            return

        else:
            conn.send(json.dumps({"ok": False, "message": "unknown action"}).encode())

    except Exception as e:
        conn.send(json.dumps({"ok": False, "message": str(e)}).encode())
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run_unix_server():
    if UNIX_SOCKET_PATH.exists():
        UNIX_SOCKET_PATH.unlink()

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(UNIX_SOCKET_PATH))
    sock.listen(5)
    sock.settimeout(10.0)
    os.chmod(str(UNIX_SOCKET_PATH), 0o777)

    while True:
        try:
            conn, _ = sock.accept()
            _handle_unix_connection(conn)
        except socket.timeout:
            continue
        except Exception as e:
            logger.error("Unix socket error: %s", e)
            time.sleep(1)
            continue


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("Hayward HeatPro provisioning daemon starting")

    watcher_thread = threading.Thread(target=_file_watcher, daemon=True)
    watcher_thread.start()

    run_unix_server()


if __name__ == "__main__":
    main()
