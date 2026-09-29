import asyncio
from bmslib.models.jikong import JKBt

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci1"

RESTART = bytes.fromhex(
    "AA5590EB660000000000000000000000000000E0"
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

        print("CONNECTED")
        print("Sending documented JK02_32S RESTART 0x66")
        print("TX:", RESTART.hex(" ").upper())

        await bms.client.write_gatt_char(
            bms.char_handle_write,
            RESTART,
            response=False
        )

        print("RESTART SENT")
        await asyncio.sleep(3)

    except Exception as e:
        # Disconnect/timeout immediately after restart is expected
        print("After restart:", repr(e))

    finally:
        try:
            await bms.disconnect()
        except Exception:
            pass

asyncio.run(main())
