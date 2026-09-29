import asyncio
import time
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"

RX_HEADER = bytes.fromhex("55 AA EB 90")

rx = bytearray()
settings_queue = asyncio.Queue()

phase = "CONNECT"


def make_frame(address, value=0, length=0):
    f = bytearray(20)

    f[0:4] = bytes.fromhex("AA 55 90 EB")
    f[4] = address
    f[5] = length

    f[6] = (value >> 0) & 0xff
    f[7] = (value >> 8) & 0xff
    f[8] = (value >> 16) & 0xff
    f[9] = (value >> 24) & 0xff

    f[19] = sum(f[:19]) & 0xff
    return bytes(f)


def print_hex(prefix, data):
    print(
        prefix,
        " ".join(f"{b:02X}" for b in data)
    )


def on_notify(sender, data):
    global rx

    ts = time.strftime("%H:%M:%S")

    print(
        f"{ts} [{phase}] RX chunk {len(data):3d}:",
        " ".join(f"{b:02X}" for b in data)
    )

    # Отдельно отмечаем возможный 20-байтный ответ
    # на команду записи.
    if (
        len(data) == 20
        and data[:4] == bytes.fromhex("AA 55 90 EB")
    ):
        print_hex(
            f"{ts} [{phase}] *** COMMAND RESPONSE:",
            data
        )

    rx.extend(data)

    while True:
        pos = rx.find(RX_HEADER)

        if pos < 0:
            if len(rx) > 3:
                del rx[:-3]
            return

        if pos > 0:
            del rx[:pos]

        if len(rx) < 300:
            return

        frame = bytes(rx[:300])
        del rx[:300]

        crc_stored = frame[299]
        crc_calc = sum(frame[:299]) & 0xff

        print()
        print(
            f"{ts} [{phase}] FULL FRAME:",
            f"type=0x{frame[4]:02X}",
            f"crc={crc_calc:02X}/{crc_stored:02X}"
        )

        if crc_calc != crc_stored:
            print("BAD CRC")
            continue

        if frame[4] == 0x01:
            try:
                settings_queue.put_nowait(frame)
            except asyncio.QueueFull:
                pass


async def send(client, ch, address, value=0, length=0):
    f = make_frame(address, value, length)

    print()
    print_hex(
        f"{time.strftime('%H:%M:%S')} [{phase}] TX:",
        f
    )

    await client.write_gatt_char(
        ch,
        f,
        response=False
    )


async def get_settings(client, ch):
    # выбрасываем старые settings frames
    while not settings_queue.empty():
        try:
            settings_queue.get_nowait()
        except asyncio.QueueEmpty:
            break

    await send(client, ch, 0x96)

    frame = await asyncio.wait_for(
        settings_queue.get(),
        timeout=12
    )

    raw = frame[138:142]
    value = int.from_bytes(raw, "little")

    print(
        "Start balance RAW:",
        " ".join(f"{b:02X}" for b in raw)
    )
    print(
        "Start balance voltage:",
        f"{value / 1000:.3f} V"
    )

    return value


async def main():
    global phase

    print("Searching", MAC, "via", ADAPTER)

    dev = await BleakScanner.find_device_by_address(
        MAC,
        timeout=15,
        adapter=ADAPTER
    )

    if dev is None:
        raise SystemExit("BMS not found via hci0")

    print("Found:", dev)

    async with BleakClient(
        dev,
        adapter=ADAPTER,
        timeout=20
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
            raise RuntimeError("Notify characteristic not found")

        if write_ch is None:
            raise RuntimeError(
                "Write-without-response characteristic not found"
            )

        print("NOTIFY HANDLE:", notify_ch.handle)
        print("WRITE  HANDLE:", write_ch.handle)

        phase = "ENABLE_NOTIFY"

        await client.start_notify(
            notify_ch,
            on_notify
        )

        await asyncio.sleep(1)

        # Именно это делает esphome-jk-bms
        # после регистрации notify.
        phase = "DEVICE_INFO"
        await send(client, write_ch, 0x97)

        await asyncio.sleep(2)

        phase = "READ_BEFORE"
        before = await get_settings(
            client,
            write_ch
        )

        print()
        print("================================")
        print(
            "BEFORE:",
            f"{before / 1000:.3f} V"
        )
        print("================================")

        await asyncio.sleep(1)

        # 3410 mV = 3.410 V
        phase = "WRITE_3410"
        await send(
            client,
            write_ch,
            0x22,
            3410,
            4
        )

        # Важно: ждём возможный ACK/ошибку JK.
        await asyncio.sleep(3)

        phase = "READ_AFTER"
        after = await get_settings(
            client,
            write_ch
        )

        print()
        print("================================")
        print(
            "BEFORE:",
            f"{before / 1000:.3f} V"
        )
        print(
            "AFTER :",
            f"{after / 1000:.3f} V"
        )

        if after == 3410:
            print("RESULT: WRITE SUCCESS")
        elif after == before:
            print("RESULT: WRITE IGNORED")
        else:
            print("RESULT: VALUE CHANGED TO UNEXPECTED VALUE")

        print("================================")

        phase = "DONE"

        await client.stop_notify(
            notify_ch
        )


asyncio.run(main())
