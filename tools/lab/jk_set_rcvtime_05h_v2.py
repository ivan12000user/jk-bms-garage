import asyncio
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
HEADER = bytes.fromhex("55 AA EB 90")

TARGET = 5       # 5 * 0.1 h = 0.5 h

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
    print("Found:", dev)

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
    await asyncio.sleep(0.7)

    return client, ch, nch


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


async def read_rcv_time(client, ch):
    while not q_info.empty():
        try:
            q_info.get_nowait()
        except asyncio.QueueEmpty:
            break

    await send(client, ch, 0x97)

    info = await asyncio.wait_for(
        q_info.get(),
        timeout=12
    )

    return info[266]


async def close(client, nch):
    try:
        await client.stop_notify(nch)
    except Exception:
        pass

    try:
        await client.disconnect()
    except Exception:
        pass


async def main():

    #
    # SESSION 1
    # ONLY SOFT RESTART
    #
    print("========================================")
    print("SESSION 1: UNLOCK BY SOFT RESTART")
    print("========================================")

    client, ch, nch = await connect()

    before = await read_rcv_time(client, ch)

    print(
        f"RCV Time BEFORE restart = "
        f"{before/10:.1f} h"
    )

    print()
    print("SOFT RESTART 0x66")

    await send(
        client,
        ch,
        0x66,
        0,
        0
    )

    await asyncio.sleep(3)

    try:
        await client.disconnect()
    except Exception:
        pass

    print("Waiting for BMS reboot...")
    await asyncio.sleep(8)

    #
    # SESSION 2
    # EXACTLY ONE SETTINGS WRITE
    #
    print()
    print("========================================")
    print("SESSION 2: ONE WRITE ONLY")
    print("========================================")

    client, ch, nch = await connect()

    current = await read_rcv_time(client, ch)

    print(
        f"RCV Time BEFORE write = "
        f"{current/10:.1f} h"
    )

    print()
    print("WRITE RCV Time -> 0.5 h")

    await send(
        client,
        ch,
        0xB3,
        TARGET,
        1
    )

    # Никаких других settings-write.
    await asyncio.sleep(3)

    await close(client, nch)

    #
    # SESSION 3
    # READ ONLY
    #
    await asyncio.sleep(5)

    print()
    print("========================================")
    print("SESSION 3: VERIFY ONLY")
    print("========================================")

    client, ch, nch = await connect()

    result = await read_rcv_time(client, ch)

    print()
    print(
        f"RCV Time READBACK = "
        f"{result/10:.1f} h"
    )

    if result == TARGET:
        print()
        print("***************************************")
        print("SUCCESS: RCV Time = 0.5 h")
        print("***************************************")
    else:
        print()
        print(
            "FAILED: RCV Time remains "
            f"{result/10:.1f} h"
        )

    await close(client, nch)


asyncio.run(main())
