"""
pipeline_demo.py - the full pipeline:
  drivers -> schema -> message bus -> database -> SQL queries

Run with real MQTT (public broker):  python pipeline_demo.py
Run with no network:                 python pipeline_demo.py --offline
Readings are saved to lab.db, which you can explore afterwards with:
                                     python -m sqlite3 lab.db
"""
import argparse
import time
import uuid

from bus import InMemoryBus, MqttBus
from drivers import SimulatedHumiditySensor, SimulatedPressureSensor, SimulatedTemperatureSensor
from messaging import publish_reading
from store import ReadingStore

parser = argparse.ArgumentParser()
parser.add_argument("--host", default="test.mosquitto.org")
parser.add_argument("--port", type=int, default=1883)
parser.add_argument("--offline", action="store_true", help="use InMemoryBus")
parser.add_argument("--db", default="lab.db")
parser.add_argument("--rounds", type=int, default=5)
args = parser.parse_args()

root = f"cy-ai-playground/{uuid.uuid4().hex[:6]}/lab"

# Each physical sensor gets its own unique ID
sensors = [
    (SimulatedTemperatureSensor(), "incubator1-temp", "temperature"),
    (SimulatedPressureSensor(), "incubator1-pressure", "pressure"),
    (SimulatedHumiditySensor(), "incubator1-humidity", "humidity")
]
store = ReadingStore(args.db)
bus = InMemoryBus() if args.offline else MqttBus(args.host, args.port)
bus.subscribe(f"{root}/#", store)
if not args.offline:
    bus.connect()

for sensor, _, _ in sensors:
    sensor.connect()
for _ in range(args.rounds):
    for sensor, sensor_id, sensor_type in sensors:
        publish_reading(bus, sensor, sensor_id, sensor_type, root)
    time.sleep(0.2)
for sensor, _, _ in sensors:
    sensor.close()

if not args.offline:
    time.sleep(2)  # let the last messages arrive
    bus.close()

print(f"Saved: {store.saved}   Duplicates: {store.duplicates}   "
      f"Rejected: {len(store.rejected)}\n")

print("Summary per sensor (all runs so far):")
rows = store.query("""
    SELECT s.sensor_id, s.unit, COUNT(*), ROUND(AVG(r.value), 2),
           MIN(r.value), MAX(r.value)
    FROM readings AS r
    JOIN sensors AS s ON s.sensor_id = r.sensor_id
    GROUP BY s.sensor_id
    ORDER BY s.sensor_id
""")
print(f"  {'sensor':<22}{'unit':<6}{'count':>6}{'avg':>9}{'min':>9}{'max':>9}")
for sensor_id, unit, count, avg, low, high in rows:
    print(f"  {sensor_id:<22}{unit:<6}{count:>6}{avg:>9}{low:>9}{high:>9}")

store.close()
