import asyncio
import time
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
HEADER = bytes.fromhex("55 AA EB 90")

rx = bytearray()


def cmd(reg):
    f = bytearray(20)
    f[0:4] = bytes.fromhex("AA 55 90 EB")
    f[4] = reg
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

        if f[4] != 0x02:
            continue

        cells = [
            int.from_bytes(
                f[6+i*2:8+i*2], "little"
            ) / 1000
            for i in range(4)
        ]

        pack = int.from_bytes(
            f[150:154], "little"
        ) / 1000

        current = int.from_bytes(
            f[158:162],
            "little",
            signed=True
        ) / 1000

        soc = f[173]

        remain = int.from_bytes(
            f[174:178], "little"
        ) / 1000

        capacity = int.from_bytes(
            f[178:182], "little"
        ) / 1000

        print(
            time.strftime("%H:%M:%S"),
            f"U={pack:6.3f} V",
            f"I={current:+7.3f} A",
            f"SOC={soc:3d}%",
            f"Remain={remain:6.3f}/{capacity:.3f} Ah",
            f"cells={'/'.join(f'{v:.3f}' for v in cells)}",
            flush=True
        )


async def main():
    print("Searching BMS via hci0...")

    dev = await BleakScanner.find_device_by_address(
        MAC,
        timeout=20,
        adapter=ADAPTER
    )

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
            if "write-without-response" in c.properties
        )

        nch = next(
            c for c in chars
            if "notify" in c.properties
        )

        await client.start_notify(nch, notify)

        # Инициализация
        await client.write_gatt_char(
            ch, cmd(0x97), response=False
        )

        await asyncio.sleep(1)

        # Запуск потока данных
        await client.write_gatt_char(
            ch, cmd(0x96), response=False
        )

        print()
        print("===== JK LIVE SOC WATCH =====")
        print("Ctrl+C для выхода")
        print()

        while True:
            await asyncio.sleep(30)

            # на случай прекращения телеметрии
            await client.write_gatt_char(
                ch, cmd(0x96), response=False
            )


asyncio.run(main())
