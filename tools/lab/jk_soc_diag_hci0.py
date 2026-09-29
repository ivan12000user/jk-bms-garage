import asyncio
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
HEADER = bytes.fromhex("55 AA EB 90")

rx = bytearray()
q_settings = asyncio.Queue()
q_cell = asyncio.Queue()


def cmd(x):
    f = bytearray(20)
    f[0:4] = bytes.fromhex("AA 55 90 EB")
    f[4] = x
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
            q_cell.put_nowait(f)


async def main():
    dev = await BleakScanner.find_device_by_address(
        MAC, timeout=15, adapter=ADAPTER
    )

    if dev is None:
        raise SystemExit("BMS not found")

    async with BleakClient(
        dev, adapter=ADAPTER, timeout=20
    ) as client:

        ch = None
        for s in client.services:
            for c in s.characteristics:
                if c.uuid.lower() == FFE1:
                    ch = c
                    break

        if ch is None:
            raise SystemExit("FFE1 not found")

        await client.start_notify(ch, notify)

        await client.write_gatt_char(ch, cmd(0x97), response=False)
        await asyncio.sleep(1)

        await client.write_gatt_char(ch, cmd(0x96), response=False)

        settings = await asyncio.wait_for(q_settings.get(), 10)
        cell = await asyncio.wait_for(q_cell.get(), 10)

        soc100 = int.from_bytes(settings[30:34], "little") / 1000
        soc0 = int.from_bytes(settings[34:38], "little") / 1000

        cells = [
            int.from_bytes(cell[6+i*2:8+i*2], "little") / 1000
            for i in range(4)
        ]

        voltage = int.from_bytes(cell[150:154], "little") / 1000
        current = int.from_bytes(
            cell[158:162], "little", signed=True
        ) / 1000

        soc = cell[173]
        remain = int.from_bytes(cell[174:178], "little") / 1000
        capacity = int.from_bytes(cell[178:182], "little") / 1000
        soh = cell[190]

        print()
        print("===== JK SOC DIAGNOSTICS =====")
        print("Cells:", " / ".join(f"{v:.3f}" for v in cells), "V")
        print(f"Pack voltage:       {voltage:.3f} V")
        print(f"Current:            {current:+.3f} A")
        print(f"SOC:                {soc} %")
        print(f"Remaining capacity: {remain:.3f} Ah")
        print(f"Nominal capacity:   {capacity:.3f} Ah")
        print(f"SOH:                {soh} %")
        print(f"SOC 100% voltage:   {soc100:.3f} V/cell")
        print(f"SOC 0% voltage:     {soc0:.3f} V/cell")

        await client.stop_notify(ch)


asyncio.run(main())
