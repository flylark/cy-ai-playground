"""
bus.py - THE MESSAGE BUS CONTRACT and two adapters

Same pattern as sensor.py, applied to messaging:
  MessageBus     -> the contract (publish / subscribe)
  InMemoryBus    -> fast, no network; used by tests and CI
  MqttBus        -> real MQTT broker (needs paho-mqtt)

Topics are levels separated by "/", e.g. "lab/temperature/incubator1".
Subscriptions may use wildcards:
  +  matches exactly one level   ("lab/+/incubator1")
  #  matches all remaining levels ("lab/#")
"""
import threading
from abc import ABC, abstractmethod
from typing import Callable

# A subscriber callback receives (topic, payload)
Callback = Callable[[str, str], None]


def topic_matches(topic_filter: str, topic: str) -> bool:
    """Return True if a topic matches a subscription filter (MQTT rules)."""
    filter_levels = topic_filter.split("/")
    topic_levels = topic.split("/")
    for i, level in enumerate(filter_levels):
        if level == "#":
            return True
        if i >= len(topic_levels):
            return False
        if level != "+" and level != topic_levels[i]:
            return False
    return len(filter_levels) == len(topic_levels)


class MessageBus(ABC):
    @abstractmethod
    def publish(self, topic: str, payload: str) -> None:
        """Send a text payload to a topic."""

    @abstractmethod
    def subscribe(self, topic_filter: str, callback: Callback) -> None:
        """Call callback(topic, payload) for every matching message."""


class InMemoryBus(MessageBus):
    """Delivers messages instantly, inside one program. Great for tests."""

    def __init__(self):
        self._subscriptions = []

    def publish(self, topic: str, payload: str) -> None:
        for topic_filter, callback in self._subscriptions:
            if topic_matches(topic_filter, topic):
                callback(topic, payload)

    def subscribe(self, topic_filter: str, callback: Callback) -> None:
        self._subscriptions.append((topic_filter, callback))


class MqttBus(MessageBus):
    """Talks to a real MQTT broker over the network."""

    def __init__(self, host: str = "localhost", port: int = 1883):
        import paho.mqtt.client as mqtt  # imported here so tests don't need it

        self._subscriptions = []
        self._connected = threading.Event()
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._host, self._port = host, port

    def connect(self, timeout: float = 10) -> None:
        self._client.connect(self._host, self._port)
        self._client.loop_start()  # background thread handles network traffic
        if not self._connected.wait(timeout):
            raise ConnectionError(f"Could not connect to {self._host}:{self._port}")

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def publish(self, topic: str, payload: str) -> None:
        info = self._client.publish(topic, payload, qos=1)  # qos=1: at least once
        info.wait_for_publish(timeout=10)

    def subscribe(self, topic_filter: str, callback: Callback) -> None:
        self._subscriptions.append((topic_filter, callback))
        if self._connected.is_set():
            self._client.subscribe(topic_filter, qos=1)

    # --- called by paho on its background thread ---
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        for topic_filter, _ in self._subscriptions:
            client.subscribe(topic_filter, qos=1)
        self._connected.set()

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8")
        for topic_filter, callback in self._subscriptions:
            if topic_matches(topic_filter, msg.topic):
                callback(msg.topic, payload)
