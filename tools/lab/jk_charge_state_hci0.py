import asyncio
import time
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
HEADER = bytes.fromhex("55 AA EB 90")

rx = bytearray()
q_live = asyncio.Queue()


def frame(reg):
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

        if f[4] == 0x02:
            q_live.put_nowait(f)


async def main():

    dev = await BleakScanner.find_device_by_address(
        MAC,
        timeout=15,
        adapter=ADAPTER
    )

    if not dev:
        raise SystemExit("BMS not found")

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

        await client.write_gatt_char(
            ch,
            frame(0x97),
            response=False
        )

        await asyncio.sleep(1)

        await client.write_gatt_char(
            ch,
            frame(0x96),
            response=False
        )

        print(
            "time      pack      current   SOC   "
            "remain      state        timer"
        )

        end = time.monotonic() + 20

        while time.monotonic() < end:

            try:
                f = await asyncio.wait_for(
                    q_live.get(),
                    timeout=5
                )
            except asyncio.TimeoutError:
                await client.write_gatt_char(
                    ch,
                    frame(0x96),
                    response=False
                )
                continue

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

            elapsed = int.from_bytes(
                f[278:280], "little"
            )

            sid = f[280]

            state = {
                0: "Bulk",
                1: "Absorption",
                2: "Float",
            }.get(sid, f"Unknown({sid})")

            print(
                time.strftime("%H:%M:%S"),
                f"{pack:8.3f}V",
                f"{current:+8.3f}A",
                f"{soc:3d}%",
                f"{remain:7.3f}Ah",
                f"{state:12s}",
                f"{elapsed:5d}s"
            )

        await client.stop_notify(nch)


asyncio.run(main())
