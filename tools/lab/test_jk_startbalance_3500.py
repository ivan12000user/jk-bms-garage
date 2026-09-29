import asyncio
from bmslib.models.jikong import JKBt

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci1"
OFFSET = 138

def u32(buf, pos):
    return int.from_bytes(buf[pos:pos+4], "little")

async def read_value(bms, label):
    bms._resp_table.pop(0x01, None)
    await bms._q(cmd=0x96, resp=0x01)
    buf, _ = bms.debug_data()["resp"][0x01]
    v = u32(bytes(buf), OFFSET)
    print(f"{label}: {v} = {v/1000:.3f} V")
    return v

async def main():
    bms = JKBt(
        MAC,
        name="garage_jk_bms",
        keep_alive=False,
        adapter=ADAPTER
    )

    try:
        await bms.connect(timeout=25)

        before = await read_value(bms, "BEFORE")
        if before != 3400:
            raise RuntimeError(f"SAFETY STOP: expected 3400, got {before}")

        print("\n===== WRITE 3400 -> 3500 =====")
        await bms._write(
            0x22,
            list((3500).to_bytes(4, "little"))
        )

        await asyncio.sleep(1)
        a1 = await read_value(bms, "AFTER 1 SEC")

        await asyncio.sleep(3)
        a4 = await read_value(bms, "AFTER 4 SEC")

        print("\n===== RESTORE 3400 =====")
        await bms._write(
            0x22,
            list((3400).to_bytes(4, "little"))
        )

        await asyncio.sleep(2)
        restored = await read_value(bms, "RESTORE CHECK")

        print("\n===== RESULT =====")
        print("WRITE:", "SUCCESS" if 3500 in (a1, a4) else "FAILED")
        print("RESTORE:", "OK" if restored == 3400 else "FAILED")

    finally:
        try:
            await bms.disconnect()
        except Exception:
            pass

asyncio.run(main())
