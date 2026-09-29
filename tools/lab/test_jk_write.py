import asyncio
import time
from pathlib import Path
from bmslib.models.jikong import JKBt

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci1"

ADDR = 0x22
OFFSET = 138

def u32(b, p):
    return int.from_bytes(b[p:p+4], "little")

async def read_settings(bms):
    bms._resp_table.pop(0x01, None)
    await bms._q(cmd=0x96, resp=0x01)
    buf, _ = bms.debug_data()["resp"][0x01]
    return bytes(buf)

async def write_value(bms, raw):
    payload = list(raw.to_bytes(4, "little"))
    print("WRITE:", raw, payload)
    await bms._write(ADDR, payload)
    await asyncio.sleep(2)

async def main():
    bms = JKBt(
        MAC,
        name="garage_jk_bms",
        keep_alive=False,
        adapter=ADAPTER
    )

    try:
        await bms.connect(timeout=25)

        before = await read_settings(bms)
        original = u32(before, OFFSET)

        print("BEFORE:", original, "=", original/1000, "V")

        Path(
            f"/opt/batmon-ha/jk_test_before_{time.strftime('%Y%m%d_%H%M%S')}.hex"
        ).write_text(before.hex(" "))

        if original != 3400:
            raise SystemExit(
                f"STOP: expected 3400, actually {original}"
            )

        print()
        print("=== TEST 3.400 -> 3.410 ===")
        await write_value(bms, 3410)

        mid = await read_settings(bms)
        got = u32(mid, OFFSET)
        print("AFTER TEST:", got, "=", got/1000, "V")

        if got != 3410:
            print("RESULT: WRITE CHANNEL FAILED")
            return

        print()
        print("=== RESTORE 3.410 -> 3.400 ===")
        await write_value(bms, 3400)

        after = await read_settings(bms)
        restored = u32(after, OFFSET)
        print("RESTORED:", restored, "=", restored/1000, "V")

        if restored == 3400:
            print("RESULT: WRITE CHANNEL OK")
        else:
            print("WARNING: RESTORE FAILED")

    finally:
        try:
            await bms.disconnect()
        except:
            pass

asyncio.run(main())
