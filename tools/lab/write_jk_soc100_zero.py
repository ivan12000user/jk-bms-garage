import asyncio
from bmslib.models.jikong import JKBt

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci1"

SOC100_OFFSET = 30

CMD97 = bytes.fromhex(
    "AA5590EB97000000000000000000000000000011"
)

CMD96 = bytes.fromhex(
    "AA5590EB96000000000000000000000000000010"
)

# 0x07, len=4, 3440 = 0x00000D70 LE
# bytes 10..18 = 00
# checksum = 0x02
WRITE_3440 = bytes.fromhex(
    "AA5590EB0704700D000000000000000000000002"
)

def read_u32(data, offset):
    return int.from_bytes(data[offset:offset+4], "little")

async def tx(bms, frame, name):
    print(f"TX {name}: {frame.hex(' ').upper()}")
    await bms.client.write_gatt_char(
        bms.char_handle_write,
        frame,
        response=False
    )

async def read_settings(bms, label):
    bms._resp_table.pop(0x01, None)

    await tx(bms, CMD96, "0x96")

    for _ in range(50):
        await asyncio.sleep(0.1)
        r = bms.debug_data().get("resp", {}).get(0x01)

        if r:
            buf, _ = r
            data = bytes(buf)

            if len(data) >= 142:
                soc100 = read_u32(data, SOC100_OFFSET)
                startbal = read_u32(data, 138)

                print(
                    f"{label}: SOC100={soc100} "
                    f"({soc100/1000:.3f} V), "
                    f"StartBalance={startbal} "
                    f"({startbal/1000:.3f} V)"
                )
                return soc100

    raise RuntimeError("No fresh settings response")

async def connect():
    bms = JKBt(
        MAC,
        name="garage_jk_bms",
        keep_alive=False,
        adapter=ADAPTER
    )

    await bms.connect(timeout=25)

    await tx(bms, CMD97, "0x97")
    await asyncio.sleep(1)

    return bms

async def main():
    bms = None

    try:
        print("===== CONNECT =====")
        bms = await connect()

        before = await read_settings(bms, "BEFORE")

        if before != 3590:
            raise RuntimeError(
                f"SAFETY STOP: expected SOC100=3590, got {before}"
            )

        print()
        print("===== WRITE SOC100 3.440 V =====")
        await tx(bms, WRITE_3440, "0x07 = 3440")

        await asyncio.sleep(1)
        r1 = await read_settings(bms, "AFTER 1 SEC")

        await asyncio.sleep(3)
        r2 = await read_settings(bms, "AFTER 4 SEC")

        print()
        print("===== RESULT =====")

        if 3440 in (r1, r2):
            print("SUCCESS: SOC100 CHANGED TO 3.440 V")
            print("NEW VALUE IS LEFT IN BMS")
        elif r1 == 3590 and r2 == 3590:
            print("FAILED: BMS ACK/transport worked but value stayed 3.590 V")
        else:
            print("WARNING: unexpected readback:", r1, r2)

    finally:
        if bms is not None:
            try:
                await bms.disconnect()
            except Exception:
                pass

asyncio.run(main())
