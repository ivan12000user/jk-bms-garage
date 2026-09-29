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

        # 0x96 запускает/обновляет поток status 0x02
        await bms._q(cmd=0x96, resp=0x01)

        for _ in range(50):
            await asyncio.sleep(0.2)

            r = bms.debug_data().get("resp", {}).get(0x02)
            if not r:
                continue

            buf, _ = r
            data = bytes(buf)

            if len(data) < 170:
                continue

            errors = int.from_bytes(data[166:170], "little")

            print(f"ERRORS RAW = 0x{errors:08X}")
            print(f"bit19 Modify password in time = {'ON' if errors & (1<<19) else 'OFF'}")

            names = {
                0: "Wire resistance",
                1: "MOSFET overtemperature",
                2: "Cell count mismatch",
                4: "Battery fully charged",
                5: "Pack overvoltage",
                6: "Charge overcurrent",
                7: "Charge short circuit",
                8: "Charge overtemperature",
                9: "Charge undertemperature",
                10: "Coprocessor communication error",
                11: "Cell undervoltage",
                12: "Pack undervoltage",
                13: "Discharge overcurrent",
                14: "Discharge short circuit",
                15: "Discharge overtemperature",
                16: "Charging MOS abnormal",
                17: "Discharging MOS abnormal",
                18: "GPS disconnected",
                19: "Modify password in time",
                20: "Discharge on failed",
                21: "Battery overtemperature",
                22: "Temperature sensor anomaly",
                23: "PL module anomaly",
                24: "SCP release failed",
                25: "Discharge OCP II",
                26: "Discharge OCP III",
                27: "Discharge undertemperature alarm",
                28: "GPS remote lock",
            }

            for bit, name in names.items():
                if errors & (1 << bit):
                    print(f"BIT {bit:2d}: {name}")

            return

        print("No fresh 0x02 frame")

    finally:
        try:
            await bms.disconnect()
        except Exception:
            pass

asyncio.run(main())
