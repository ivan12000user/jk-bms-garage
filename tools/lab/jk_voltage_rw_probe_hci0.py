import asyncio
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
HEADER = bytes.fromhex("55 AA EB 90")

PARAMS = [
    ("OVPR",   0x05, 22),
    ("SOC100", 0x07, 30),
    ("RCV",    0x09, 38),
]

rx = bytearray()
q_settings = asyncio.Queue()


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


async def clear():
    while not q_settings.empty():
        q_settings.get_nowait()


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


async def read_settings(client, ch):
    await clear()

    await send(client, ch, 0x96)

    return await asyncio.wait_for(
        q_settings.get(),
        timeout=12
    )


def get_value(f, offset):
    return int.from_bytes(
        f[offset:offset+4],
        "little"
    )


async def write_and_read(client, ch, name, reg, offset, value):
    print(
        f"TRY {name} = {value/1000:.3f} V"
    )

    await send(
        client,
        ch,
        reg,
        value,
        4
    )

    await asyncio.sleep(1.5)

    f = await read_settings(client, ch)
    actual = get_value(f, offset)

    print(
        f"READBACK {name} = {actual/1000:.3f} V"
    )

    return actual


async def main():
    dev = None

    for attempt in range(1, 5):
        print(
            f"Searching via {ADAPTER}, "
            f"attempt {attempt}/4..."
        )

        dev = await BleakScanner.find_device_by_address(
            MAC,
            timeout=12,
            adapter=ADAPTER
        )

        if dev:
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
            for s in client.services
            for c in s.characteristics
            if c.uuid.lower() == FFE1
        ]

        write_ch = next(
            c for c in chars
            if "write-without-response" in c.properties
        )

        notify_ch = next(
            c for c in chars
            if "notify" in c.properties
        )

        await client.start_notify(
            notify_ch,
            notify
        )

        await asyncio.sleep(0.7)

        print("===== INIT =====")
        await send(client, write_ch, 0x97)
        await asyncio.sleep(1)

        f = await read_settings(client, write_ch)

        originals = {
            name: get_value(f, offset)
            for name, reg, offset in PARAMS
        }

        print()
        print("===== ORIGINAL =====")
        for name, _, _ in PARAMS:
            print(
                f"{name:7s} "
                f"{originals[name]/1000:.3f} V"
            )

        for name, reg, offset in PARAMS:
            original = originals[name]

            print()
            print(
                "========================================"
            )
            print(
                f"PROBE {name}, original "
                f"{original/1000:.3f} V"
            )
            print(
                "========================================"
            )

            #
            # +1 mV
            #
            up = original + 1

            actual = await write_and_read(
                client,
                write_ch,
                name,
                reg,
                offset,
                up
            )

            if actual == up:
                print("+1 mV: ACCEPTED")

                print("RESTORE ORIGINAL")
                restored = await write_and_read(
                    client,
                    write_ch,
                    name,
                    reg,
                    offset,
                    original
                )

                if restored != original:
                    raise SystemExit(
                        f"ERROR: failed to restore {name}"
                    )
            else:
                print("+1 mV: REJECTED")

            #
            # -1 mV
            #
            down = original - 1

            actual = await write_and_read(
                client,
                write_ch,
                name,
                reg,
                offset,
                down
            )

            if actual == down:
                print("-1 mV: ACCEPTED")

                print("RESTORE ORIGINAL")
                restored = await write_and_read(
                    client,
                    write_ch,
                    name,
                    reg,
                    offset,
                    original
                )

                if restored != original:
                    raise SystemExit(
                        f"ERROR: failed to restore {name}"
                    )
            else:
                print("-1 mV: REJECTED")

        #
        # Final verification
        #
        f = await read_settings(
            client,
            write_ch
        )

        print()
        print("===== FINAL - MUST MATCH ORIGINAL =====")

        all_ok = True

        for name, reg, offset in PARAMS:
            v = get_value(f, offset)

            print(
                f"{name:7s} {v/1000:.3f} V"
            )

            if v != originals[name]:
                all_ok = False

        if all_ok:
            print("FINAL RESULT: ORIGINAL VALUES RESTORED")
        else:
            print("WARNING: FINAL VALUES DIFFER")

        await client.stop_notify(
            notify_ch
        )


asyncio.run(main())
