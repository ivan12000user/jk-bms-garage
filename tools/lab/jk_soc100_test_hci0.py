import asyncio
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
HEADER = bytes.fromhex("55 AA EB 90")

rx = bytearray()
q_settings = asyncio.Queue()
q_live = asyncio.Queue()


def frame(reg, value=0, length=0):
    f = bytearray(20)
    f[0:4] = bytes.fromhex("AA 55 90 EB")
    f[4] = reg
    f[5] = length
    f[6:10] = value.to_bytes(4, "little")
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

        if f[4] == 0x01:
            q_settings.put_nowait(f)
        elif f[4] == 0x02:
            q_live.put_nowait(f)


async def send(client, ch, reg, value=0, length=0):
    f = frame(reg, value, length)

    print(
        "TX:",
        " ".join(f"{x:02X}" for x in f)
    )

    await client.write_gatt_char(
        ch,
        f,
        response=False
    )


async def clear(q):
    while not q.empty():
        q.get_nowait()


def print_live(title, f):
    cells = [
        int.from_bytes(f[6+i*2:8+i*2], "little") / 1000
        for i in range(4)
    ]

    soc = f[173]
    remain = int.from_bytes(f[174:178], "little") / 1000
    capacity = int.from_bytes(f[178:182], "little") / 1000

    print()
    print("=====", title, "=====")
    print("Cells:", " / ".join(f"{v:.3f}" for v in cells), "V")
    print("SOC:", soc, "%")
    print("Remaining:", f"{remain:.3f}", "Ah")
    print("Capacity:", f"{capacity:.3f}", "Ah")


async def main():
    dev = await BleakScanner.find_device_by_address(
        MAC,
        timeout=15,
        adapter=ADAPTER
    )

    if dev is None:
        raise SystemExit("BMS not found via hci0")

    print("Found:", dev)

    async with BleakClient(
        dev,
        adapter=ADAPTER,
        timeout=20
    ) as client:

        chars = [
            c
            for s in client.services
            for c in s.characteristics
            if c.uuid.lower() == FFE1
        ]

        ch = next(
            c for c in chars
            if "write-without-response" in c.properties
        )

        nch = next(
            c for c in chars
            if "notify" in c.properties
        )

        await client.start_notify(nch, notify)

        # Инициализация
        await send(client, ch, 0x97)
        await asyncio.sleep(1)

        # Состояние ДО
        await clear(q_live)
        await send(client, ch, 0x96)

        before = await asyncio.wait_for(
            q_live.get(),
            timeout=12
        )

        print_live("BEFORE", before)

        # SOC-100% voltage = 3.410 V
        print()
        print("===== WRITE SOC100 = 3.410 V =====")

        await send(
            client,
            ch,
            0x07,
            3410,
            4
        )

        await asyncio.sleep(2)

        # Проверяем, что настройка реально записалась
        await clear(q_settings)
        await send(client, ch, 0x96)

        settings = await asyncio.wait_for(
            q_settings.get(),
            timeout=12
        )

        soc100_raw = int.from_bytes(
            settings[30:34],
            "little"
        )

        print()
        print(
            "SOC100 setting:",
            f"{soc100_raw / 1000:.3f} V/cell"
        )

        # Посмотрим SOC несколько циклов
        for n in range(1, 6):
            await clear(q_live)

            await send(client, ch, 0x96)

            live = await asyncio.wait_for(
                q_live.get(),
                timeout=12
            )

            print_live(f"AFTER #{n}", live)

            await asyncio.sleep(2)

        await client.stop_notify(nch)


asyncio.run(main())
