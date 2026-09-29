import csv
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path


class WebFileSink:
    """
    Local BatMON sink.

    Does NOT open Bluetooth or MQTT connections.
    Receives data directly from BmsSampler and writes:
      state.json
      jk_log.csv
    """

    HISTORY_FIELDS = [
        "ts",
        "time",
        "voltage",
        "current",
        "power",
        "soc",
        "charge",
        "capacity",
        "soh",
        "balance_current",
        "cell1",
        "cell2",
        "cell3",
        "cell4",
        "cell_min",
        "cell_max",
        "cell_delta",
        "temp1",
        "temp2",
        "mos_temperature",
        "uptime",
    ]

    def __init__(self, web_dir, history_hours=72):
        self.web_dir = Path(web_dir)
        self.web_dir.mkdir(parents=True, exist_ok=True)

        self.state_path = self.web_dir / "state.json"
        self.history_path = self.web_dir / "jk_log.csv"

        self.history_hours = float(history_hours)

        self.states = {}
        self.last_history_ts = {}
        self.last_trim = 0

    @staticmethod
    def _finite(value):
        if value is None:
            return None

        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            if isinstance(value, float) and not math.isfinite(value):
                return None
            return value

        return value

    @staticmethod
    def _cell_to_v(value):
        if value is None:
            return None

        try:
            value = float(value)
        except Exception:
            return None

        if not math.isfinite(value):
            return None

        # BatMON fetch_voltages normally supplies mV.
        if abs(value) > 20:
            value /= 1000.0

        return round(value, 4)

    @staticmethod
    def _round(value, digits=3):
        try:
            value = float(value)
        except Exception:
            return None

        if not math.isfinite(value):
            return None

        return round(value, digits)

    def publish_sample(self, bms_name, sample, tags=None):
        temps = list(sample.temperatures or [])

        state = self.states.setdefault(bms_name, {})

        state.update({
            "device": bms_name,
            "timestamp": float(sample.timestamp),
            "updated_at": datetime.fromtimestamp(
                sample.timestamp,
                timezone.utc
            ).isoformat(),

            "voltage": self._round(sample.voltage, 3),
            "current": self._round(sample.current, 3),
            "power": self._round(sample.power, 2),

            "soc": self._round(sample.soc, 2),
            "charge": self._round(sample.charge, 3),
            "capacity": self._round(sample.capacity, 3),
            "soh": self._round(sample.soh, 2),
            "aged_capacity": self._round(
                sample.aged_capacity, 3
            ),

            "balance_current": self._round(
                sample.balance_current, 3
            ),

            "mos_temperature": self._round(
                sample.mos_temperature, 1
            ),

            "temperatures": [
                self._round(x, 1)
                for x in temps
                if self._round(x, 1) is not None
            ],

            "num_cycles": self._round(
                sample.num_cycles, 2
            ),

            "total_charge_throughput": self._round(
                sample.total_charge_throughput, 3
            ),

            "uptime": self._round(
                sample.uptime, 0
            ),

            "problem": sample.problem,
            "problem_code": sample.problem_code,

            "battery_charging":
                sample.battery_charging,

            "battery_mode":
                sample.battery_mode,

            "switches": dict(
                sample.switches or {}
            ),
        })

        self._write_state(bms_name)

    def publish_voltages(
        self,
        bms_name,
        voltages,
        short=False,
        tags=None
    ):
        if not voltages:
            return

        cells = [
            self._cell_to_v(x)
            for x in voltages
        ]

        cells = [
            x for x in cells
            if x is not None
        ]

        if not cells:
            return

        state = self.states.setdefault(
            bms_name, {}
        )

        state["cells"] = cells
        state["cell_min"] = round(
            min(cells), 4
        )
        state["cell_max"] = round(
            max(cells), 4
        )
        state["cell_delta"] = round(
            max(cells) - min(cells), 4
        )
        state["cell_average"] = round(
            sum(cells) / len(cells), 4
        )

        self._write_state(bms_name)
        self._append_history(bms_name)

    def publish_meters(
        self,
        bms_name,
        readings
    ):
        state = self.states.setdefault(
            bms_name, {}
        )

        state["meters"] = {
            str(k): self._round(v, 5)
            for k, v in readings.items()
            if self._round(v, 5) is not None
        }

        self._write_state(bms_name)

    def _write_state(self, bms_name):
        state = self.states.get(bms_name)

        if not state:
            return

        tmp = self.state_path.with_suffix(
            ".json.tmp"
        )

        tmp.write_text(
            json.dumps(
                state,
                ensure_ascii=False,
                indent=2,
                allow_nan=False
            ) + "\n",
            encoding="utf-8"
        )

        os.replace(
            tmp,
            self.state_path
        )

    def _append_history(self, bms_name):
        state = self.states.get(bms_name)

        if not state:
            return

        ts = state.get("timestamp")

        if not ts:
            return

        prev = self.last_history_ts.get(
            bms_name, 0
        )

        if ts <= prev:
            return

        self.last_history_ts[bms_name] = ts

        cells = state.get("cells", [])
        temps = state.get(
            "temperatures", []
        )

        row = {
            "ts": round(ts, 3),
            "time": datetime.fromtimestamp(
                ts,
                timezone.utc
            ).isoformat(),

            "voltage": state.get("voltage"),
            "current": state.get("current"),
            "power": state.get("power"),
            "soc": state.get("soc"),
            "charge": state.get("charge"),
            "capacity": state.get("capacity"),
            "soh": state.get("soh"),
            "balance_current":
                state.get("balance_current"),

            "cell1":
                cells[0] if len(cells) > 0 else "",
            "cell2":
                cells[1] if len(cells) > 1 else "",
            "cell3":
                cells[2] if len(cells) > 2 else "",
            "cell4":
                cells[3] if len(cells) > 3 else "",

            "cell_min":
                state.get("cell_min"),
            "cell_max":
                state.get("cell_max"),
            "cell_delta":
                state.get("cell_delta"),

            "temp1":
                temps[0] if len(temps) > 0 else "",
            "temp2":
                temps[1] if len(temps) > 1 else "",

            "mos_temperature":
                state.get("mos_temperature"),

            "uptime":
                state.get("uptime"),
        }

        new_file = not self.history_path.exists()

        with self.history_path.open(
            "a",
            newline="",
            encoding="utf-8"
        ) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=self.HISTORY_FIELDS
            )

            if new_file:
                writer.writeheader()

            writer.writerow(row)

        now = time.time()

        if now - self.last_trim > 900:
            self.last_trim = now
            self._trim_history()

    def _trim_history(self):
        if not self.history_path.exists():
            return

        cutoff = (
            time.time()
            - self.history_hours * 3600
        )

        tmp = self.history_path.with_suffix(
            ".csv.tmp"
        )

        with self.history_path.open(
            "r",
            newline="",
            encoding="utf-8"
        ) as src, tmp.open(
            "w",
            newline="",
            encoding="utf-8"
        ) as dst:

            reader = csv.DictReader(src)

            writer = csv.DictWriter(
                dst,
                fieldnames=self.HISTORY_FIELDS
            )

            writer.writeheader()

            for row in reader:
                try:
                    ts = float(row["ts"])
                except Exception:
                    continue

                if ts >= cutoff:
                    writer.writerow(row)

        os.replace(
            tmp,
            self.history_path
        )
