import asyncio
import time
from pathlib import Path
import os

from bmslib.models.jikong import JKBt

MAC = "C8:47:80:53:3D:A7"

# Только эти параметры пишем.
# addr — адрес JK BLE write.
# offset — где это значение лежит в settings frame, для проверки.
TARGETS = [
    # name, addr, offset, new_raw, scale, unit
    ("Cell UVP",              0x02, 10,  2700, 1000, "V"),   # 2.700 V
    ("Cell UVP recovery",     0x03, 14,  3000, 1000, "V"),   # 3.000 V
    ("Nominal capacity",      0x20, 130, 25000, 1000, "Ah"), # 25.000 Ah
    ("Start balance voltage", 0x22, 138, 3400, 1000, "V"),   # 3.400 V
]

def u32(buf, pos):
    return int.from_bytes(buf[pos:pos+4], "little", signed=False)

def fmt(raw, scale, unit):
    return f"{raw / scale:.3f} {unit}"

async def read_settings(bms):
    bms._resp_table.pop(0x01, None)
    await bms._q(cmd=0x96, resp=0x01)
    buf, ts = bms.debug_data()["resp"][0x01]
    return bytes(buf)

async def main():
    apply = os.environ.get("CONFIRM_WRITE_JK") == "YES"

    bms = JKBt(MAC, name="garage_jk_bms", keep_alive=False, adapter="hci0")

    try:
        print("Connecting to JK BMS", MAC)
        await bms.connect(timeout=25)

        print("Reading current settings...")
        before = await read_settings(bms)

        backup = Path(f"/opt/batmon-ha/jk_settings_before_write_{time.strftime('%Y%m%d_%H%M%S')}.hex")
        backup.write_text(before.hex(" "), encoding="utf-8")

        print()
        print("=== CURRENT -> TARGET ===")
        for name, addr, offset, new_raw, scale, unit in TARGETS:
            old_raw = u32(before, offset)
            print(f"{name:24s} addr=0x{addr:02X} offset={offset:3d}: {fmt(old_raw, scale, unit)} -> {fmt(new_raw, scale, unit)}")

        print()
        print("Backup saved:", backup)

        if not apply:
            print()
            print("DRY RUN ONLY. Ничего не записано.")
            print("Для записи запусти с CONFIRM_WRITE_JK=YES")
            return

        print()
        print("=== WRITING ===")
        for name, addr, offset, new_raw, scale, unit in TARGETS:
            payload = list(int(new_raw).to_bytes(4, "little", signed=False))
            print(f"Write {name:24s} addr=0x{addr:02X} value={fmt(new_raw, scale, unit)} bytes={bytes(payload).hex(' ')}")
            await bms._write(addr, payload)
            await asyncio.sleep(0.8)

        print()
        print("Reading settings after write...")
        await asyncio.sleep(1.5)
        after = await read_settings(bms)

        backup_after = Path(f"/opt/batmon-ha/jk_settings_after_write_{time.strftime('%Y%m%d_%H%M%S')}.hex")
        backup_after.write_text(after.hex(" "), encoding="utf-8")

        print()
        print("=== VERIFY ===")
        ok = True
        for name, addr, offset, new_raw, scale, unit in TARGETS:
            got_raw = u32(after, offset)
            state = "OK" if got_raw == new_raw else "FAIL"
            if got_raw != new_raw:
                ok = False
            print(f"{state:4s} {name:24s}: {fmt(got_raw, scale, unit)}")

        print()
        print("After saved:", backup_after)

        if ok:
            print("OK: selected JK settings written and verified")
        else:
            print("WARNING: some settings did not verify")

    finally:
        try:
            await bms.disconnect()
        except Exception:
            pass

asyncio.run(main())
