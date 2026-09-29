import asyncio
import time
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
HEADER = bytes.fromhex("55 AA EB 90")

rx = bytearray()
q_settings = asyncio.Queue()
q_info = asyncio.Queue()
q_live = asyncio.Queue()

TARGETS = [
    # Верхнюю цепочку JK меняем снизу вверх:
    # OVP > RCV > SOC100 > OVPR
    #
    # name, register, value, settings_offset, command_length
    ("OVPR",   0x05, 3390, 22, 4),
    ("SOC100", 0x07, 3400, 30, 4),
    ("RCV",    0x09, 3440, 38, 4),
]


def make_frame(reg, value=0, length=0):
    f = bytearray(20)
    f[0:4] = bytes.fromhex("AA 55 90 EB")
    f[4] = reg
    f[5] = length
    f[6:10] = int(value).to_bytes(4, "little")
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
            print("BAD CRC")
            continue

        if f[4] == 0x01:
            q_settings.put_nowait(f)
        elif f[4] == 0x02:
            q_live.put_nowait(f)
        elif f[4] == 0x03:
            q_info.put_nowait(f)


async def clear(q):
    while not q.empty():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            break


async def send(client, ch, reg, value=0, length=0):
    f = make_frame(reg, value, length)
    print(
        "TX:",
        " ".join(f"{x:02X}" for x in f)
    )
    await client.write_gatt_char(
        ch, f, response=False
    )


async def get_settings(client, ch):
    await clear(q_settings)

    await send(client, ch, 0x96)

    return await asyncio.wait_for(
        q_settings.get(),
        timeout=12
    )


async def get_info(client, ch):
    await clear(q_info)

    await send(client, ch, 0x97)

    return await asyncio.wait_for(
        q_info.get(),
        timeout=12
    )


def u32(f, n):
    return int.from_bytes(
        f[n:n+4], "little"
    )


def show_settings(f):
    vals = {
        "SmartSleep": u32(f, 6),
        "UVP":        u32(f, 10),
        "UVPR":       u32(f, 14),
        "OVP":        u32(f, 18),
        "OVPR":       u32(f, 22),
        "SOC100":     u32(f, 30),
        "SOC0":       u32(f, 34),
        "RCV":        u32(f, 38),
        "RFV":        u32(f, 42),
        "PowerOff":   u32(f, 46),
    }

    print()
    print("===== VOLTAGE SETTINGS =====")

    for k, v in vals.items():
        print(
            f"{k:11s} {v/1000:.3f} V"
        )

    if len(f) > 283:
        controls = int.from_bytes(
            f[282:284], "little"
        )

        print(
            f"Controls:    0x{controls:04X}"
        )

        print(
            "Float mode:",
            "ON" if controls & 0x0200 else "OFF"
        )

    return vals


async def write_verify(
    client, ch, name, reg, value, offset, length
):
    print()
    print("========================================")
    print(
        f"WRITE {name}: {value/1000:.3f} V"
    )
    print("========================================")

    print(
        f"COMMAND LENGTH: {length}"
    )

    await send(
        client,
        ch,
        reg,
        value,
        length
    )

    await asyncio.sleep(1.5)

    f = await get_settings(client, ch)

    actual = u32(f, offset)

    print(
        f"READBACK {name}: "
        f"{actual/1000:.3f} V"
    )

    if actual != value:
        print()
        print(
            f"FAILED: {name} was rejected by BMS"
        )
        print("STOPPING HERE.")
        return False

    print("OK")
    return True


def decode_live(f):
    pack = u32(f, 150)

    current = int.from_bytes(
        f[158:162],
        "little",
        signed=True
    )

    soc = f[173]

    remain = u32(f, 174)
    capacity = u32(f, 178)

    elapsed = int.from_bytes(
        f[278:280], "little"
    )

    status_id = f[280]

    status = {
        0: "Bulk",
        1: "Absorption",
        2: "Float",
    }.get(
        status_id,
        f"Unknown({status_id})"
    )

    cells = [
        int.from_bytes(
            f[6+i*2:8+i*2],
            "little"
        )
        for i in range(4)
    ]

    return (
        pack,
        current,
        soc,
        remain,
        capacity,
        status,
        elapsed,
        cells,
    )


async def main():

    dev = None

    for attempt in range(1, 5):
        print(
            f"Searching via {ADAPTER} "
            f"attempt {attempt}/4..."
        )

        dev = await BleakScanner.find_device_by_address(
            MAC,
            timeout=12,
            adapter=ADAPTER
        )

        if dev:
            break

        await asyncio.sleep(3)

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

        print("FFE1 handle:", ch.handle)

        await client.start_notify(
            nch, notify
        )

        await asyncio.sleep(0.7)

        #
        # Proper session initialization
        #
        info = await get_info(client, ch)

        print(
            "HW:",
            info[22:30]
            .split(b"\x00")[0]
            .decode(errors="ignore")
        )

        print(
            "SW:",
            info[30:38]
            .split(b"\x00")[0]
            .decode(errors="ignore")
        )

        f = await get_settings(client, ch)

        print()
        print("===== BEFORE =====")
        show_settings(f)

        print()
        print(
            "RCV Time:",
            f"{info[266]/10:.1f} h"
        )

        #
        # Change values ONE BY ONE,
        # verifying after every write.
        #
        for item in TARGETS:
            ok = await write_verify(
                client,
                ch,
                *item
            )

            if not ok:
                await client.stop_notify(nch)
                return

        #
        # Ensure RCV Time = 0.1 h
        #
        print()
        print("========================================")
        print("RCV TIME -> 0.1 h")
        print("========================================")

        await send(
            client,
            ch,
            0xB3,
            1,
            1
        )

        await asyncio.sleep(1.5)

        info = await get_info(client, ch)

        print(
            "RCV Time readback:",
            f"{info[266]/10:.1f} h"
        )

        if info[266] != 1:
            print(
                "RCV TIME WRITE FAILED"
            )
            return

        #
        # Final settings
        #
        f = await get_settings(client, ch)

        print()
        print("========================================")
        print("FINAL SETTINGS")
        print("========================================")
        show_settings(f)

        print()
        print(
            "RCV Time:",
            f"{info[266]/10:.1f} h"
        )

        print()
        print("Target pack voltages:")
        print("RCV    = 13.760 V")
        print("SOC100 = 13.600 V")

        #
        # Observe SOC algorithm
        #
        print()
        print("========================================")
        print("SOC SYNC WATCH - 20 MIN")
        print("Ctrl+C can safely stop it")
        print("========================================")

        await clear(q_live)

        await send(client, ch, 0x96)

        start = time.monotonic()
        last_print = 0
        last_status = None
        last_soc = None

        while time.monotonic() - start < 1200:

            try:
                lf = await asyncio.wait_for(
                    q_live.get(),
                    timeout=15
                )

            except asyncio.TimeoutError:
                await send(
                    client,
                    ch,
                    0x96
                )
                continue

            (
                pack,
                current,
                soc,
                remain,
                capacity,
                status,
                elapsed,
                cells,
            ) = decode_live(lf)

            now = time.monotonic()

            if (
                now - last_print >= 5
                or status != last_status
                or soc != last_soc
            ):

                print(
                    time.strftime("%H:%M:%S"),
                    f"U={pack/1000:.3f}V",
                    f"I={current/1000:+.3f}A",
                    f"SOC={soc}%",
                    f"Remain={remain/1000:.3f}/"
                    f"{capacity/1000:.3f}Ah",
                    f"Status={status}",
                    f"Timer={elapsed}s",
                    "Cells=" +
                    "/".join(
                        f"{v/1000:.3f}"
                        for v in cells
                    ),
                    flush=True
                )

                last_print = now
                last_status = status
                last_soc = soc

            if soc == 100:
                print()
                print(
                    "***** SOC RESET SUCCESS *****"
                )
                break

        await client.stop_notify(nch)


asyncio.run(main())
