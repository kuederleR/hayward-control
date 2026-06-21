#!/usr/bin/env python3
"""
Bluetooth provisioning server for Hayward HeatPro.

Listens for WiFi credentials over Bluetooth RFCOMM (Serial Port Profile).
Connecting from a phone:
  1. Pair with "Hayward-HeatPro" via Bluetooth settings
  2. Use a serial terminal app (e.g. "Serial Bluetooth Terminal" on Android,
     "Bluetooth Serial" on iOS) to connect
  3. Send: {"ssid":"MyNetwork","password":"secret"}
  4. The Pi saves the credentials, reconnects WiFi, and responds with OK/ERR

Also provides a Unix socket for the Docker backend to query status and
trigger provisioning locally.

Run directly:  sudo python3 provisioning_server.py [--foreground]
Install as service: see install.sh
"""

import json
import logging
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("provisioning")

# ── paths ──────────────────────────────────────────────────────────────────
WPA_CONF = Path("/etc/wpa_supplicant/wpa_supplicant.conf")
WPA_CONF_BACKUP = Path("/etc/wpa_supplicant/wpa_supplicant.conf.bak")
NETWORK_RESTART_CMD = ["wpa_cli", "-i", "wlan0", "reconfigure"]
ALT_RESTART_CMD = ["systemctl", "restart", "networking"]

RFCOMM_CHANNEL = 1
UNIX_SOCKET_PATH = Path("/tmp/hayward-provisioning.sock")

# State
_current_wifi: dict | None = None
_bt_advertised_name: str = "Hayward-HeatPro"


# ── helpers ────────────────────────────────────────────────────────────────

def _wpa_escape(s: str) -> str:
    """Escape a string for wpa_supplicant.conf."""
    return s.replace('\\', '\\\\').replace('"', '\\"')


def _read_wpa_conf() -> str:
    if WPA_CONF.exists():
        return WPA_CONF.read_text()
    return ""


def _write_wpa_conf(content: str):
    if WPA_CONF.exists():
        WPA_CONF.rename(WPA_CONF_BACKUP)
    WPA_CONF.write_text(content)


def _restart_networking() -> bool:
    try:
        r = subprocess.run(NETWORK_RESTART_CMD, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return True
    except Exception:
        pass
    try:
        r = subprocess.run(ALT_RESTART_CMD, capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception as e:
        logger.error("Failed to restart networking: %s", e)
        return False


# ── WiFi management ────────────────────────────────────────────────────────

def current_wifi_ssid() -> str | None:
    """Return the SSID of the currently connected WiFi network, or None."""
    try:
        r = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or None
    except Exception:
        return None


def apply_wifi_config(ssid: str, password: str) -> tuple[bool, str]:
    """Add or update a network block in wpa_supplicant.conf and reconnect."""
    if not ssid:
        return False, "SSID is required"

    escaped_ssid = _wpa_escape(ssid)
    escaped_pass = _wpa_escape(password)

    # Build the new network block
    new_block = f'network={{\n\tssid="{escaped_ssid}"\n\tpsk="{escaped_pass}"\n}}\n'

    old_config = _read_wpa_conf()

    # If the config already has network blocks, add the new one at the top
    # Otherwise create a minimal config
    if old_config.strip():
        # Remove any existing block for the same SSID
        lines = old_config.splitlines(keepends=True)
        filtered = []
        in_block = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("network="):
                in_block = True
                filtered.append(line)
            elif in_block:
                if stripped == "}":
                    in_block = False
                filtered.append(line)
            else:
                filtered.append(line)
        # If we stripped lines, that section is gone; rebuild
        content = old_config.rstrip() + "\n\n" + new_block
    else:
        content = (
            'ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\n'
            'update_config=1\n'
            'country=US\n\n'
            + new_block
        )

    try:
        _write_wpa_conf(content)
    except PermissionError:
        return False, "Permission denied writing wpa_supplicant.conf (run as root)"

    ok = _restart_networking()
    if ok:
        global _current_wifi
        _current_wifi = {"ssid": ssid, "password": password}
        return True, "WiFi config applied, reconnecting…"
    else:
        return False, "Config saved but network restart failed"


# ── Bluetooth RFCOMM server ────────────────────────────────────────────────

_bt_agent_process = None


def _bt_agent_cleanup():
    global _bt_agent_process
    if _bt_agent_process is not None:
        _bt_agent_process.terminate()
        try:
            _bt_agent_process.wait(timeout=3)
        except Exception:
            _bt_agent_process.kill()
        _bt_agent_process = None


def _bt_init():
    """Initialize Bluetooth adapter for iOS-compatible SPP."""
    global _bt_agent_process

    # Load kernel module and power on Bluetooth adapter
    subprocess.run(["modprobe", "rfcomm"], capture_output=True, timeout=5)
    subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True, timeout=10)

    # Set HCI-level page/inquiry scan (hciconfig) + BlueZ-level config (bluetoothctl)
    for cmd in [
        ["hciconfig", "hci0", "piscan"],
    ]:
        try:
            subprocess.run(cmd, capture_output=True, timeout=10)
        except Exception:
            pass

    # bluetoothctl is interactive — pipe all commands in one shot
    btctl_cmds = (
        "power on\n"
        "discoverable on\n"
        "pairable on\n"
        f"system-alias {_bt_advertised_name}\n"
        "quit\n"
    )
    try:
        subprocess.run(["bluetoothctl"], input=btctl_cmds, capture_output=True,
                       text=True, timeout=15)
    except Exception as e:
        logger.warning("bluetoothctl init failed: %s", e)

    # Start bt-agent as persistent pairing handler (keeps agent registered on D-Bus)
    if _bt_agent_process is None or _bt_agent_process.poll() is not None:
        try:
            _bt_agent_process = subprocess.Popen(
                ["bt-agent", "-c", "NoInputNoOutput"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            logger.info("bt-agent started (pid %d)", _bt_agent_process.pid)
        except FileNotFoundError:
            logger.warning("bt-agent not found (install bluez-tools)")
        except Exception as e:
            logger.warning("bt-agent failed to start: %s", e)

    # Register SPP SDP record so serial terminal apps can discover it
    _register_spp_sdp()


def _register_spp_sdp():
    """Register SPP SDP record so serial terminal apps discover the device."""
    for attempt in range(3):
        try:
            r = subprocess.run(
                ["sdptool", "add", f"--channel={RFCOMM_CHANNEL}", "SP"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                break
            logger.warning("sdptool attempt %d: %s", attempt + 1, r.stderr.strip() or r.stdout.strip())
        except Exception as e:
            logger.warning("sdptool attempt %d error: %s", attempt + 1, e)
        time.sleep(1)

    try:
        r = subprocess.run(["sdptool", "browse", "local"], capture_output=True,
                           text=True, timeout=10)
        if r.returncode == 0:
            if "Serial Port" in r.stdout:
                logger.info("SPP SDP record verified")
            else:
                logger.warning("SPP record NOT found in SDP browse:\n%s",
                               r.stdout[:500])
    except Exception as e:
        logger.warning("SDP browse failed: %s", e)


def _bt_periodic_refresh():
    """Refresh discoverable/pairable state and SDP record every 30 seconds."""
    while True:
        time.sleep(30)
        try:
            subprocess.run(["hciconfig", "hci0", "piscan"],
                           capture_output=True, timeout=10)
        except Exception:
            pass
        for cmd in ("discoverable on\n", "pairable on\n"):
            try:
                subprocess.run(["bluetoothctl"], input=cmd,
                               capture_output=True, text=True, timeout=10)
            except Exception:
                pass
        _register_spp_sdp()


def _bt_addr():
    """Get local Bluetooth adapter MAC as 6-byte binary (or BDADDR_ANY)."""
    try:
        addr_str = Path("/sys/class/bluetooth/hci0/address").read_text().strip()
        if addr_str:
            return bytes.fromhex(addr_str.replace(":", ""))
    except Exception:
        pass
    try:
        r = subprocess.run(["hciconfig", "hci0"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if "BD Address" in line:
                return bytes.fromhex(line.split()[-1].replace(":", ""))
    except Exception:
        pass
    return b"\x00\x00\x00\x00\x00\x00"  # BDADDR_ANY


def run_bt_server():
    """Run the Bluetooth RFCOMM server."""
    _bt_init()

    addr = _bt_addr()

    # Retry loop: rfcomm module or bluetoothd might not be ready
    sock = None
    for attempt in range(10):
        try:
            sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                                  socket.BTPROTO_RFCOMM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((addr, RFCOMM_CHANNEL))
            break
        except OSError as e:
            logger.warning("bind attempt %d failed: %s", attempt + 1, e)
            if sock is not None:
                sock.close()
                sock = None
            if attempt == 0:
                subprocess.run(["modprobe", "rfcomm"], capture_output=True, timeout=5)
            time.sleep(2)
    if sock is None:
        logger.error("Could not bind RFCOMM socket after 10 attempts")
        return
    sock.listen(1)
    sock.settimeout(30.0)

    logger.info("Bluetooth RFCOMM server listening on channel %d as '%s'",
                RFCOMM_CHANNEL, _bt_advertised_name)

    while True:
        try:
            client, addr = sock.accept()
            client.settimeout(15.0)
            logger.info("Connection from %s", addr)

            try:
                data = client.recv(4096)
                if not data:
                    client.close()
                    continue

                payload = data.decode("utf-8", errors="replace").strip()
                logger.info("Received: %s", payload[:200])

                # Try JSON
                parsed = json.loads(payload)
                ssid = parsed.get("ssid", "")
                password = parsed.get("password", "")
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Try simple format: WIFI:SSID:PASSWORD
                if payload.startswith("WIFI:"):
                    parts = payload.split(":", 2)
                    if len(parts) == 3:
                        ssid, password = parts[1], parts[2]
                    else:
                        client.send(b"ERR: invalid format (use WIFI:ssid:password)\n")
                        client.close()
                        continue
                else:
                    client.send(b"ERR: send JSON {\"ssid\":\"...\",\"password\":\"...\"}\n")
                    client.close()
                    continue
            except Exception as e:
                client.send(f"ERR: {e}\n".encode())
                client.close()
                continue

            ok, msg = apply_wifi_config(ssid, password)
            response = "OK" if ok else f"ERR: {msg}"
            client.send(f"{response}\n".encode())
            logger.info("Response: %s", response)
            client.close()

        except socket.timeout:
            continue
        except OSError as e:
            logger.error("Socket error: %s", e)
            time.sleep(2)
            continue
        except Exception as e:
            logger.error("Unexpected error: %s", e)
            time.sleep(2)
            continue


# ── Unix socket (for backend communication) ────────────────────────────────

def _handle_unix_connection(conn):
    try:
        data = conn.recv(4096)
        payload = json.loads(data.decode("utf-8").strip())
        action = payload.get("action", "")
        if action == "status":
            ssid = current_wifi_ssid()
            conn.send(json.dumps({
                "connected": ssid is not None,
                "ssid": ssid,
                "advertising": _bt_advertised_name,
            }).encode())
        elif action == "set_wifi":
            ok, msg = apply_wifi_config(
                payload.get("ssid", ""),
                payload.get("password", ""),
            )
            conn.send(json.dumps({"ok": ok, "message": msg}).encode())
        else:
            conn.send(json.dumps({"ok": False, "message": "unknown action"}).encode())
    except Exception as e:
        conn.send(json.dumps({"ok": False, "message": str(e)}).encode())
    finally:
        conn.close()


def run_unix_server():
    """Run a Unix socket server for backend communication."""
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


# ── entry point ────────────────────────────────────────────────────────────

def main():
    import atexit
    import threading

    atexit.register(_bt_agent_cleanup)

    # Start Unix socket server in background
    unix_thread = threading.Thread(target=run_unix_server, daemon=True)
    unix_thread.start()

    # Periodic Bluetooth state refresher
    refresh_thread = threading.Thread(target=_bt_periodic_refresh, daemon=True)
    refresh_thread.start()

    # Start Bluetooth server (blocking)
    run_bt_server()


if __name__ == "__main__":
    main()
