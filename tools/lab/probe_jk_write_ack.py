import asyncio
import secrets
from bmslib.models.jikong import JKBt

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci1"

APP_INIT = bytes.fromhex(
    "AA5590EB97000000000000000000000000000011"
)

def frame(addr, value, length=4):
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

async def tx(bms, data):
    print("TX:", data.hex(" ").upper())
    await bms.client.write_gatt_char(
        bms.char_handle_write,
        data=data,
        response=False
    )

async def main():
    bms = JKBt(
        MAC,
        name="garage_jk_bms",
        keep_alive=False,
        adapter=ADAPTER
    )

    try:
        await bms.connect(timeout=25)

        print("MTU:", getattr(bms.client, "mtu_size", "unknown"))

        print("INIT 97")
        await tx(bms, APP_INIT)
        await asyncio.sleep(2)

        s = await read_settings(bms)
        value = int.from_bytes(s[138:142], "little")
        print("START BALANCE BEFORE:", value)

        print("QUIET 2 SEC")
        await asyncio.sleep(2)

        print("WRITE SAME VALUE 3400")
        await tx(bms, frame(0x22, 3400, 4))

        await asyncio.sleep(3)

        s = await read_settings(bms)
        value = int.from_bytes(s[138:142], "little")
        print("START BALANCE AFTER:", value)

        await asyncio.sleep(2)

    finally:
        try:
            await bms.disconnect()
        except Exception:
            pass

asyncio.run(main())
