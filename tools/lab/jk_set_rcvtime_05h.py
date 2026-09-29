import asyncio
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
HEADER = bytes.fromhex("55 AA EB 90")

rx = bytearray()
q_info = asyncio.Queue()


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

        if f[4] == 0x03:
            q_info.put_nowait(f)


async def find_bms():
    for n in range(1, 7):
        print(f"Search attempt {n}/6")

        dev = await BleakScanner.find_device_by_address(
            MAC,
            timeout=10,
            adapter=ADAPTER
        )

        if dev:
            return dev

        await asyncio.sleep(3)

    raise RuntimeError("BMS not found")


async def connect():
    dev = await find_bms()

    client = BleakClient(
        dev,
        adapter=ADAPTER,
        timeout=30
    )

    await client.connect()

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

    return client, ch, nch


async def read_time(client, ch):
    while not q_info.empty():
        q_info.get_nowait()

    await client.write_gatt_char(
        ch,
        frame(0x97),
        response=False
    )

    f = await asyncio.wait_for(
        q_info.get(),
        timeout=12
    )

    return f[266]


async def main():

    print("===== SESSION 1: WRITE =====")

    client, ch, nch = await connect()

    old = await read_time(client, ch)

    print(f"RCV Time BEFORE = {old/10:.1f} h")

    # 5 * 0.1 h = 0.5 h
    tx = frame(0xB3, 5, 1)

    print(
        "TX:",
        " ".join(f"{x:02X}" for x in tx)
    )

    await client.write_gatt_char(
        ch,
        tx,
        response=False
    )

    await asyncio.sleep(3)

    await client.disconnect()

    await asyncio.sleep(3)

    print()
    print("===== SOFT RESTART =====")

    client, ch, nch = await connect()

    await client.write_gatt_char(
        ch,
        frame(0x66),
        response=False
    )

    await asyncio.sleep(4)

    try:
        await client.disconnect()
    except Exception:
        pass

    await asyncio.sleep(8)

    print()
    print("===== VERIFY =====")

    client, ch, nch = await connect()

    new = await read_time(client, ch)

    print(f"RCV Time READBACK = {new/10:.1f} h")

    if new == 5:
        print("SUCCESS: RCV Time = 0.5 h")
    else:
        print("FAILED")

    await client.disconnect()


asyncio.run(main())
