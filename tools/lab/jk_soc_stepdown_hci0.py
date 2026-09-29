import asyncio
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
HEADER = bytes.fromhex("55 AA EB 90")

STEP_MV = 20
MAX_PASSES = 10

# Порядок важен: снизу вверх по цепочке
# RCV > SOC100 > OVPR
PARAMS = [
    {
        "name": "OVPR",
        "reg": 0x05,
        "offset": 22,
        "target": 3390,
    },
    {
        "name": "SOC100",
        "reg": 0x07,
        "offset": 30,
        "target": 3400,
    },
    {
        "name": "RCV",
        "reg": 0x09,
        "offset": 38,
        "target": 3440,
    },
]

rx = bytearray()
q_settings = asyncio.Queue()


def make_frame(reg, value=0, length=0):
    f = bytearray(20)

    f[0:4] = bytes.fromhex("AA 55 90 EB")
    f[4] = reg
    f[5] = length

    f[6] = (value >> 0) & 0xff
    f[7] = (value >> 8) & 0xff
    f[8] = (value >> 16) & 0xff
    f[9] = (value >> 24) & 0xff

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

        if p > 0:
            del rx[:p]

        if len(rx) < 300:
            return

        f = bytes(rx[:300])
        del rx[:300]

        if (sum(f[:299]) & 0xff) != f[299]:
            continue

        if f[4] == 0x01:
            q_settings.put_nowait(f)


async def clear_queue():
    while not q_settings.empty():
        try:
            q_settings.get_nowait()
        except asyncio.QueueEmpty:
            break


async def send(client, ch, reg, value=0, length=0):
    f = make_frame(reg, value, length)

    print(
        "TX:",
        " ".join(f"{x:02X}" for x in f)
    )

    await client.write_gatt_char(
        ch,
        f,
        response=False
    )


async def get_settings(client, ch):
    await clear_queue()

    await send(
        client,
        ch,
        0x96,
        0,
        0
    )

    return await asyncio.wait_for(
        q_settings.get(),
        timeout=12
    )


def u32(f, offset):
    return int.from_bytes(
        f[offset:offset+4],
        "little"
    )


def values(f):
    return {
        p["name"]: u32(f, p["offset"])
        for p in PARAMS
    }


def show(vals, title):
    print()
    print("========================================")
    print(title)
    print("========================================")

    for p in PARAMS:
        v = vals[p["name"]]
        print(
            f"{p['name']:7s} "
            f"{v / 1000:.3f} V "
            f"(target {p['target']/1000:.3f})"
        )


async def main():

    dev = None

    for attempt in range(1, 5):
        print(
            f"Searching {MAC} via {ADAPTER}, "
            f"attempt {attempt}/4..."
        )

        dev = await BleakScanner.find_device_by_address(
            MAC,
            timeout=12,
            adapter=ADAPTER
        )

        if dev is not None:
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
            for service in client.services
            for c in service.characteristics
            if c.uuid.lower() == FFE1
        ]

        write_ch = next(
            (
                c for c in chars
                if "write-without-response"
                in c.properties
            ),
            None
        )

        notify_ch = next(
            (
                c for c in chars
                if "notify" in c.properties
            ),
            None
        )

        if write_ch is None or notify_ch is None:
            raise RuntimeError("FFE1 write/notify not found")

        print("FFE1 handle:", write_ch.handle)

        await client.start_notify(
            notify_ch,
            notify
        )

        await asyncio.sleep(0.7)

        #
        # Инициализация BLE-сеанса JK
        #
        print()
        print("===== INIT =====")

        await send(
            client,
            write_ch,
            0x97,
            0,
            0
        )

        await asyncio.sleep(1)

        f = await get_settings(
            client,
            write_ch
        )

        vals = values(f)

        show(
            vals,
            "START VALUES"
        )

        #
        # Проходы
        #
        for pass_no in range(1, MAX_PASSES + 1):

            print()
            print()
            print(
                "########################################"
            )
            print(
                f"PASS {pass_no}/{MAX_PASSES}"
            )
            print(
                "########################################"
            )

            progress = False

            for p in PARAMS:

                name = p["name"]
                current = vals[name]
                target = p["target"]

                print()
                print("----------------------------------------")
                print(
                    f"{name}: current={current/1000:.3f} "
                    f"target={target/1000:.3f}"
                )

                if current == target:
                    print("Already at target")
                    continue

                if current < target:
                    print(
                        "Current value is BELOW target. "
                        "Not increasing automatically."
                    )
                    continue

                candidate = max(
                    target,
                    current - STEP_MV
                )

                print(
                    f"TRY {name}: "
                    f"{current/1000:.3f} -> "
                    f"{candidate/1000:.3f} V"
                )

                await send(
                    client,
                    write_ch,
                    p["reg"],
                    candidate,
                    4
                )

                await asyncio.sleep(1.5)

                f = await get_settings(
                    client,
                    write_ch
                )

                new_vals = values(f)
                actual = new_vals[name]

                print(
                    f"READBACK {name}: "
                    f"{actual/1000:.3f} V"
                )

                if actual == candidate:
                    print(
                        f"SUCCESS: {name} changed"
                    )
                    progress = True

                elif actual == current:
                    print(
                        f"REJECTED: {name} unchanged"
                    )

                else:
                    print(
                        f"UNEXPECTED: {name} changed to "
                        f"{actual/1000:.3f} V"
                    )
                    progress = True

                #
                # Всегда принимаем полный свежий
                # settings-frame как истину.
                #
                vals = new_vals

                await asyncio.sleep(0.8)

            show(
                vals,
                f"AFTER PASS {pass_no}"
            )

            done = all(
                vals[p["name"]] == p["target"]
                for p in PARAMS
            )

            if done:
                print()
                print(
                    "****************************************"
                )
                print(
                    "ALL TARGET VALUES REACHED"
                )
                print(
                    "****************************************"
                )
                break

            if not progress:
                print()
                print(
                    "****************************************"
                )
                print(
                    "NO PARAMETER CHANGED IN THIS PASS"
                )
                print(
                    "STOPPING - hidden constraint found"
                )
                print(
                    "****************************************"
                )
                break

            await asyncio.sleep(1)

        #
        # Финальный readback
        #
        f = await get_settings(
            client,
            write_ch
        )

        vals = values(f)

        show(
            vals,
            "FINAL READBACK"
        )

        print()
        print("RCV > SOC100 > OVPR:")
        print(
            f"{vals['RCV']/1000:.3f} > "
            f"{vals['SOC100']/1000:.3f} > "
            f"{vals['OVPR']/1000:.3f}"
        )

        await client.stop_notify(
            notify_ch
        )


asyncio.run(main())
