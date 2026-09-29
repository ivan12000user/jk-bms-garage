import asyncio
import secrets
from bmslib.models.jikong import JKBt

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci1"

OFFSET = 138

CMD97 = bytes.fromhex(
    "AA5590EB97000000000000000000000000000011"
)

CMD96 = bytes.fromhex(
    "AA5590EB96000000000000000000000000000010"
)

def make_frame(code, length, value):
    b = bytearray.fromhex("AA5590EB")
    b.append(code)
    b.append(length)
    b += int(value).to_bytes(length, "little")

    while len(b) < 19:
        b.append(secrets.randbelow(256))

    b.append(sum(b) & 0xff)
    return bytes(b)

async def raw_tx(bms, data, name):
    print(f"TX {name}: {data.hex(' ').upper()}")
    await bms.client.write_gatt_char(
        bms.char_handle_write,
        data,
        response=False
    )

async def read_settings(bms, label):
    bms._resp_table.pop(0x01, None)

    await raw_tx(bms, CMD96, "0x96")

    for _ in range(50):
        await asyncio.sleep(0.1)

        r = bms.debug_data().get("resp", {}).get(0x01)
        if r:
            buf, _ = r
            data = bytes(buf)

            if len(data) >= 142:
                val = int.from_bytes(
                    data[OFFSET:OFFSET+4], "little"
                )
                print(
                    f"{label}: {val} = {val/1000:.3f} V"
                )
                return val

    raise RuntimeError("No fresh 0x96 settings response")

async def connect():
    bms = JKBt(
        MAC,
        name="garage_jk_bms",
        keep_alive=False,
        adapter=ADAPTER
    )

    await bms.connect(timeout=25)

    await raw_tx(bms, CMD97, "0x97")
    await asyncio.sleep(1)

    return bms

async def disconnect(bms):
    try:
        await bms.disconnect()
    except Exception:
        pass
    await asyncio.sleep(2)

async def main():
    bms = None

    try:
        print("===== SESSION 1 =====")
        bms = await connect()

        before = await read_settings(bms, "BEFORE")

        if before != 3400:
            raise RuntimeError(
                f"SAFETY STOP: expected 3400, got {before}"
            )

        print()
        print("===== WRITE 3410 =====")

        frame3410 = make_frame(0x22, 4, 3410)
        await raw_tx(bms, frame3410, "0x22 = 3410")

        await asyncio.sleep(1)

        r1 = await read_settings(
            bms, "READ AFTER 1 SEC"
        )

        await asyncio.sleep(3)

        r2 = await read_settings(
            bms, "READ AFTER 4 SEC"
        )

        print()
        print("===== RECONNECT =====")

        await disconnect(bms)
        bms = None

        bms = await connect()

        r3 = await read_settings(
            bms, "READ AFTER RECONNECT"
        )

        print()
        print("OBSERVED:", before, r1, r2, r3)

        print()
        print("===== FORCE RESTORE 3400 =====")

        frame3400 = make_frame(0x22, 4, 3400)
        await raw_tx(bms, frame3400, "0x22 = 3400")

        await asyncio.sleep(2)

        restored = await read_settings(
            bms, "RESTORE CHECK"
        )

        if restored != 3400:
            print("!!! WARNING: RESTORE NOT CONFIRMED !!!")
        else:
            print("RESTORE OK: 3.400 V")

        print()
        if 3410 in (r1, r2, r3):
            print("RESULT: WRITE REALLY WORKS")
        else:
            print("RESULT: ACK ACCEPTED BUT VALUE NOT APPLIED")

    finally:
        if bms is not None:
            await disconnect(bms)

asyncio.run(main())
