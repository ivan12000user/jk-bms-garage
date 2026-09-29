import asyncio
from bmslib.models.jikong import JKBt

MAC = "C8:47:80:53:3D:A7"

async def main():
    bms = JKBt(
        MAC,
        name="garage_jk_bms",
        keep_alive=False,
        adapter="hci1"
    )

    try:
        await bms.connect(timeout=25)

        buf, _ = bms.debug_data()["resp"][0x03]
        b = bytes(buf)

        uptime = int.from_bytes(b[38:42], "little")
        power_on_count = int.from_bytes(b[42:46], "little")

        days = uptime / 86400

        print("Uptime seconds :", uptime)
        print("Uptime days    :", f"{days:.2f}")
        print("Power-on count :", power_on_count)

    finally:
        try:
            await bms.disconnect()
        except Exception:
            pass

asyncio.run(main())
