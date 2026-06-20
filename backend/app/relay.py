import logging
import os

logger = logging.getLogger(__name__)

RELAY_PIN = int(os.getenv("RELAY_GPIO_PIN", "17"))

try:
    import RPi.GPIO as GPIO

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    RPI_AVAILABLE = True
except (ImportError, RuntimeError):
    RPI_AVAILABLE = False
    logger.warning("RPi.GPIO not available — relay will be simulated")


class RelayController:

    def __init__(self):
        self._pin = RELAY_PIN
        self._state = False

        if RPI_AVAILABLE:
            try:
                GPIO.setup(self._pin, GPIO.OUT, initial=GPIO.HIGH)
                logger.info("Relay initialized on GPIO %s", self._pin)
            except Exception as e:
                logger.error("GPIO setup failed: %s", e)

    @property
    def state(self) -> bool:
        return self._state

    def on(self):
        self._state = True
        if RPI_AVAILABLE:
            GPIO.output(self._pin, GPIO.LOW)
        logger.info("Relay ON")

    def off(self):
        self._state = False
        if RPI_AVAILABLE:
            GPIO.output(self._pin, GPIO.HIGH)
        logger.info("Relay OFF")

    def cleanup(self):
        if RPI_AVAILABLE:
            try:
                GPIO.output(self._pin, GPIO.HIGH)
                GPIO.cleanup(self._pin)
            except Exception:
                pass


relay = RelayController()
