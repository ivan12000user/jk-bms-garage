import asyncio
from bmslib.models.jikong import JKBt

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci1"

OFFSET = 6

CMD97 = bytes.fromhex(
    "AA5590EB97000000000000000000000000000011"
)

CMD96 = bytes.fromhex(
    "AA5590EB96000000000000000000000000000010"
)

# 0x01 Smart Sleep Voltage
# 3510 = 0x00000DB6 LE
WRITE_3510 = bytes.fromhex(
    "AA5590EB0104B60D000000000000000000000042"
)

# 3500 = 0x00000DAC LE
WRITE_3500 = bytes.fromhex(
    "AA5590EB0104AC0D000000000000000000000038"
)

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

            if len(data) >= OFFSET + 4:
                value = int.from_bytes(
                    data[OFFSET:OFFSET+4],
                    "little"
                )

                print(
                    f"{label}: {value} = {value/1000:.3f} V"
                )
                return value

    raise RuntimeError("No fresh settings response")

async def main():
    bms = JKBt(
        MAC,
        name="garage_jk_bms",
        keep_alive=False,
        adapter=ADAPTER
    )

    try:
        await bms.connect(timeout=25)

        print("===== INIT =====")
        await tx(bms, CMD97, "0x97")
        await asyncio.sleep(1)

        before = await read_settings(bms, "BEFORE")

        if before != 3500:
            raise RuntimeError(
                f"SAFETY STOP: expected 3500, got {before}"
            )

        print()
        print("===== WRITE 3.510 V =====")
        await tx(bms, WRITE_3510, "0x01 = 3510")
        await asyncio.sleep(1)

        r1 = await read_settings(
            bms, "AFTER 1 SEC"
        )

        await asyncio.sleep(3)

        r2 = await read_settings(
            bms, "AFTER 4 SEC"
        )

        print()
        print("===== RESTORE 3.500 V =====")
        await tx(bms, WRITE_3500, "0x01 = 3500")
        await asyncio.sleep(2)

        restored = await read_settings(
            bms, "RESTORE CHECK"
        )

        print()
        print("===== RESULT =====")

        if 3510 in (r1, r2):
            print("WRITE WORKS: parameter changed to 3510")
        else:
            print("WRITE FAILED: parameter stayed 3500")

        if restored == 3500:
            print("RESTORE OK")
        else:
            print("!!! RESTORE NOT CONFIRMED !!!")

    finally:
        try:
            await bms.disconnect()
        except Exception:
            pass

asyncio.run(main())
