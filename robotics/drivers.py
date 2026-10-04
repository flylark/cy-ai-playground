"""
drivers.py - THE DRIVERS (adapters)

Two simulated drivers. Both follow the same Sensor contract,
so any code that works with one works with the other.
That is what "reusable" means in the job description.
"""
import random

from sensor import Sensor


class SimulatedTemperatureSensor(Sensor):
    """Pretends to be a temperature sensor (degrees C)."""

    def __init__(self):
        self._connected = False

    def connect(self) -> None:
        self._connected = True

    def read(self) -> float:
        if not self._connected:
            raise RuntimeError("Sensor not connected. Call connect() first.")
        return round(random.uniform(20.0, 25.0), 2)

    def close(self) -> None:
        self._connected = False


class SimulatedPressureSensor(Sensor):
    """Pretends to be a pressure sensor (kPa)."""

    def __init__(self):
        self._connected = False

    def connect(self) -> None:
        self._connected = True

    def read(self) -> float:
        if not self._connected:
            raise RuntimeError("Sensor not connected. Call connect() first.")
        return round(random.uniform(100.0, 102.0), 2)

    def close(self) -> None:
        self._connected = False

class SimulatedHumiditySensor(Sensor):
    """Pretends to be a humidity sensor (%)."""

    def __init__(self):
        self._connected = False

    def connect(self) -> None:
        self._connected = True

    def read(self) -> float:
        if not self._connected:
            raise RuntimeError("Sensor not connected. Call connect() first.")
        return round(random.uniform(40.0, 60.0), 2)

    def close(self) -> None:
        self._connected = False
