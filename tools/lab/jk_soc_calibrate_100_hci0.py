import asyncio
import time
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"

HEADER = bytes.fromhex("55 AA EB 90")

rx = bytearray()
cell_queue = asyncio.Queue()


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


def notify(sender, data):
    global rx

    rx.extend(data)

    while True:
        p = rx.find(HEADER)

        if p < 0:
            if len(rx) > 3:
                del rx[:-3]
            return

        if p > 0:
            del rx[:p]

        if len(rx) < 300:
            return

        f = bytes(rx[:300])
        del rx[:300]

        crc_calc = sum(f[:299]) & 0xff
        crc_stored = f[299]

        if crc_calc != crc_stored:
            continue

        # 0x02 = live/cell info
        if f[4] == 0x02:
            cell_queue.put_nowait(f)


async def send(client, ch, address, value=0, length=0):
    f = make_frame(address, value, length)

    print(
        "TX:",
        " ".join(f"{b:02X}" for b in f)
    )

    await client.write_gatt_char(
        ch,
        f,
        response=False
    )


def show_state(title, f):
    cells = [
        int.from_bytes(f[6+i*2:8+i*2], "little") / 1000
        for i in range(4)
    ]

    voltage = int.from_bytes(
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

    capacity = int.from_bytes(
        f[178:182], "little"
    ) / 1000

    print()
    print("================================")
    print(title)
    print(
        "Cells:",
        " / ".join(f"{x:.3f}" for x in cells),
        "V"
    )
    print(f"Pack:       {voltage:.3f} V")
    print(f"Current:    {current:+.3f} A")
    print(f"SOC:        {soc} %")
    print(f"Remaining:  {remain:.3f} Ah")
    print(f"Capacity:   {capacity:.3f} Ah")
    print("================================")

    return soc, remain, capacity


async def get_next_cell_frame(timeout=10):
    while not cell_queue.empty():
        try:
            cell_queue.get_nowait()
        except asyncio.QueueEmpty:
            break

    return await asyncio.wait_for(
        cell_queue.get(),
        timeout=timeout
    )


async def main():
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

        if notify_ch is None or write_ch is None:
            raise RuntimeError("Required FFE1 not found")

        print("HANDLE:", write_ch.handle)

        await client.start_notify(
            notify_ch,
            notify
        )

        await asyncio.sleep(0.7)

        #
        # Инициализация JK BLE-сессии
        #
        print()
        print("===== INIT 0x97 =====")
        await send(
            client,
            write_ch,
            0x97
        )

        #
        # На этой JK после 0x97 приходит Device Info (type 0x03).
        # Для получения следующего цикла данных явно отправляем 0x96.
        #
        await asyncio.sleep(1)

        while not cell_queue.empty():
            cell_queue.get_nowait()

        print()
        print("===== REQUEST DATA 0x96 =====")

        await send(
            client,
            write_ch,
            0x96
        )

        before = await asyncio.wait_for(
            cell_queue.get(),
            timeout=12
        )

        soc_before, rem_before, cap = show_state(
            "BEFORE CALIBRATION",
            before
        )

        #
        # SOC calibration = 100 %
        #
        print()
        print("===== SOC CALIBRATION -> 100% =====")

        # JK02_32S:
        # register 0x6E
        # length = 1
        # value  = 100 (0x64)
        await send(
            client,
            write_ch,
            0x6E,
            100,
            1
        )

        await asyncio.sleep(1)

        #
        # Удаляем старые live-кадры и запрашиваем
        # новый цикл данных уже после калибровки.
        #
        while not cell_queue.empty():
            cell_queue.get_nowait()

        print()
        print("===== REFRESH AFTER CALIBRATION 0x96 =====")

        await send(
            client,
            write_ch,
            0x96
        )

        after = await asyncio.wait_for(
            cell_queue.get(),
            timeout=12
        )

        soc_after, rem_after, cap_after = show_state(
            "AFTER CALIBRATION",
            after
        )

        print()
        print("================================")

        if soc_after == 100:
            print("RESULT: SOC CALIBRATION SUCCESS")
        else:
            print(
                "RESULT: SOC DID NOT BECOME 100%"
            )

        print(
            f"SOC: {soc_before}% -> {soc_after}%"
        )

        print(
            f"Remaining: "
            f"{rem_before:.3f} -> {rem_after:.3f} Ah"
        )

        print("================================")

        await client.stop_notify(
            notify_ch
        )


asyncio.run(main())
