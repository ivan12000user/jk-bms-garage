import asyncio
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
HEADER = bytes.fromhex("55 AA EB 90")

REG = 0x07
TARGET = 3590
OFFSET = 30

rx = bytearray()
q_settings = asyncio.Queue()


def frame(reg, value=0, length=0):
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
            continue

        if f[4] == 0x01:
            q_settings.put_nowait(f)


async def find():
    for n in range(1, 5):
        print(f"Search attempt {n}/4")

        dev = await BleakScanner.find_device_by_address(
            MAC,
            timeout=12,
            adapter=ADAPTER
        )

        if dev:
            return dev

        await asyncio.sleep(3)

    return None


async def read_settings(client, ch):
    while not q_settings.empty():
        q_settings.get_nowait()

    f = frame(0x96)

    print(
        "TX:",
        " ".join(f"{x:02X}" for x in f)
    )

    await client.write_gatt_char(
        ch,
        f,
        response=False
    )

    return await asyncio.wait_for(
        q_settings.get(),
        timeout=12
    )


async def session(do_write):
    dev = await find()

    if dev is None:
        raise RuntimeError("BMS not found")

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

        # init
        await client.write_gatt_char(
            ch,
            frame(0x97),
            response=False
        )

        await asyncio.sleep(1)

        f = await read_settings(client, ch)

        current = int.from_bytes(
            f[OFFSET:OFFSET+4],
            "little"
        )

        print(
            f"SOC100 current = {current/1000:.3f} V"
        )

        if do_write:
            print(
                f"WRITE SOC100 -> {TARGET/1000:.3f} V"
            )

            tx = frame(
                REG,
                TARGET,
                4
            )

            print(
                "TX:",
                " ".join(f"{x:02X}" for x in tx)
            )

            await client.write_gatt_char(
                ch,
                tx,
                response=False
            )

            # Никаких других settings-write
            # в этой сессии.
            await asyncio.sleep(3)

        await client.stop_notify(nch)

        return current


async def main():
    print("===== SESSION 1: ONE WRITE ONLY =====")

    await session(True)

    # Полностью новая BLE-сессия
    await asyncio.sleep(5)

    print()
    print("===== SESSION 2: VERIFY ONLY =====")

    value = await session(False)

    print()
    print("================================")

    if value == TARGET:
        print("SUCCESS: SOC100 restored to 3.590 V")
    else:
        print(
            "FAILED: SOC100 is still "
            f"{value/1000:.3f} V"
        )

    print("================================")


asyncio.run(main())
