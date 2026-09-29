#!/usr/bin/env python3

import asyncio
import sys
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci1"

FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
REGISTER_SOC100 = 0x07

def make_frame(voltage):
    mv = round(voltage * 1000)

    frame = bytearray(20)
    frame[0:4] = bytes.fromhex("AA 55 90 EB")
    frame[4] = REGISTER_SOC100
    frame[5] = 4
    frame[6:10] = mv.to_bytes(4, "little", signed=False)
    frame[19] = sum(frame[:19]) & 0xFF

    return bytes(frame)

async def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: write_jk_soc100.py VOLTAGE")

    target = float(sys.argv[1])

    if not 3.30 <= target <= 3.60:
        raise SystemExit("Safety stop: allowed range in this script is 3.30..3.60 V")

    frame = make_frame(target)

    print(f"Target SOC-100% voltage: {target:.3f} V")
    print("Register: 0x07")
    print("TX:", frame.hex(" ").upper())

    dev = await BleakScanner.find_device_by_address(
        MAC,
        timeout=15.0,
        adapter=ADAPTER
    )

    if dev is None:
        raise SystemExit("BMS not found")

    async with BleakClient(
        dev,
        adapter=ADAPTER,
        timeout=15.0
    ) as client:

        candidates = []

        for service in client.services:
            for ch in service.characteristics:
                if ch.uuid.lower() == FFE1:
                    if "write-without-response" in ch.properties or "write" in ch.properties:
                        candidates.append(ch)

        if not candidates:
            raise RuntimeError("Writable FFE1 characteristic not found")

        ch = candidates[0]

        print(
            f"Write characteristic: handle={ch.handle}, "
            f"properties={ch.properties}"
        )

        await client.write_gatt_char(
            ch,
            frame,
            response=False
        )

        await asyncio.sleep(2)

    print("WRITE SENT")

asyncio.run(main())
