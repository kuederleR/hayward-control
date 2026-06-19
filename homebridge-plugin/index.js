let hap;

module.exports = (api) => {
  hap = api.hap;
  api.registerAccessory('homebridge-hayward-heatpro', 'PoolThermostat', PoolThermostatAccessory);
};

const BACKEND = 'http://localhost:8000';

async function apiGet(path) {
  const res = await fetch(`${BACKEND}${path}`);
  return res.json();
}

async function apiPost(path, body) {
  await fetch(`${BACKEND}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

class PoolThermostatAccessory {
  constructor(log, config) {
    this.log = log;
    this.name = config.name || 'Pool Heater';
  }

  getServices() {
    const info = new hap.Service.AccessoryInformation()
      .setCharacteristic(hap.Characteristic.Manufacturer, 'Hayward')
      .setCharacteristic(hap.Characteristic.Model, 'HeatPro')
      .setCharacteristic(hap.Characteristic.SerialNumber, 'HC-001');

    const thermo = new hap.Service.Thermostat(this.name);

    thermo.getCharacteristic(hap.Characteristic.CurrentTemperature)
      .on('get', this._getCurrentTemp.bind(this));

    thermo.getCharacteristic(hap.Characteristic.TargetTemperature)
      .on('get', this._getTargetTemp.bind(this))
      .on('set', this._setTargetTemp.bind(this));

    thermo.getCharacteristic(hap.Characteristic.CurrentHeatingCoolingState)
      .on('get', this._getCurrentState.bind(this));

    thermo.getCharacteristic(hap.Characteristic.TargetHeatingCoolingState)
      .setProps({ validValues: [0, 1, 3] })
      .on('get', this._getTargetState.bind(this))
      .on('set', this._setTargetState.bind(this));

    return [info, thermo];
  }

  async _getCurrentTemp(callback) {
    try {
      const data = await apiGet('/api/temperature');
      callback(null, data.temperature ?? 0);
    } catch (e) {
      this.log.error('GET temperature failed: %s', e.message);
      callback(e);
    }
  }

  async _getTargetTemp(callback) {
    try {
      const data = await apiGet('/api/thermostat');
      callback(null, data.target_temperature);
    } catch (e) {
      this.log.error('GET target temp failed: %s', e.message);
      callback(e);
    }
  }

  async _setTargetTemp(value, callback) {
    try {
      await apiPost('/api/thermostat', { target_temperature: value });
      callback(null);
    } catch (e) {
      this.log.error('SET target temp failed: %s', e.message);
      callback(e);
    }
  }

  async _getCurrentState(callback) {
    try {
      const data = await apiGet('/api/relay');
      callback(null, data.state ? 1 : 0);
    } catch (e) {
      this.log.error('GET relay failed: %s', e.message);
      callback(e);
    }
  }

  async _getTargetState(callback) {
    try {
      const data = await apiGet('/api/thermostat');
      if (data.enabled) {
        callback(null, 3);
      } else {
        const relay = await apiGet('/api/relay');
        callback(null, relay.state ? 1 : 0);
      }
    } catch (e) {
      this.log.error('GET thermostat failed: %s', e.message);
      callback(e);
    }
  }

  async _setTargetState(value, callback) {
    try {
      switch (value) {
        case 0:
          await apiPost('/api/thermostat', { enabled: false });
          await apiPost('/api/relay', { state: false });
          break;
        case 1:
          await apiPost('/api/thermostat', { enabled: false });
          await apiPost('/api/relay', { state: true });
          break;
        case 3:
          await apiPost('/api/thermostat', { enabled: true });
          break;
      }
      callback(null);
    } catch (e) {
      this.log.error('SET thermostat failed: %s', e.message);
      callback(e);
    }
  }
}
