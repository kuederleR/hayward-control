let hap;

module.exports = (api) => {
  hap = api.hap;
  api.registerAccessory('homebridge-hayward-heatpro', 'PoolHeater', PoolHeaterAccessory);
  api.registerAccessory('homebridge-hayward-heatpro', 'PoolTemperature', PoolTemperatureAccessory);
};

const BACKEND = 'http://localhost:8000';

class PoolHeaterAccessory {
  constructor(log, config) {
    this.log = log;
    this.name = config.name || 'Pool Heater';
  }

  getServices() {
    const info = new hap.Service.AccessoryInformation()
      .setCharacteristic(hap.Characteristic.Manufacturer, 'Hayward')
      .setCharacteristic(hap.Characteristic.Model, 'HeatPro')
      .setCharacteristic(hap.Characteristic.SerialNumber, 'HC-001');

    const sw = new hap.Service.Switch(this.name);
    sw.getCharacteristic(hap.Characteristic.On)
      .on('get', this._get.bind(this))
      .on('set', this._set.bind(this));

    return [info, sw];
  }

  async _get(callback) {
    try {
      const res = await fetch(`${BACKEND}/api/relay`);
      const data = await res.json();
      callback(null, data.state);
    } catch (e) {
      this.log.error('GET relay failed: %s', e.message);
      callback(e);
    }
  }

  async _set(value, callback) {
    try {
      await fetch(`${BACKEND}/api/relay`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ state: value }),
      });
      callback(null);
    } catch (e) {
      this.log.error('SET relay failed: %s', e.message);
      callback(e);
    }
  }
}

class PoolTemperatureAccessory {
  constructor(log, config) {
    this.log = log;
    this.name = config.name || 'Pool Temperature';
  }

  getServices() {
    const info = new hap.Service.AccessoryInformation()
      .setCharacteristic(hap.Characteristic.Manufacturer, 'Hayward')
      .setCharacteristic(hap.Characteristic.Model, 'HeatPro')
      .setCharacteristic(hap.Characteristic.SerialNumber, 'HC-002');

    const temp = new hap.Service.TemperatureSensor(this.name);
    temp.getCharacteristic(hap.Characteristic.CurrentTemperature)
      .on('get', this._get.bind(this));

    return [info, temp];
  }

  async _get(callback) {
    try {
      const res = await fetch(`${BACKEND}/api/temperature`);
      const data = await res.json();
      callback(null, data.temperature);
    } catch (e) {
      this.log.error('GET temperature failed: %s', e.message);
      callback(e);
    }
  }
}
