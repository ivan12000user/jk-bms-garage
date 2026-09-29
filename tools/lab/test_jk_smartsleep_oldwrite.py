import asyncio
from bmslib.models.jikong import JKBt

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci1"

OFFSET = 6

def u32(buf, pos):
    return int.from_bytes(buf[pos:pos+4], "little", signed=False)

async def read_settings(bms, label):
    bms._resp_table.pop(0x01, None)

    # Именно старый механизм _q():
    # write_gatt_char без response=False
    await bms._q(cmd=0x96, resp=0x01)

    buf, _ = bms.debug_data()["resp"][0x01]
    data = bytes(buf)

    value = u32(data, OFFSET)

    print(
        f"{label}: {value} = {value/1000:.3f} V"
    )
    return value

async def main():
    bms = JKBt(
        MAC,
        name="garage_jk_bms",
        keep_alive=False,
        adapter=ADAPTER
    )

    try:
        print("===== CONNECT =====")
        await bms.connect(timeout=25)

        before = await read_settings(bms, "BEFORE")

        if before != 3500:
            raise RuntimeError(
                f"SAFETY STOP: expected 3500, got {before}"
            )

        print()
        print("===== OLD _write(): 3500 -> 3510 =====")

        payload = list(
            int(3510).to_bytes(4, "little")
        )

        print(
            "WRITE 0x01 = 3510, payload:",
            bytes(payload).hex(" ")
        )

        # ВАЖНО:
        # именно старый метод, без response=False
        await bms._write(0x01, payload)

        await asyncio.sleep(1)

        r1 = await read_settings(
            bms, "AFTER 1 SEC"
        )

        await asyncio.sleep(3)

        r2 = await read_settings(
            bms, "AFTER 4 SEC"
        )

        print()
        print("===== RESTORE 3500 =====")

        payload_restore = list(
            int(3500).to_bytes(4, "little")
        )

        await bms._write(
            0x01,
            payload_restore
        )

        await asyncio.sleep(2)

        restored = await read_settings(
            bms, "RESTORE CHECK"
        )

        print()
        print("===== RESULT =====")

        if 3510 in (r1, r2):
            print("SUCCESS: WRITE WITH RESPONSE WORKS")
        else:
            print("FAILED: VALUE DID NOT CHANGE")

        if restored == 3500:
            print("RESTORE OK")
        else:
            print("!!! RESTORE FAILED !!!")

    finally:
        try:
            await bms.disconnect()
        except Exception:
            pass

asyncio.run(main())
