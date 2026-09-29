import asyncio
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"

HEADER = bytes.fromhex("55 AA EB 90")

rx = bytearray()
settings_queue = asyncio.Queue()


def make_cmd(cmd):
    f = bytearray(20)

    f[0:4] = bytes.fromhex("AA 55 90 EB")
    f[4] = cmd
    f[5] = 0x00

    # bytes 6..18 = 0
    f[19] = sum(f[:19]) & 0xFF

    return bytes(f)


def on_notify(sender, data):
    global rx

    print(
        "RX chunk:",
        len(data),
        "bytes:",
        " ".join(f"{b:02X}" for b in data[:12]),
        "..." if len(data) > 12 else ""
    )

    rx.extend(data)

    while True:
        pos = rx.find(HEADER)

        if pos < 0:
            # оставляем последние 3 байта на случай,
            # если заголовок разделён между notification
            if len(rx) > 3:
                del rx[:-3]
            return

        if pos > 0:
            del rx[:pos]

        # Для JK02 settings frame = 300 байт
        if len(rx) < 300:
            return

        frame = bytes(rx[:300])
        del rx[:300]

        calc = sum(frame[:299]) & 0xFF
        stored = frame[299]

        print()
        print("FULL FRAME:")
        print("type       =", hex(frame[4]))
        print("crc stored =", hex(stored))
        print("crc calc   =", hex(calc))

        if calc != stored:
            print("BAD CRC")
            continue

        if frame[4] == 0x01:
            settings_queue.put_nowait(frame)


async def main():
    print("Searching", MAC, "via", ADAPTER)

    dev = await BleakScanner.find_device_by_address(
        MAC,
        timeout=15.0,
        adapter=ADAPTER
    )

    if dev is None:
        raise SystemExit("BMS not found via hci0")

    print("Found:", dev)

    async with BleakClient(
        dev,
        adapter=ADAPTER,
        timeout=20.0
    ) as client:

        chars = []

        for service in client.services:
            for ch in service.characteristics:
                if ch.uuid.lower() == FFE1:
                    chars.append(ch)

        if not chars:
            raise RuntimeError("FFE1 not found")

        for ch in chars:
            print(
                "FFE1:",
                "handle=", ch.handle,
                "properties=", ch.properties
            )

        notify_ch = next(
            (x for x in chars if "notify" in x.properties),
            None
        )

        write_ch = next(
            (
                x for x in chars
                if "write-without-response" in x.properties
            ),
            None
        )

        if notify_ch is None:
            raise RuntimeError("Notify FFE1 not found")

        if write_ch is None:
            raise RuntimeError(
                "Write-without-response FFE1 not found"
            )

        print("NOTIFY HANDLE:", notify_ch.handle)
        print("WRITE  HANDLE:", write_ch.handle)

        await client.start_notify(
            notify_ch,
            on_notify
        )

        await asyncio.sleep(0.5)

        cmd = make_cmd(0x96)

        print(
            "TX SETTINGS REQUEST:",
            " ".join(f"{b:02X}" for b in cmd)
        )

        await client.write_gatt_char(
            write_ch,
            cmd,
            response=False
        )

        try:
            frame = await asyncio.wait_for(
                settings_queue.get(),
                timeout=12.0
            )
        except asyncio.TimeoutError:
            raise SystemExit(
                "TIMEOUT: valid settings frame not received"
            )

        raw = frame[138:142]

        value = int.from_bytes(
            raw,
            byteorder="little",
            signed=False
        )

        print()
        print("================================")
        print(
            "Start balance RAW:",
            " ".join(f"{b:02X}" for b in raw)
        )
        print(
            "Start balance voltage:",
            f"{value / 1000:.3f} V"
        )
        print("================================")

        await client.stop_notify(notify_ch)


asyncio.run(main())
