#!/usr/bin/env python3

import json
import time
import paho.mqtt.client as mqtt

cfg = json.load(open("/opt/batmon-ha/options.json"))

BASE = "ivan12000/garage/akb"
DEVICE_ID = "akb_garage"

DEVICE = {
    "identifiers": [DEVICE_ID],
    "name": "АКБ гараж",
    "manufacturer": "JK",
    "model": "JK-BD4A8S4P"
}

# uid, name, suffix, unit, device_class, state_class,
# icon, value_template, precision
SENSORS = [
    ("akb_garage_soc",
     "Заряд",
     "soc/soc_percent",
     "%",
     "battery",
     "measurement",
     "mdi:battery",
     "{{ value | float(0) | round(1) }}",
     1),

    ("akb_garage_voltage",
     "Напряжение",
     "soc/total_voltage",
     "V",
     "voltage",
     "measurement",
     "mdi:flash",
     "{{ value | float(0) | round(2) }}",
     2),

    ("akb_garage_current",
     "Ток",
     "soc/current",
     "A",
     "current",
     "measurement",
     "mdi:current-dc",
     "{{ value | float(0) | round(2) }}",
     2),

    ("akb_garage_power",
     "Мощность",
     "soc/power",
     "W",
     "power",
     "measurement",
     "mdi:flash",
     "{{ value | float(0) | round(1) }}",
     1),

    ("akb_garage_balance_current",
     "Балансировка",
     "soc/balance_current",
     "A",
     "current",
     "measurement",
     "mdi:scale-balance",
     "{{ value | float(0) | round(3) }}",
     3),

    ("akb_garage_cell1",
     "Ячейка 1",
     "cell_voltages/1",
     "V",
     "voltage",
     "measurement",
     None,
     "{{ value | float(0) | round(3) }}",
     3),

    ("akb_garage_cell2",
     "Ячейка 2",
     "cell_voltages/2",
     "V",
     "voltage",
     "measurement",
     None,
     "{{ value | float(0) | round(3) }}",
     3),

    ("akb_garage_cell3",
     "Ячейка 3",
     "cell_voltages/3",
     "V",
     "voltage",
     "measurement",
     None,
     "{{ value | float(0) | round(3) }}",
     3),

    ("akb_garage_cell4",
     "Ячейка 4",
     "cell_voltages/4",
     "V",
     "voltage",
     "measurement",
     None,
     "{{ value | float(0) | round(3) }}",
     3),

    ("akb_garage_cell_delta",
     "Разброс",
     "cell_voltages/delta",
     "V",
     "voltage",
     "measurement",
     None,
     "{{ value | float(0) | round(3) }}",
     3),

    ("akb_garage_cell_min",
     "Мин. ячейка",
     "cell_voltages/min",
     "V",
     "voltage",
     "measurement",
     None,
     "{{ value | float(0) | round(3) }}",
     3),

    ("akb_garage_cell_max",
     "Макс. ячейка",
     "cell_voltages/max",
     "V",
     "voltage",
     "measurement",
     None,
     "{{ value | float(0) | round(3) }}",
     3),

    ("akb_garage_temp_bms",
     "Температура BMS",
     "mosfet_status/temperature",
     "°C",
     "temperature",
     "measurement",
     "mdi:thermometer",
     "{{ value | float(0) | round(1) }}",
     1),

    ("akb_garage_temp1",
     "Температура 1",
     "temperatures/1",
     "°C",
     "temperature",
     "measurement",
     "mdi:thermometer",
     "{{ value | float(0) | round(1) }}",
     1),

    ("akb_garage_temp2",
     "Температура 2",
     "temperatures/2",
     "°C",
     "temperature",
     "measurement",
     "mdi:thermometer",
     "{{ value | float(0) | round(1) }}",
     1),

    ("akb_garage_capacity",
     "Ёмкость BMS",
     "soc/capacity",
     "Ah",
     None,
     "measurement",
     "mdi:battery-heart",
     "{{ value | float(0) | round(1) }}",
     1),

    ("akb_garage_remaining",
     "Остаток",
     "mosfet_status/capacity_ah",
     "Ah",
     None,
     "measurement",
     "mdi:battery-clock",
     "{{ value | float(0) | round(2) }}",
     2),

    ("akb_garage_soh",
     "Ресурс",
     "soc/soh",
     "%",
     None,
     "measurement",
     "mdi:battery-heart-variant",
     "{{ value | float(0) | round(1) }}",
     1),

    ("akb_garage_uptime_h",
     "Время работы",
     "bms/uptime",
     "d",
     "duration",
     "measurement",
     "mdi:clock-outline",
     "{{ (value | float(0) / 86400) | round(4) }}",
     4),
]


client = mqtt.Client()
client.username_pw_set(
    cfg["mqtt_user"],
    cfg["mqtt_password"]
)

client.connect(
    cfg["mqtt_broker"],
    int(cfg.get("mqtt_port", 1883)),
    30
)

client.loop_start()

for (
    uid, name, suffix, unit,
    device_class, state_class,
    icon, value_template, precision
) in SENSORS:

    payload = {
        "unique_id": uid,
        "name": name,
        "state_topic": f"{BASE}/{suffix}",
        "device": DEVICE,
        "expire_after": 90,
        "suggested_display_precision": precision,
    }

    if unit:
        payload["unit_of_measurement"] = unit

    if device_class:
        payload["device_class"] = device_class

    if state_class:
        payload["state_class"] = state_class

    if icon:
        payload["icon"] = icon

    if value_template:
        payload["value_template"] = value_template

    topic = f"homeassistant/sensor/{DEVICE_ID}/{uid}/config"

    info = client.publish(
        topic,
        json.dumps(payload, ensure_ascii=False),
        qos=0,
        retain=True
    )

    info.wait_for_publish()

    print(
        f"{uid:28s} <- {BASE}/{suffix}"
    )

time.sleep(1)

client.loop_stop()
client.disconnect()

print("HA discovery published for АКБ гараж")
