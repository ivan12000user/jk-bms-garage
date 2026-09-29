import json
import subprocess

CFG_PATH = "/opt/batmon-ha/options.json"

with open(CFG_PATH, "r", encoding="utf-8") as f:
    cfg = json.load(f)

host = cfg["mqtt_broker"]
port = str(cfg.get("mqtt_port", 1883))
user = cfg["mqtt_user"]
password = cfg["mqtt_password"]

object_ids = [
    "garage_jk_bms_soc",
    "garage_jk_bms_total_voltage",
    "garage_jk_bms_current",
    "garage_jk_bms_power",
    "garage_jk_bms_balance_current",
    "garage_jk_bms_capacity",
    "garage_jk_bms_remaining_ah",
    "garage_jk_bms_mos_temp",
    "garage_jk_bms_temp1",
    "garage_jk_bms_temp2",
    "garage_jk_bms_cell1",
    "garage_jk_bms_cell2",
    "garage_jk_bms_cell3",
    "garage_jk_bms_cell4",
    "garage_jk_bms_cell_delta",
    "garage_jk_bms_cell_min",
    "garage_jk_bms_cell_max",
]

for object_id in object_ids:
    topic = f"homeassistant/sensor/{object_id}/config"
    subprocess.run([
        "mosquitto_pub",
        "-h", host,
        "-p", port,
        "-u", user,
        "-P", password,
        "-t", topic,
        "-n",
        "-r"
    ], check=True)
    print("deleted", topic)

print("OK: manual HA discovery removed")
