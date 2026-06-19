import glob
import logging
import os

from .models import TemperatureReading

logger = logging.getLogger(__name__)

W1_DEVICE_PATH = "/sys/bus/w1/devices"


class TemperatureSensor:

    def __init__(self):
        self._manual_temp: float | None = None

    def _discover_device(self) -> str | None:
        try:
            devices = glob.glob(f"{W1_DEVICE_PATH}/28-*/w1_slave")
            return devices[0] if devices else None
        except Exception:
            return None

    def _read_raw(self, device_path: str) -> tuple[str, str] | None:
        try:
            with open(device_path, "r") as f:
                lines = f.readlines()
            return lines[0].strip(), lines[1].strip()
        except Exception:
            return None

    def read(self, demo_mode: bool = False) -> TemperatureReading:
        if demo_mode and self._manual_temp is not None:
            return TemperatureReading(
                temperature=round(self._manual_temp, 1), connected=True
            )

        device = self._discover_device()
        if device is None:
            if self._manual_temp is not None:
                return TemperatureReading(
                    temperature=round(self._manual_temp, 1), connected=False
                )
            return TemperatureReading(temperature=None, connected=False)

        raw = self._read_raw(device)
        if raw is None:
            return TemperatureReading(temperature=None, connected=False)

        first, second = raw
        if "YES" not in first:
            return TemperatureReading(temperature=None, connected=False)

        try:
            temp_str = second.split("t=")[-1]
            temp_c = float(temp_str) / 1000.0
            return TemperatureReading(temperature=round(temp_c, 1), connected=True)
        except (IndexError, ValueError):
            return TemperatureReading(temperature=None, connected=False)

    def set_manual(self, temp: float):
        self._manual_temp = temp

    def clear_manual(self):
        self._manual_temp = None


sensor = TemperatureSensor()
