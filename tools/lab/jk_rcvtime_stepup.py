import asyncio
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
HEADER = bytes.fromhex("55 AA EB 90")

TARGETS = [2, 3, 4, 5]   # 0.2, 0.3, 0.4, 0.5 h

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


async def clear():
    while not q_info.empty():
        try:
            q_info.get_nowait()
        except asyncio.QueueEmpty:
            break


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


async def read_time(client, ch):
    await clear()

    await send(
        client,
        ch,
        0x97,
        0,
        0
    )

    f = await asyncio.wait_for(
        q_info.get(),
        timeout=12
    )

    return f[266]


async def close(client, nch):
    try:
        await client.stop_notify(nch)
    except Exception:
        pass

    try:
        await client.disconnect()
    except Exception:
        pass


async def restart_bms():

    client, ch, nch = await connect()

    current = await read_time(
        client,
        ch
    )

    print(
        f"Before restart: RCV Time = "
        f"{current/10:.1f} h"
    )

    print("SOFT RESTART")

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

    await asyncio.sleep(8)


async def verify(expected):

    client, ch, nch = await connect()

    actual = await read_time(
        client,
        ch
    )

    print(
        f"READBACK = {actual/10:.1f} h"
    )

    await close(client, nch)

    return actual == expected


async def write_one(target):

    print()
    print()
    print("########################################")
    print(
        f"TARGET RCV TIME = {target/10:.1f} h"
    )
    print("########################################")

    #
    # Proven sequence:
    # restart -> new connection -> one write
    #
    await restart_bms()

    client, ch, nch = await connect()

    before = await read_time(
        client,
        ch
    )

    print(
        f"Before write = {before/10:.1f} h"
    )

    if before == target:
        print("Already at target")
        await close(client, nch)
        return True

    print(
        f"WRITE {before/10:.1f} -> "
        f"{target/10:.1f} h"
    )

    await send(
        client,
        ch,
        0xB3,
        target,
        1
    )

    #
    # No more writes in this session.
    #
    await asyncio.sleep(3)

    await close(client, nch)

    await asyncio.sleep(5)

    print("VERIFY IN NEW SESSION")

    ok = await verify(target)

    if ok:
        print(
            f"SUCCESS: RCV Time = "
            f"{target/10:.1f} h"
        )
    else:
        print(
            f"REJECTED: target "
            f"{target/10:.1f} h"
        )

    return ok


async def main():

    client, ch, nch = await connect()

    start = await read_time(
        client,
        ch
    )

    print()
    print(
        f"START RCV Time = {start/10:.1f} h"
    )

    await close(client, nch)

    #
    # Starting point should currently be 0.1 h.
    # Skip targets already passed.
    #
    for target in TARGETS:

        if target <= start:
            continue

        ok = await write_one(target)

        if not ok:
            print()
            print("========================================")
            print("STOP: BMS rejected this increment")
            print("No further RCV Time writes attempted")
            print("========================================")
            return

        start = target

    print()
    print("****************************************")
    print("RCV TIME STEP-UP COMPLETED")
    print(f"FINAL = {start/10:.1f} h")
    print("****************************************")


asyncio.run(main())
