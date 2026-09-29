import asyncio
import time
import os
from pathlib import Path

from bmslib.models.jikong import JKBt

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci1"

ADDR = 0x07
OFFSET = 30
TARGET_RAW = 3560
TARGET_V = TARGET_RAW / 1000

def u32(buf, pos):
    return int.from_bytes(buf[pos:pos+4], "little", signed=False)

async def read_settings(bms):
    bms._resp_table.pop(0x01, None)
    await bms._q(cmd=0x96, resp=0x01)
    buf, ts = bms.debug_data()["resp"][0x01]
    return bytes(buf)

async def main():
    apply = os.environ.get("CONFIRM_WRITE_JK") == "YES"

    bms = JKBt(
        MAC,
        name="garage_jk_bms",
        keep_alive=False,
        adapter=ADAPTER
    )

    try:
        print("Connecting:", MAC, "adapter:", ADAPTER)
        await bms.connect(timeout=25)

        print("Reading BEFORE...")
        before = await read_settings(bms)

        old_raw = u32(before, OFFSET)

        backup = Path(
            f"/opt/batmon-ha/jk_settings_before_soc100_"
            f"{time.strftime('%Y%m%d_%H%M%S')}.hex"
        )
        backup.write_text(before.hex(" "), encoding="utf-8")

        print()
        print("SOC100 BEFORE:", old_raw / 1000, "V")
        print("SOC100 TARGET:", TARGET_V, "V")
        print("ADDR: 0x%02X" % ADDR)
        print("OFFSET:", OFFSET)
        print("BYTES:", TARGET_RAW.to_bytes(4, "little").hex(" "))
        print("Backup:", backup)

        if not apply:
            print()
            print("DRY RUN ONLY")
            print("Nothing written")
            return

        if not 3300 <= old_raw <= 3650:
            raise RuntimeError(
                f"Safety stop: unexpected current SOC100 raw={old_raw}"
            )

        print()
        print("=== WRITING ONLY SOC100 ===")

        payload = list(
            TARGET_RAW.to_bytes(4, "little", signed=False)
        )

        await bms._write(ADDR, payload)
        await asyncio.sleep(2)

        print("Reading AFTER...")
        after = await read_settings(bms)

        got_raw = u32(after, OFFSET)

        backup_after = Path(
            f"/opt/batmon-ha/jk_settings_after_soc100_"
            f"{time.strftime('%Y%m%d_%H%M%S')}.hex"
        )
        backup_after.write_text(after.hex(" "), encoding="utf-8")

        print()
        print("=== VERIFY ===")
        print("SOC100 AFTER:", got_raw / 1000, "V")
        print("After backup:", backup_after)

        if got_raw == TARGET_RAW:
            print("OK: SOC100 changed and verified")
        else:
            print(
                "FAIL: expected",
                TARGET_V,
                "V but read",
                got_raw / 1000,
                "V"
            )
            raise SystemExit(2)

    finally:
        try:
            await bms.disconnect()
        except Exception:
            pass

asyncio.run(main())
