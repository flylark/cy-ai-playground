"""
test_drivers.py - THE TESTS

These check that every driver honors the contract.
Run them with:  pytest
"""
import pytest

from drivers import SimulatedPressureSensor, SimulatedTemperatureSensor, SimulatedHumiditySensor
from sensor import Sensor

# Each driver and the range its readings should fall in
DRIVERS = [
    (SimulatedTemperatureSensor, 20.0, 25.0),
    (SimulatedPressureSensor, 100.0, 102.0),
    (SimulatedHumiditySensor, 40.0, 60.0),
]


def test_contract_cannot_be_used_directly():
    # The contract itself is not a driver
    with pytest.raises(TypeError):
        Sensor()


@pytest.mark.parametrize("driver_class, low, high", DRIVERS)
def test_reading_is_in_expected_range(driver_class, low, high):
    sensor = driver_class()
    sensor.connect()
    value = sensor.read()
    sensor.close()
    assert low <= value <= high


@pytest.mark.parametrize("driver_class, low, high", DRIVERS)
def test_read_before_connect_raises_error(driver_class, low, high):
    sensor = driver_class()
    with pytest.raises(RuntimeError):
        sensor.read()


@pytest.mark.parametrize("driver_class, low, high", DRIVERS)
def test_read_after_close_raises_error(driver_class, low, high):
    sensor = driver_class()
    sensor.connect()
    sensor.close()
    with pytest.raises(RuntimeError):
        sensor.read()
