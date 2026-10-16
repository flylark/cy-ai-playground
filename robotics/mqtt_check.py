"""
mqtt_check.py - diagnose MQTT connection problems

Run:  python mqtt_check.py broker.hivemq.com
      python mqtt_check.py broker.hivemq.com --websockets
"""
import logging
import sys
import time

import paho.mqtt
import paho.mqtt.client as mqtt

host = sys.argv[1] if len(sys.argv) > 1 else "broker.hivemq.com"
use_websockets = "--websockets" in sys.argv
port = 8000 if use_websockets else 1883

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(message)s")
print(f"Python {sys.version.split()[0]}, paho-mqtt {paho.mqtt.__version__}")
print(f"Connecting to {host}:{port} ({'websockets' if use_websockets else 'tcp'})\n")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                     transport="websockets" if use_websockets else "tcp")
if use_websockets:
    client.ws_set_options(path="/mqtt")
client.enable_logger()  # print every step paho takes


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"\n>>> on_connect called, reason: {reason_code}\n")


client.on_connect = on_connect
client.connect(host, port)
client.loop_start()
time.sleep(10)
client.loop_stop()
client.disconnect()
print("Done.")
