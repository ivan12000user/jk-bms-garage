import asyncio
import time
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


async def find_bms(attempts=6):
    for n in range(1, attempts + 1):
        print(f"Search attempt {n}/{attempts}")

        dev = await BleakScanner.find_device_by_address(
            MAC,
            timeout=10,
            adapter=ADAPTER
        )

        if dev:
            return dev

        await asyncio.sleep(3)

    return None


async def clear(q):
    while not q.empty():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            break


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

    # нормальная инициализация JK
    await send(client, ch, 0x97)
    await asyncio.sleep(1)

    return client, ch, nch


async def read_state(client, ch):
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

    soc100 = int.from_bytes(
        settings[30:34],
        "little"
    )

    pack = int.from_bytes(
        live[150:154],
        "little"
    ) / 1000

    current = int.from_bytes(
        live[158:162],
        "little",
        signed=True
    ) / 1000

    soc = live[173]

    remain = int.from_bytes(
        live[174:178],
        "little"
    ) / 1000

    return soc100, pack, current, soc, remain


async def main():

    print("========================================")
    print("SESSION 1 - CHECK AND RESTART")
    print("========================================")

    client, ch, nch = await connect()

    soc100, pack, current, soc, remain = await read_state(
        client, ch
    )

    print()
    print(f"Pack:      {pack:.3f} V")
    print(f"Current:   {current:+.3f} A")
    print(f"SOC:       {soc}%")
    print(f"Remaining: {remain:.3f} Ah")
    print(f"SOC100:    {soc100/1000:.3f} V")

    #
    # Не перезапускаем BMS, если она реально
    # сейчас заметно заряжается/разряжается.
    #
    if abs(current) > 0.30:
        print()
        print("ABORT:")
        print("Battery current is above 0.30 A.")
        print("Leave PSU ON and run again when current is near zero.")
        await client.stop_notify(nch)
        await client.disconnect()
        return

    print()
    print("===== SOFT RESTART BMS: register 0x66 =====")

    # Официальная JK02_32S команда Restart
    await send(
        client,
        ch,
        0x66,
        0,
        0
    )

    #
    # Соединение должно оборваться само.
    #
    await asyncio.sleep(3)

    try:
        if client.is_connected:
            await client.disconnect()
    except Exception:
        pass

    print()
    print("Waiting for BMS to reboot...")
    await asyncio.sleep(8)

    print()
    print("========================================")
    print("SESSION 2 - AFTER RESTART")
    print("========================================")

    client, ch, nch = await connect()

    soc100, pack, current, soc, remain = await read_state(
        client, ch
    )

    print()
    print(f"After restart SOC100 = {soc100/1000:.3f} V")
    print(f"Pack                = {pack:.3f} V")
    print(f"Current             = {current:+.3f} A")
    print(f"SOC                 = {soc}%")
    print(f"Remaining           = {remain:.3f} Ah")

    print()
    print("===== RESTORE SOC100 -> 3.590 V =====")

    await send(
        client,
        ch,
        0x07,
        3590,
        4
    )

    #
    # После записи ничего больше в этой
    # BLE-сессии не пишем.
    #
    await asyncio.sleep(3)

    await client.stop_notify(nch)
    await client.disconnect()

    await asyncio.sleep(5)

    print()
    print("========================================")
    print("SESSION 3 - VERIFY")
    print("========================================")

    client, ch, nch = await connect()

    soc100, pack, current, soc, remain = await read_state(
        client, ch
    )

    print()
    print(f"SOC100 READBACK = {soc100/1000:.3f} V")

    if soc100 == 3590:
        print()
        print("SUCCESS: SOC100 restored to 3.590 V")
        print("The BMS write lock was cleared by restart.")
    else:
        print()
        print(
            "FAILED: SOC100 remains "
            f"{soc100/1000:.3f} V"
        )

    await client.stop_notify(nch)
    await client.disconnect()


asyncio.run(main())
