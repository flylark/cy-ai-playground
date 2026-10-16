"""
mqtt_demo.py - send readings through a REAL MQTT broker

Default broker is test.mosquitto.org: free and public, no install needed.
It is PUBLIC, so anyone can see these messages. Only send fake data.

Run:            python mqtt_demo.py
Local broker:   python mqtt_demo.py --host localhost
"""
import argparse
import time
import uuid

from bus import MqttBus
from drivers import SimulatedHumiditySensor, SimulatedPressureSensor, SimulatedTemperatureSensor
from messaging import ReadingCollector, publish_reading

parser = argparse.ArgumentParser()
parser.add_argument("--host", default="test.mosquitto.org")
parser.add_argument("--port", type=int, default=1883)
args = parser.parse_args()

# A unique topic root so we don't mix with other people on the public broker
root = f"cy-ai-playground/{uuid.uuid4().hex[:6]}/lab"

sensors = [
    (SimulatedTemperatureSensor(), "incubator1", "temperature"),
    (SimulatedPressureSensor(), "incubator1", "pressure"),
    (SimulatedHumiditySensor(), "incubator1", "humidity"),
]

bus = MqttBus(args.host, args.port)
collector = ReadingCollector()
bus.subscribe(f"{root}/#", collector)       # subscriber: listen to everything
bus.connect()
print(f"Connected to {args.host}. Topic root: {root}")

for sensor, _, _ in sensors:
    sensor.connect()

for round_number in range(3):               # publisher: 3 rounds of readings
    for sensor, sensor_id, sensor_type in sensors:
        r = publish_reading(bus, sensor, sensor_id, sensor_type, root)
        print(f"  sent     {sensor_type:<12} {r.value} {r.unit}")
    time.sleep(1)

bus.publish(f"{root}/temperature/broken", "this is not a valid reading")
time.sleep(2)                               # give messages time to arrive

for sensor, _, _ in sensors:
    sensor.close()
bus.close()

print(f"\nReceived and valid: {len(collector.accepted)}")
print(f"Rejected:           {len(collector.rejected)}")
for topic, payload, _ in collector.rejected:
    print(f"  rejected on {topic}: {payload!r}")
