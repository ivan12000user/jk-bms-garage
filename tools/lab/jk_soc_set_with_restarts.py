import asyncio
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
HEADER = bytes.fromhex("55 AA EB 90")

# name, register, settings offset, target
STEPS = [
    ("OVPR", 0x05, 22, 3580),
]

rx = bytearray()
q_settings = asyncio.Queue()
q_live = asyncio.Queue()


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
            continue

        if f[4] == 0x01:
            q_settings.put_nowait(f)
        elif f[4] == 0x02:
            q_live.put_nowait(f)


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
        ch,
        f,
        response=False
    )


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

    return None


async def connect():
    dev = await find_bms()

    if dev is None:
        raise RuntimeError("BMS not found")

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

    # init JK session
    await send(client, ch, 0x97)
    await asyncio.sleep(1)

    return client, ch, nch


async def disconnect(client, nch):
    try:
        await client.stop_notify(nch)
    except Exception:
        pass

    try:
        await client.disconnect()
    except Exception:
        pass


async def read_all(client, ch):

    await clear(q_settings)
    await clear(q_live)

    await send(client, ch, 0x96)

    settings = await asyncio.wait_for(
        q_settings.get(),
        timeout=12
    )

    live = await asyncio.wait_for(
        q_live.get(),
        timeout=12
    )

    vals = {
        "OVPR": int.from_bytes(
            settings[22:26], "little"
        ),
        "SOC100": int.from_bytes(
            settings[30:34], "little"
        ),
        "RCV": int.from_bytes(
            settings[38:42], "little"
        ),
    }

    pack = int.from_bytes(
        live[150:154], "little"
    ) / 1000

    current = int.from_bytes(
        live[158:162],
        "little",
        signed=True
    ) / 1000

    soc = live[173]

    remain = int.from_bytes(
        live[174:178], "little"
    ) / 1000

    return vals, pack, current, soc, remain


def show(vals, pack, current, soc, remain):
    print()
    print("========================================")
    print(f"OVPR:      {vals['OVPR']/1000:.3f} V")
    print(f"SOC100:    {vals['SOC100']/1000:.3f} V")
    print(f"RCV:       {vals['RCV']/1000:.3f} V")
    print(f"Pack:      {pack:.3f} V")
    print(f"Current:   {current:+.3f} A")
    print(f"SOC:       {soc} %")
    print(f"Remaining: {remain:.3f} Ah")
    print("========================================")


async def soft_restart():
    print()
    print("===== SOFT RESTART =====")

    client, ch, nch = await connect()

    vals, pack, current, soc, remain = await read_all(
        client, ch
    )

    print(
        f"Before restart: U={pack:.3f} V "
        f"I={current:+.3f} A"
    )

    if abs(current) > 0.30:
        await disconnect(client, nch)

        raise RuntimeError(
            "ABORT: battery current above 0.30 A"
        )

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

    print("Restart command sent")
    await asyncio.sleep(8)


async def write_one(name, reg, offset, target):

    print()
    print()
    print("########################################")
    print(
        f"WRITE {name} -> {target/1000:.3f} V"
    )
    print("########################################")

    #
    # Every settings write gets a fresh
    # BMS restart first.
    #
    await soft_restart()

    client, ch, nch = await connect()

    vals, pack, current, soc, remain = await read_all(
        client, ch
    )

    current_value = vals[name]

    print(
        f"{name} BEFORE = "
        f"{current_value/1000:.3f} V"
    )

    if current_value == target:
        print("Already at target")
        await disconnect(client, nch)
        return True

    if abs(current) > 0.30:
        print(
            "ABORT: current is not near zero:",
            f"{current:+.3f} A"
        )
        await disconnect(client, nch)
        return False

    print()
    print("ONE SETTINGS WRITE:")

    await send(
        client,
        ch,
        reg,
        target,
        4
    )

    #
    # Do NOT issue another settings write
    # in this session.
    #
    await asyncio.sleep(3)

    await disconnect(client, nch)

    #
    # Completely new BLE session for verification.
    #
    await asyncio.sleep(5)

    client, ch, nch = await connect()

    vals, pack, current, soc, remain = await read_all(
        client, ch
    )

    actual = vals[name]

    print()
    print(
        f"{name} READBACK = "
        f"{actual/1000:.3f} V"
    )

    await disconnect(client, nch)

    if actual == target:
        print(
            f"SUCCESS: {name} accepted"
        )
        return True

    print(
        f"FAILED: {name} remained "
        f"{actual/1000:.3f} V"
    )

    return False


async def main():

    #
    # Initial snapshot
    #
    print("===== INITIAL STATE =====")

    client, ch, nch = await connect()

    vals, pack, current, soc, remain = await read_all(
        client, ch
    )

    show(vals, pack, current, soc, remain)

    await disconnect(client, nch)

    #
    # Sequential writes
    #
    for step in STEPS:

        ok = await write_one(*step)

        if not ok:
            print()
            print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            print("STOPPING: one parameter was rejected")
            print("No later parameter was changed")
            print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            return

    #
    # Final restart + final verification
    #
    await soft_restart()

    print()
    print("===== FINAL STATE =====")

    client, ch, nch = await connect()

    vals, pack, current, soc, remain = await read_all(
        client, ch
    )

    show(vals, pack, current, soc, remain)

    ok = (
        vals["OVPR"] == 3580
        and vals["SOC100"] == 3400
        and vals["RCV"] == 3440
    )

    if ok:
        print()
        print("***************************************")
        print("ALL THREE SETTINGS SUCCESSFULLY APPLIED")
        print("***************************************")
    else:
        print()
        print("FINAL SETTINGS DO NOT MATCH TARGET")

    await disconnect(client, nch)


asyncio.run(main())
