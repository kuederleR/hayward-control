from pydantic import BaseModel


class TemperatureReading(BaseModel):
    temperature: float | None
    connected: bool


class RelayCommand(BaseModel):
    state: bool


class ThermostatConfig(BaseModel):
    target_temperature: float | None = None
    enabled: bool | None = None


class StatusResponse(BaseModel):
    temperature: float | None
    sensor_connected: bool
    target_temperature: float
    relay_on: bool
    relay_heating: bool
    auto_mode: bool
    demo_mode: bool


class ManualTemperature(BaseModel):
    temperature: float
