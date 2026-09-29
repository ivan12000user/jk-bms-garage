import asyncio
from bmslib.models.jikong import JKBt

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci1"

CMD97 = bytes.fromhex(
    "AA5590EB97000000000000000000000000000011"
)

CMD96 = bytes.fromhex(
    "AA5590EB96000000000000000000000000000010"
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

        print("=== 0x97 WRITE COMMAND ===")
        await bms.client.write_gatt_char(
            bms.char_handle_write,
            CMD97,
            response=False
        )

        await asyncio.sleep(1)

        bms._resp_table.pop(0x01, None)

        print("=== 0x96 WRITE COMMAND ===")
        await bms.client.write_gatt_char(
            bms.char_handle_write,
            CMD96,
            response=False
        )

        for n in range(30):
            await asyncio.sleep(0.1)
            r = bms.debug_data().get("resp", {}).get(0x01)
            if r:
                buf, ts = r
                data = bytes(buf)

                print("SETTINGS LEN:", len(data))

                if len(data) >= 142:
                    soc100 = int.from_bytes(data[30:34], "little")
                    startbal = int.from_bytes(data[138:142], "little")

                    print("SOC100 RAW:", soc100,
                          "=", soc100 / 1000, "V")
                    print("START BALANCE RAW:", startbal,
                          "=", startbal / 1000, "V")

                print("RESULT: RAW 0x96 NO-RESPONSE READ OK")
                return

        print("RESULT: NO SETTINGS RESPONSE")

    finally:
        try:
            await bms.disconnect()
        except Exception:
            pass

asyncio.run(main())
