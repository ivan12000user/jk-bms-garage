import asyncio
from bmslib.models.jikong import JKBt

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci1"

def txt(buf):
    return bytes(buf).split(b"\x00",1)[0].decode("ascii","replace")

async def main():
    bms = JKBt(
        MAC,
        name="garage_jk_bms",
        keep_alive=False,
        adapter=ADAPTER
    )

    try:
        await bms.connect(timeout=25)

        bms._resp_table.pop(0x03, None)
        await bms._q(cmd=0x97, resp=0x03)

        buf, ts = bms.debug_data()["resp"][0x03]
        b = bytes(buf)

        print("len:", len(b))
        print("HW:", txt(b[22:30]))
        print("SW:", txt(b[30:38]))
        print("Device name:", txt(b[46:62]))
        print("Device passcode:", txt(b[62:78]))
        print("Serial:", txt(b[86:102]))
        print("Setup passcode:", txt(b[118:134]))

    finally:
        try:
            await bms.disconnect()
        except:
            pass

asyncio.run(main())
