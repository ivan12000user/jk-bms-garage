import asyncio
import time
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
HEADER = bytes.fromhex("55 AA EB 90")

rx = bytearray()
frames = {}


def request_frame(cmd):
    f = bytearray(20)
    f[0:4] = bytes.fromhex("AA 55 90 EB")
    f[4] = cmd
    f[19] = sum(f[:19]) & 0xff
    return bytes(f)


def notify(sender, data):
    global rx

    rx.extend(data)

    while True:
        p = rx.find(HEADER)

        if p < 0:
            if len(rx) > 3:
                del rx[:-3]
            return

        if p:
            del rx[:p]

        if len(rx) < 300:
            return

        f = bytes(rx[:300])
        del rx[:300]

        if (sum(f[:299]) & 0xff) != f[299]:
            continue

        typ = f[4]

        if typ in (1, 2, 3):
            frames[typ] = f


def u16(f, o):
    return int.from_bytes(f[o:o+2], "little")


def s16(f, o):
    return int.from_bytes(f[o:o+2], "little", signed=True)


def u32(f, o):
    return int.from_bytes(f[o:o+4], "little")


def s32(f, o):
    return int.from_bytes(f[o:o+4], "little", signed=True)


def i8(f, o):
    return int.from_bytes(f[o:o+1], "little", signed=True)


def asc(f, o, n):
    return (
        f[o:o+n]
        .split(b"\x00")[0]
        .decode("ascii", errors="replace")
        .strip()
    )


def yn(v):
    return "ON" if v else "OFF"


def runtime_string(sec):
    days, sec = divmod(sec, 86400)
    hours, sec = divmod(sec, 3600)
    mins, sec = divmod(sec, 60)

    return (
        f"{days}d {hours:02d}:"
        f"{mins:02d}:{sec:02d}"
    )


def hexblock(f, a, b):
    return " ".join(
        f"{x:02X}" for x in f[a:b]
    )


def title(s):
    print()
    print("=" * 72)
    print(s)
    print("=" * 72)


ERROR_NAMES = {
    0:  "Charge over-temperature",
    1:  "Charge under-temperature",
    2:  "Coprocessor communication",
    3:  "Cell undervoltage",
    4:  "Battery undervoltage",
    5:  "Discharge overcurrent",
    6:  "Discharge short circuit",
    7:  "Discharge over-temperature",
    8:  "Wire resistance abnormal",
    9:  "MOS over-temperature",
    10: "Cell count mismatch",
    11: "Current sensor abnormal",
    12: "Cell overvoltage",
    13: "Battery overvoltage",
    14: "Charge overcurrent",
    15: "Charge short circuit",
}


CONTROL_BITS = {
    0: "Heating",
    1: "Disable temperature sensors",
    2: "GPS heartbeat",
    3: "Multiplexed port RS485/CAN",
    4: "Display always on",
    5: "Special charger mode",
    6: "Smart Sleep",
    7: "Disable PCL",
    8: "Timed stored data",
    9: "Float mode",
}


def decode_settings(f):
    title("SETTINGS / CONFIGURATION  (frame 0x01)")

    print(f"Frame counter                  : {f[5]}")

    print()
    print("--- CELL VOLTAGE / SOC ---")

    vals = {}

    def volt(name, o):
        v = u32(f, o) / 1000
        vals[name] = v
        print(f"{name:31s}: {v:7.3f} V")
        return v

    vals["smart_sleep"] = volt(
        "Smart Sleep voltage", 6
    )
    vals["uvp"] = volt(
        "Cell UVP", 10
    )
    vals["uvpr"] = volt(
        "Cell UVP recovery", 14
    )
    vals["ovp"] = volt(
        "Cell OVP", 18
    )
    vals["ovpr"] = volt(
        "Cell OVP recovery", 22
    )
    vals["balance_delta"] = volt(
        "Balance trigger delta", 26
    )
    vals["soc100"] = volt(
        "SOC 100% voltage", 30
    )
    vals["soc0"] = volt(
        "SOC 0% voltage", 34
    )
    vals["rcv"] = volt(
        "RCV", 38
    )
    vals["rfv"] = volt(
        "RFV", 42
    )
    vals["poweroff"] = volt(
        "Power Off voltage", 46
    )

    print()
    print("--- CURRENT / PROTECTION ---")

    vals["max_charge"] = u32(f, 50) / 1000
    vals["charge_ocp_delay"] = u32(f, 54)
    vals["charge_ocp_recovery"] = u32(f, 58)
    vals["max_discharge"] = u32(f, 62) / 1000
    vals["discharge_ocp_delay"] = u32(f, 66)
    vals["discharge_ocp_recovery"] = u32(f, 70)
    vals["short_recovery"] = u32(f, 74)
    vals["max_balance"] = u32(f, 78) / 1000

    print(
        f"{'Max charge current':31s}: "
        f"{vals['max_charge']:.3f} A"
    )
    print(
        f"{'Charge OCP delay':31s}: "
        f"{vals['charge_ocp_delay']} s"
    )
    print(
        f"{'Charge OCP recovery':31s}: "
        f"{vals['charge_ocp_recovery']} s"
    )
    print(
        f"{'Max discharge current':31s}: "
        f"{vals['max_discharge']:.3f} A"
    )
    print(
        f"{'Discharge OCP delay':31s}: "
        f"{vals['discharge_ocp_delay']} s"
    )
    print(
        f"{'Discharge OCP recovery':31s}: "
        f"{vals['discharge_ocp_recovery']} s"
    )
    print(
        f"{'Short circuit recovery':31s}: "
        f"{vals['short_recovery']} s"
    )
    print(
        f"{'Max balance current':31s}: "
        f"{vals['max_balance']:.3f} A"
    )

    print()
    print("--- TEMPERATURE PROTECTION ---")

    temp_fields = [
        ("Charge OTP",            82, False),
        ("Charge OTP recovery",   86, False),
        ("Discharge OTP",         90, False),
        ("Discharge OTP recovery",94, False),
        ("Charge UTP",            98, True),
        ("Charge UTP recovery",  102, True),
        ("MOS OTP",              106, True),
        ("MOS OTP recovery",     110, True),
    ]

    for name, o, signed in temp_fields:
        raw = s32(f, o) if signed else u32(f, o)
        value = raw / 10
        vals[name] = value

        print(
            f"{name:31s}: "
            f"{value:7.1f} °C"
        )

    print()
    print("--- BATTERY / SWITCHES ---")

    vals["cell_count"] = u32(f, 114)
    vals["charge_switch"] = u32(f, 118)
    vals["discharge_switch"] = u32(f, 122)
    vals["balance_switch"] = u32(f, 126)
    vals["capacity"] = u32(f, 130) / 1000
    vals["scp_delay_us"] = u32(f, 134)
    vals["balance_start"] = u32(f, 138) / 1000

    print(
        f"{'Cell count':31s}: "
        f"{vals['cell_count']}"
    )
    print(
        f"{'Charge switch':31s}: "
        f"{yn(vals['charge_switch'])}"
    )
    print(
        f"{'Discharge switch':31s}: "
        f"{yn(vals['discharge_switch'])}"
    )
    print(
        f"{'Balancer switch':31s}: "
        f"{yn(vals['balance_switch'])}"
    )
    print(
        f"{'Configured capacity':31s}: "
        f"{vals['capacity']:.3f} Ah"
    )
    print(
        f"{'Short circuit delay':31s}: "
        f"{vals['scp_delay_us']} us"
    )
    print(
        f"{'Balance start voltage':31s}: "
        f"{vals['balance_start']:.3f} V"
    )

    print()
    print("--- CONFIGURED CELL WIRE RESISTANCE ---")

    count = min(max(vals["cell_count"], 1), 32)

    for i in range(count):
        r = u32(f, 142 + i * 4) / 1000

        print(
            f"Cell {i+1:02d} configured R          : "
            f"{r:.3f} ohm"
        )

    print()
    print("--- JK02_32S EXTENDED SETTINGS ---")

    vals["device_address"] = f[270]
    vals["precharge_time"] = f[274]
    controls = u16(f, 282)
    vals["controls"] = controls

    print(
        f"{'Device address':31s}: "
        f"{f[270]}"
    )

    print(
        f"{'Unknown 271..273':31s}: "
        f"{hexblock(f,271,274)}"
    )

    print(
        f"{'Discharge precharge time':31s}: "
        f"{f[274]} s"
    )

    print(
        f"{'Unknown 275..281':31s}: "
        f"{hexblock(f,275,282)}"
    )

    print(
        f"{'Control bitmask':31s}: "
        f"0x{controls:04X}"
    )

    for bit, name in CONTROL_BITS.items():
        print(
            f"  bit {bit:02d} {name:26s}: "
            f"{yn(bool(controls & (1 << bit)))}"
        )

    vals["heat_start"] = i8(f, 284)
    vals["heat_stop"] = i8(f, 285)
    vals["smart_sleep_time"] = f[286]
    vals["data_field_enable"] = f[287]

    print(
        f"{'Heating start':31s}: "
        f"{vals['heat_start']} °C"
    )
    print(
        f"{'Heating stop':31s}: "
        f"{vals['heat_stop']} °C"
    )
    print(
        f"{'Smart Sleep time':31s}: "
        f"{vals['smart_sleep_time']} h"
    )
    print(
        f"{'Data field enable':31s}: "
        f"0x{vals['data_field_enable']:02X}"
    )

    print(
        f"{'Unknown 288..298':31s}: "
        f"{hexblock(f,288,299)}"
    )

    return vals


def decode_device(f):
    title("DEVICE INFO  (frame 0x03)")

    d = {}

    d["vendor"] = asc(f, 6, 16)
    d["hw"] = asc(f, 22, 8)
    d["sw"] = asc(f, 30, 8)
    d["uptime"] = u32(f, 38)
    d["power_on"] = u32(f, 42)
    d["name"] = asc(f, 46, 16)
    d["mfg"] = asc(f, 78, 8)
    d["serial"] = asc(f, 86, 11)
    d["userdata"] = asc(f, 102, 16)
    d["userdata2"] = asc(f, 134, 16)

    print(f"{'Vendor / model':31s}: {d['vendor']}")
    print(f"{'Hardware':31s}: {d['hw']}")
    print(f"{'Software':31s}: {d['sw']}")
    print(
        f"{'Device uptime':31s}: "
        f"{d['uptime']} s "
        f"({runtime_string(d['uptime'])})"
    )
    print(
        f"{'Power-on count':31s}: "
        f"{d['power_on']}"
    )
    print(f"{'Device name':31s}: {d['name']}")
    print(f"{'Manufacturing date':31s}: {d['mfg']}")
    print(f"{'Serial number':31s}: {d['serial']}")
    print(f"{'User data':31s}: {d['userdata']}")
    print(f"{'User data 2':31s}: {d['userdata2']}")

    # Пароли намеренно не печатаем.
    print(
        f"{'Device passcode':31s}: "
        "<present, masked>"
    )
    print(
        f"{'Setup passcode':31s}: "
        "<present, masked>"
    )

    print()
    print("--- COMMUNICATION / AUXILIARY ---")

    d["uart1"] = f[184]
    d["can"] = f[185]
    d["uart2"] = f[218]

    print(
        f"{'UART1 protocol':31s}: {f[184]}"
    )
    print(
        f"{'CAN protocol':31s}: {f[185]}"
    )
    print(
        f"{'UART2 protocol':31s}: {f[218]}"
    )

    print(
        f"{'LCD buzzer trigger':31s}: {f[234]}"
    )
    print(
        f"{'DRY1 trigger':31s}: {f[235]}"
    )
    print(
        f"{'DRY2 trigger':31s}: {f[236]}"
    )
    print(
        f"{'UART protocol library ver':31s}: "
        f"{f[237]}"
    )

    print(
        f"{'LCD buzzer trigger value':31s}: "
        f"{u32(f,238)}"
    )
    print(
        f"{'LCD buzzer release value':31s}: "
        f"{u32(f,242)}"
    )
    print(
        f"{'DRY1 trigger value':31s}: "
        f"{u32(f,246)}"
    )
    print(
        f"{'DRY1 release value':31s}: "
        f"{u32(f,250)}"
    )
    print(
        f"{'DRY2 trigger value':31s}: "
        f"{u32(f,254)}"
    )
    print(
        f"{'DRY2 release value':31s}: "
        f"{u32(f,258)}"
    )
    print(
        f"{'Data stored period':31s}: "
        f"{u32(f,262)}"
    )

    d["rcv_time"] = f[266] / 10
    d["rfv_time"] = f[267] / 10

    print(
        f"{'RCV Time':31s}: "
        f"{d['rcv_time']:.1f} h"
    )
    print(
        f"{'RFV Time':31s}: "
        f"{d['rfv_time']:.1f} h"
    )

    print(
        f"{'CAN protocol library ver':31s}: "
        f"{f[268]}"
    )

    print()
    print("--- UNDECODED DEVICE-INFO AREAS ---")

    for a, b in [
        (150,184),
        (186,218),
        (219,234),
        (269,299),
    ]:
        print(
            f"{a:03d}..{b-1:03d}: "
            f"{hexblock(f,a,b)}"
        )

    return d


def decode_live(f, configured_cell_count):
    title("LIVE DATA  (frame 0x02 / JK02_32S)")

    # JK02_32S:
    # +16 bytes after cell voltage array,
    # then +32 bytes after voltage + resistance arrays.
    offset_cells = 16
    offset = 32

    cell_count = min(
        max(int(configured_cell_count), 1),
        32
    )

    cells = [
        u16(f, 6 + i * 2) / 1000
        for i in range(32)
    ]

    enabled_cells = [
        (i + 1, v)
        for i, v in enumerate(cells)
        if v > 0
    ]

    print("--- CELL VOLTAGES ---")

    for i in range(cell_count):
        print(
            f"Cell {i+1:02d} voltage                : "
            f"{cells[i]:.3f} V"
        )

    active_voltages = [
        v for _, v in enabled_cells
    ]

    if active_voltages:
        vmin = min(active_voltages)
        vmax = max(active_voltages)
        avg = sum(active_voltages) / len(active_voltages)
        delta = vmax - vmin

        min_cell = min(
            enabled_cells,
            key=lambda x: x[1]
        )[0]

        max_cell = max(
            enabled_cells,
            key=lambda x: x[1]
        )[0]

        print()
        print(
            f"{'Active cells':31s}: "
            f"{len(active_voltages)}"
        )
        print(
            f"{'Minimum cell':31s}: "
            f"Cell {min_cell}, {vmin:.3f} V"
        )
        print(
            f"{'Maximum cell':31s}: "
            f"Cell {max_cell}, {vmax:.3f} V"
        )
        print(
            f"{'Average cell':31s}: "
            f"{avg:.3f} V"
        )
        print(
            f"{'Delta':31s}: "
            f"{delta*1000:.0f} mV"
        )
    else:
        vmin = vmax = avg = delta = 0

    enabled_mask = u32(f, 54 + offset_cells)

    print(
        f"{'Enabled cells mask':31s}: "
        f"0x{enabled_mask:08X}"
    )

    print()
    print("--- LIVE WIRE RESISTANCE ---")

    live_res = []

    for i in range(cell_count):
        r = u16(
            f,
            64 + offset_cells + i * 2
        ) / 1000

        live_res.append(r)

        print(
            f"Cell {i+1:02d} wire resistance        : "
            f"{r:.3f} ohm"
        )

    mos_temp = s16(f, 112 + offset) / 10

    wire_warn = u32(f, 114 + offset)

    pack = u32(f, 118 + offset) / 1000
    current = s32(f, 126 + offset) / 1000
    power = pack * current

    t1 = s16(f, 130 + offset) / 10
    t2 = s16(f, 132 + offset) / 10

    errors = u32(f, 134 + offset)

    balancing_current = (
        s16(f, 138 + offset) / 1000
    )

    balance_state = f[140 + offset]

    soc = f[141 + offset]
    remaining = u32(f, 142 + offset) / 1000
    nominal = u32(f, 146 + offset) / 1000
    cycles = u32(f, 150 + offset)
    cycle_capacity = (
        u32(f, 154 + offset) / 1000
    )
    soh = f[158 + offset]

    uptime = u32(f, 162 + offset)

    charging = bool(f[166 + offset])
    discharging = bool(f[167 + offset])
    precharging = bool(f[168 + offset])
    balancing_new = bool(f[169 + offset])

    print()
    print("--- PACK / SOC ---")

    print(f"{'Pack voltage':31s}: {pack:.3f} V")
    print(f"{'Current':31s}: {current:+.3f} A")
    print(f"{'Calculated power':31s}: {power:+.2f} W")
    print(f"{'SOC':31s}: {soc} %")
    print(f"{'SOH':31s}: {soh} %")
    print(
        f"{'Remaining capacity':31s}: "
        f"{remaining:.3f} Ah"
    )
    print(
        f"{'Nominal capacity':31s}: "
        f"{nominal:.3f} Ah"
    )
    print(
        f"{'Cycle count':31s}: "
        f"{cycles}"
    )
    print(
        f"{'Total cycle capacity':31s}: "
        f"{cycle_capacity:.3f} Ah"
    )
    print(
        f"{'Total runtime':31s}: "
        f"{uptime} s ({runtime_string(uptime)})"
    )

    print()
    print("--- TEMPERATURES ---")

    print(f"{'MOS temperature':31s}: {mos_temp:.1f} °C")
    print(f"{'Temperature T1':31s}: {t1:.1f} °C")
    print(f"{'Temperature T2':31s}: {t2:.1f} °C")

    t5 = s16(f, 222 + offset) / 10
    t4 = s16(f, 224 + offset) / 10
    t3 = s16(f, 226 + offset) / 10

    print(f"{'Temperature T3':31s}: {t3:.1f} °C")
    print(f"{'Temperature T4':31s}: {t4:.1f} °C")
    print(f"{'Temperature T5':31s}: {t5:.1f} °C")

    print()
    print("--- MOS / BALANCER / HEATER ---")

    print(
        f"{'Charge MOS':31s}: {yn(charging)}"
    )
    print(
        f"{'Discharge MOS':31s}: {yn(discharging)}"
    )
    print(
        f"{'Precharge':31s}: {yn(precharging)}"
    )
    print(
        f"{'Balancer activity':31s}: "
        f"{balance_state}"
    )
    print(
        f"{'Balancer new flag':31s}: "
        f"{yn(balancing_new)}"
    )
    print(
        f"{'Balancing current':31s}: "
        f"{balancing_current:+.3f} A"
    )

    temp_absent = u16(f, 182 + offset)
    heating = bool(f[183 + offset])

    print(
        f"{'Temperature absent mask':31s}: "
        f"0x{temp_absent:04X}"
    )
    print(
        f"{'Heating':31s}: "
        f"{yn(heating)}"
    )

    print()
    print("--- ERRORS / WARNINGS ---")

    print(
        f"{'Errors bitmask':31s}: "
        f"0x{errors:08X}"
    )
    print(
        f"{'Wire warning mask':31s}: "
        f"0x{wire_warn:08X}"
    )

    active_errors = []

    for bit in range(32):
        if errors & (1 << bit):
            active_errors.append(
                ERROR_NAMES.get(
                    bit,
                    f"Unknown error bit {bit}"
                )
            )

    if not active_errors:
        print("Active errors                   : NONE")
    else:
        for e in active_errors:
            print(f"ACTIVE ERROR                    : {e}")

    print()
    print("--- PROTECTION RELEASE TIMERS ---")

    timers = [
        ("Discharge OCP release", 170),
        ("Discharge SCP release", 172),
        ("Charge OCP release",    174),
        ("Charge SCP release",    176),
        ("UVP release",           178),
        ("OVP release",           180),
    ]

    for name, base in timers:
        print(
            f"{name:31s}: "
            f"{u16(f, base + offset)} s"
        )

    print()
    print("--- ADDITIONAL LIVE DATA ---")

    emergency = u16(f, 186 + offset)
    dc_corr = u16(f, 188 + offset)
    charge_sensor_v = (
        u16(f, 190 + offset) / 1000
    )
    discharge_sensor_v = (
        u16(f, 192 + offset) / 1000
    )
    voltage_corr = u32(f, 194 + offset)
    battery_voltage_alt = (
        u16(f, 202 + offset) * 0.01
    )
    heating_current = (
        s16(f, 204 + offset) / 1000
    )

    charger_plugged = bool(f[213 + offset])

    print(
        f"{'Emergency countdown':31s}: "
        f"{emergency} s"
    )
    print(
        f"{'Discharge current corr factor':31s}: "
        f"{dc_corr}"
    )
    print(
        f"{'Charge current sensor voltage':31s}: "
        f"{charge_sensor_v:.3f} V"
    )
    print(
        f"{'Discharge current sensor volt':31s}: "
        f"{discharge_sensor_v:.3f} V"
    )
    print(
        f"{'Battery voltage corr factor':31s}: "
        f"{voltage_corr}"
    )
    print(
        f"{'Battery voltage secondary':31s}: "
        f"{battery_voltage_alt:.2f} V"
    )
    print(
        f"{'Heating current':31s}: "
        f"{heating_current:+.3f} A"
    )
    print(
        f"{'Charger plugged flag':31s}: "
        f"{yn(charger_plugged)}"
    )

    detail_logs = u32(f, 234 + offset)
    smart_sleep_countdown = u32(f, 238 + offset)
    pcl_state = bool(f[242 + offset])

    battery_type_id = f[243 + offset]

    battery_type = {
        0: "LiFePO4",
        1: "Li-ion",
        2: "LTO",
    }.get(
        battery_type_id,
        f"Unknown({battery_type_id})"
    )

    charge_elapsed = u16(f, 246 + offset)
    charge_id = f[248 + offset]

    charge_state = {
        0: "Bulk",
        1: "Absorption",
        2: "Float",
    }.get(
        charge_id,
        f"Unknown({charge_id})"
    )

    drymask = f[249 + offset]

    print(
        f"{'Detail log entry count':31s}: "
        f"{detail_logs}"
    )
    print(
        f"{'Smart Sleep countdown':31s}: "
        f"{smart_sleep_countdown} s"
    )
    print(
        f"{'PCL module state':31s}: "
        f"{yn(pcl_state)}"
    )
    print(
        f"{'Battery type':31s}: "
        f"{battery_type}"
    )
    print(
        f"{'Charge state':31s}: "
        f"{charge_state} ({charge_id})"
    )
    print(
        f"{'Charge state timer':31s}: "
        f"{charge_elapsed} s"
    )
    print(
        f"{'Dry contacts mask':31s}: "
        f"0x{drymask:02X}"
    )

    return {
        "cells": cells,
        "active_cells": len(active_voltages),
        "vmin": vmin,
        "vmax": vmax,
        "delta": delta,
        "pack": pack,
        "current": current,
        "soc": soc,
        "soh": soh,
        "remaining": remaining,
        "nominal": nominal,
        "errors": errors,
        "battery_type": battery_type,
        "charge_state": charge_state,
        "charge_elapsed": charge_elapsed,
    }


def evaluate(settings, dev, live):
    title("AUTOMATIC FIRST-PASS EVALUATION")

    def result(label, status, text):
        print(
            f"[{status:5s}] {label:28s} {text}"
        )

    result(
        "Protocol/model",
        "OK",
        f"{dev['vendor']} HW {dev['hw']} "
        f"SW {dev['sw']}"
    )

    if settings["cell_count"] == 4:
        result(
            "Configured cell count",
            "OK",
            "4S"
        )
    else:
        result(
            "Configured cell count",
            "WARN",
            f"{settings['cell_count']}S, expected 4S"
        )

    if live["active_cells"] == 4:
        result(
            "Detected active cells",
            "OK",
            "4 active cells"
        )
    else:
        result(
            "Detected active cells",
            "WARN",
            f"{live['active_cells']} active cells"
        )

    if live["battery_type"] == "LiFePO4":
        result(
            "Battery chemistry",
            "OK",
            "LiFePO4"
        )
    else:
        result(
            "Battery chemistry",
            "WARN",
            live["battery_type"]
        )

    if abs(settings["capacity"] - 25.0) < 0.1:
        result(
            "Configured capacity",
            "OK",
            f"{settings['capacity']:.3f} Ah"
        )
    else:
        result(
            "Configured capacity",
            "WARN",
            f"{settings['capacity']:.3f} Ah"
        )

    delta_mv = live["delta"] * 1000

    if delta_mv < 30:
        result(
            "Cell balance",
            "OK",
            f"delta {delta_mv:.0f} mV"
        )
    elif delta_mv < 50:
        result(
            "Cell balance",
            "WARN",
            f"delta {delta_mv:.0f} mV"
        )
    else:
        result(
            "Cell balance",
            "BAD",
            f"delta {delta_mv:.0f} mV"
        )

    if live["errors"] == 0:
        result(
            "BMS alarms",
            "OK",
            "none"
        )
    else:
        result(
            "BMS alarms",
            "BAD",
            f"0x{live['errors']:08X}"
        )

    if (
        settings["rcv"]
        > settings["soc100"]
        > settings["ovpr"]
    ):
        result(
            "RCV/SOC100/OVPR order",
            "OK",
            (
                f"{settings['rcv']:.3f} > "
                f"{settings['soc100']:.3f} > "
                f"{settings['ovpr']:.3f}"
            )
        )
    else:
        result(
            "RCV/SOC100/OVPR order",
            "WARN",
            (
                f"{settings['rcv']:.3f} / "
                f"{settings['soc100']:.3f} / "
                f"{settings['ovpr']:.3f}"
            )
        )

    if settings["uvpr"] > settings["uvp"]:
        result(
            "UVP recovery relation",
            "OK",
            (
                f"{settings['uvp']:.3f} -> "
                f"{settings['uvpr']:.3f} V"
            )
        )
    else:
        result(
            "UVP recovery relation",
            "WARN",
            (
                f"{settings['uvp']:.3f} / "
                f"{settings['uvpr']:.3f}"
            )
        )

    if settings["ovp"] > settings["ovpr"]:
        result(
            "OVP recovery relation",
            "OK",
            (
                f"{settings['ovp']:.3f} -> "
                f"{settings['ovpr']:.3f} V"
            )
        )
    else:
        result(
            "OVP recovery relation",
            "WARN",
            (
                f"{settings['ovp']:.3f} / "
                f"{settings['ovpr']:.3f}"
            )
        )

    rcv_pack = (
        settings["rcv"]
        * settings["cell_count"]
    )

    soc100_pack = (
        settings["soc100"]
        * settings["cell_count"]
    )

    result(
        "RCV pack threshold",
        "INFO",
        f"{rcv_pack:.3f} V"
    )

    result(
        "SOC100 pack threshold",
        "INFO",
        f"{soc100_pack:.3f} V"
    )

    result(
        "Current pack voltage",
        "INFO",
        f"{live['pack']:.3f} V"
    )

    result(
        "RCV Time",
        "INFO",
        f"{dev['rcv_time']:.1f} h"
    )

    result(
        "RFV Time",
        "INFO",
        f"{dev['rfv_time']:.1f} h"
    )

    result(
        "SOC/capacity",
        "INFO",
        (
            f"{live['soc']}%, "
            f"{live['remaining']:.3f}/"
            f"{live['nominal']:.3f} Ah"
        )
    )

    result(
        "Charge state",
        "INFO",
        (
            f"{live['charge_state']}, "
            f"timer {live['charge_elapsed']} s"
        )
    )

    if (
        settings["rfv"] > settings["rcv"]
        and not (settings["controls"] & (1 << 9))
    ):
        result(
            "RFV vs RCV",
            "INFO",
            (
                f"RFV {settings['rfv']:.3f} > "
                f"RCV {settings['rcv']:.3f}; "
                "Float mode is OFF"
            )
        )


async def main():
    print("JK BMS FULL READ-ONLY AUDIT")
    print("MAC:", MAC)
    print("Adapter:", ADAPTER)
    print("No configuration writes will be performed.")
    print()

    dev = None

    for n in range(1, 7):
        print(f"Search attempt {n}/6")

        dev = await BleakScanner.find_device_by_address(
            MAC,
            timeout=10,
            adapter=ADAPTER
        )

        if dev:
            break

        await asyncio.sleep(2)

    if dev is None:
        raise SystemExit("BMS not found")

    print("Found:", dev)

    async with BleakClient(
        dev,
        adapter=ADAPTER,
        timeout=30
    ) as client:

        chars = [
            c
            for s in client.services
            for c in s.characteristics
            if c.uuid.lower() == FFE1
        ]

        ch = next(
            c for c in chars
            if "write-without-response"
            in c.properties
        )

        nch = next(
            c for c in chars
            if "notify" in c.properties
        )

        await client.start_notify(
            nch,
            notify
        )

        # READ REQUESTS ONLY
        await client.write_gatt_char(
            ch,
            request_frame(0x97),
            response=False
        )

        await asyncio.sleep(1)

        await client.write_gatt_char(
            ch,
            request_frame(0x96),
            response=False
        )

        deadline = time.monotonic() + 15

        while time.monotonic() < deadline:
            if all(
                typ in frames
                for typ in (1, 2, 3)
            ):
                break

            await asyncio.sleep(1)

            # only read requests
            if 2 not in frames:
                await client.write_gatt_char(
                    ch,
                    request_frame(0x96),
                    response=False
                )

            if 1 not in frames or 3 not in frames:
                await client.write_gatt_char(
                    ch,
                    request_frame(0x97),
                    response=False
                )

        missing = [
            typ
            for typ in (1, 2, 3)
            if typ not in frames
        ]

        if missing:
            raise RuntimeError(
                f"Missing frames: {missing}"
            )

        settings_frame = frames[1]
        live_frame = frames[2]
        device_frame = frames[3]

        devinfo = decode_device(device_frame)
        settings = decode_settings(settings_frame)

        live = decode_live(
            live_frame,
            settings["cell_count"]
        )

        evaluate(
            settings,
            devinfo,
            live
        )

        title("RAW FRAME CHECKSUMS / COUNTERS")

        for typ, name in [
            (1, "SETTINGS"),
            (2, "LIVE"),
            (3, "DEVICE"),
        ]:
            f = frames[typ]

            print(
                f"{name:10s}: "
                f"counter={f[5]:3d} "
                f"crc=0x{f[299]:02X} "
                f"calc=0x{sum(f[:299]) & 0xff:02X}"
            )

        print()
        print(
            "Audit complete. "
            "No BMS settings were changed."
        )

        await client.stop_notify(nch)


asyncio.run(main())
