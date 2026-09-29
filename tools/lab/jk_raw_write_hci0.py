import asyncio
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"

# JK02_32S:
# register 0x22 = Balancing start voltage
# 3.410 V * 1000 = 3410 = 0x00000D52
FRAME = bytearray(20)

FRAME[0:4] = bytes.fromhex("AA5590EB")
FRAME[4] = 0x22
FRAME[5] = 0x04

value = 3410
FRAME[6] = (value >> 0)  & 0xFF
FRAME[7] = (value >> 8)  & 0xFF
FRAME[8] = (value >> 16) & 0xFF
FRAME[9] = (value >> 24) & 0xFF

FRAME[19] = sum(FRAME[:19]) & 0xFF


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

        candidates = []

        for service in client.services:
            for ch in service.characteristics:
                if ch.uuid.lower() == FFE1:
                    candidates.append(ch)

        if not candidates:
            raise RuntimeError("FFE1 not found")

        for ch in candidates:
            print(
                "FFE1:",
                "handle=", ch.handle,
                "properties=", ch.properties
            )

        # Предпочитаем именно Write Without Response
        ch = next(
            (
                x for x in candidates
                if "write-without-response" in x.properties
            ),
            None
        )

        if ch is None:
            raise RuntimeError(
                "FFE1 with write-without-response not found"
            )

        print("USING HANDLE:", ch.handle)
        print(
            "TX:",
            " ".join(f"{b:02X}" for b in FRAME)
        )

        # КЛЮЧЕВОЕ ОТЛИЧИЕ:
        await client.write_gatt_char(
            ch,
            bytes(FRAME),
            response=False
        )

        print("WRITE WITHOUT RESPONSE SENT")

        await asyncio.sleep(2)


asyncio.run(main())
