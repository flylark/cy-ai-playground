"""
sensor.py - THE CONTRACT (version 1.0.0)

Every sensor driver MUST provide these three methods.
Think of it like an ICD between subsystems, written in code.

Contract rules:
  1. Call connect() before read().
  2. read() returns one measurement as a float.
  3. read() raises RuntimeError if the sensor is not connected.
  4. close() releases the sensor. It is safe to call more than once.
"""
from abc import ABC, abstractmethod


class Sensor(ABC):
    """Abstract base class: you cannot use it directly, only build drivers from it."""

    @abstractmethod
    def connect(self) -> None:
        """Open the connection to the sensor."""

    @abstractmethod
    def read(self) -> float:
        """Return one measurement."""

    @abstractmethod
    def close(self) -> None:
        """Close the connection."""
