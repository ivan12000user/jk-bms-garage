import asyncio
import secrets
from bmslib.models.jikong import JKBt

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci1"

ADDR = 0x22
OFFSET = 138

APP_INIT = bytes.fromhex(
    "AA5590EB97000000000000000000000000000011"
)

def u32(b, p):
    return int.from_bytes(b[p:p+4], "little")

def app_frame(addr, value, length=4):
    b = bytearray.fromhex("AA5590EB")
    b.append(addr)
    b.append(length)
    b += int(value).to_bytes(length, "little")

    while len(b) < 19:
        b.append(secrets.randbelow(256))

    b.append(sum(b) & 0xff)
    return bytes(b)

async def read_settings(bms):
    bms._resp_table.pop(0x01, None)
    await bms._q(cmd=0x96, resp=0x01)
    buf, _ = bms.debug_data()["resp"][0x01]
    return bytes(buf)

async def write_raw(bms, frame):
    print("TX:", frame.hex(" ").upper())
    await bms.client.write_gatt_char(
        bms.char_handle_write,
        data=frame,
        response=False
    )
    await asyncio.sleep(1)

async def main():
    bms = JKBt(
        MAC,
        name="garage_jk_bms",
        keep_alive=False,
        adapter=ADAPTER
    )

    try:
        await bms.connect(timeout=25)

        print("=== OFFICIAL APP INIT 0x97 ===")
        await write_raw(bms, APP_INIT)

        before = await read_settings(bms)
        original = u32(before, OFFSET)
        print("BEFORE:", original, "=", original / 1000, "V")

        if original != 3400:
            raise SystemExit(
                f"SAFETY STOP: expected 3400, got {original}"
            )

        print()
        print("=== TEST 3.400 -> 3.410 ===")
        f = app_frame(ADDR, 3410)
        await write_raw(bms, f)

        mid = await read_settings(bms)
        got = u32(mid, OFFSET)
        print("AFTER TEST:", got, "=", got / 1000, "V")

        if got != 3410:
            print("RESULT: WRITE STILL FAILED")
            return

        print()
        print("=== RESTORE 3.410 -> 3.400 ===")
        f = app_frame(ADDR, 3400)
        await write_raw(bms, f)

        after = await read_settings(bms)
        restored = u32(after, OFFSET)
        print("RESTORED:", restored, "=", restored / 1000, "V")

        if restored == 3400:
            print("RESULT: WRITE OK WITH APP INIT 0x97")
        else:
            print("WARNING: RESTORE FAILED")

    finally:
        try:
            await bms.disconnect()
        except Exception:
            pass

asyncio.run(main())
