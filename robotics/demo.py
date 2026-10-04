"""
demo.py - shows that the drivers are interchangeable.

The function below only knows about the Sensor contract,
not about any specific driver. Run it with:  python demo.py
"""
from drivers import SimulatedPressureSensor, SimulatedTemperatureSensor
from sensor import Sensor


def take_reading(sensor: Sensor) -> float:
    sensor.connect()
    value = sensor.read()
    sensor.close()
    return value


if __name__ == "__main__":
    for s in [SimulatedTemperatureSensor(), SimulatedPressureSensor()]:
        print(f"{type(s).__name__}: {take_reading(s)}")
