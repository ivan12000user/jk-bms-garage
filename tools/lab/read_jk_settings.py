import asyncio
import time
from pathlib import Path

from bmslib.models.jikong import JKBt

MAC = "C8:47:80:53:3D:A7"

def u32(buf, pos):
    return int.from_bytes(buf[pos:pos+4], "little", signed=False)

def i32(buf, pos):
    return int.from_bytes(buf[pos:pos+4], "little", signed=True)

def u16(buf, pos):
    return int.from_bytes(buf[pos:pos+2], "little", signed=False)

def i8(buf, pos):
    x = buf[pos]
    return x - 256 if x > 127 else x

def b(buf, pos):
    return buf[pos]

def mv(buf, pos):
    return u32(buf, pos) / 1000

def ma(buf, pos):
    return u32(buf, pos) / 1000

def ah(buf, pos):
    return u32(buf, pos) / 1000

def t01(buf, pos, signed=False):
    return (i32(buf, pos) if signed else u32(buf, pos)) / 10

def onoff(x):
    return "ON" if x else "OFF"

async def main():
    bms = JKBt(MAC, name="garage_jk_bms", keep_alive=False, adapter="hci1")

    try:
        print("Connecting to JK BMS", MAC)
        await bms.connect(timeout=20)

        print("Reading settings frame 0x01...")
        await bms._q(cmd=0x96, resp=0x01)

        # Не обязательно, но полезно: подтягивает hw/sw/name
        try:
            info = await bms.fetch_device_info()
            print("Device:", info)
        except Exception as e:
            print("Device info read warning:", repr(e))

        resp = bms.debug_data()["resp"]
        settings, ts = resp[0x01]
        buf = bytes(settings)

        out = Path(f"/opt/batmon-ha/jk_settings_{time.strftime('%Y%m%d_%H%M%S')}.hex")
        out.write_text(buf.hex(" "), encoding="utf-8")

        print()
        print("=== JK SETTINGS FRAME ===")
        print("len:", len(buf))
        print("saved:", out)
        print("header:", buf[0:6].hex(" "))
        print()

        print("=== Основное ===")
        print(f"Cell count:                 {b(buf,114)} S")
        print(f"Nominal capacity:           {ah(buf,130):.3f} Ah")
        print(f"Charge switch:              {onoff(b(buf,118))}")
        print(f"Discharge switch:           {onoff(b(buf,122))}")
        print(f"Balance switch:             {onoff(b(buf,126))}")
        print(f"Device address:             {b(buf,270)}")
        print(f"Precharge time:             {b(buf,274)} s")
        print()

        print("=== Напряжения ячеек / SOC ===")
        print(f"Smart sleep voltage:        {mv(buf,6):.3f} V")
        print(f"Cell UVP:                   {mv(buf,10):.3f} V")
        print(f"Cell UVP recovery:          {mv(buf,14):.3f} V")
        print(f"Cell OVP:                   {mv(buf,18):.3f} V")
        print(f"Cell OVP recovery:          {mv(buf,22):.3f} V")
        print(f"Balance trigger delta:      {mv(buf,26):.3f} V")
        print(f"SOC 100% voltage:           {mv(buf,30):.3f} V")
        print(f"SOC 0% voltage:             {mv(buf,34):.3f} V")
        print(f"Cell RCV:                   {mv(buf,38):.3f} V")
        print(f"Cell RFV:                   {mv(buf,42):.3f} V")
        print(f"Power off voltage:          {mv(buf,46):.3f} V")
        print(f"Start balance voltage:      {mv(buf,138):.3f} V")
        print()

        print("=== Токи / защиты по току ===")
        print(f"Max charge current:         {ma(buf,50):.3f} A")
        print(f"Charge OCP delay:           {u32(buf,54)} s")
        print(f"Charge OCP recovery time:   {u32(buf,58)} s")
        print(f"Max discharge current:      {ma(buf,62):.3f} A")
        print(f"Discharge OCP delay:        {u32(buf,66)} s")
        print(f"Discharge OCP recovery:     {u32(buf,70)} s")
        print(f"Short circuit recovery:     {u32(buf,74)} s")
        print(f"Short circuit delay:        {u32(buf,134)} us")
        print(f"Max balance current:        {ma(buf,78):.3f} A")
        print()

        print("=== Температурные защиты ===")
        print(f"Charge OTP:                 {t01(buf,82):.1f} °C")
        print(f"Charge OTP recovery:        {t01(buf,86):.1f} °C")
        print(f"Discharge OTP:              {t01(buf,90):.1f} °C")
        print(f"Discharge OTP recovery:     {t01(buf,94):.1f} °C")
        print(f"Charge UTP:                 {t01(buf,98, signed=True):.1f} °C")
        print(f"Charge UTP recovery:        {t01(buf,102, signed=True):.1f} °C")
        print(f"MOS OTP:                    {t01(buf,106, signed=True):.1f} °C")
        print(f"MOS OTP recovery:           {t01(buf,110, signed=True):.1f} °C")
        print(f"Discharge UTP:              {i8(buf,296)} °C")
        print(f"Discharge UTP recovery:     {i8(buf,297)} °C")
        print(f"Heating start temp:         {i8(buf,284)} °C")
        print(f"Heating stop temp:          {i8(buf,285)} °C")
        print()

        controls = u16(buf,282)
        print("=== Controls bitmask ===")
        print(f"raw:                        0x{controls:04X}")
        bits = [
            (0, "Heating enabled"),
            (1, "Disable temperature sensors"),
            (2, "GPS heartbeat"),
            (3, "Port switch RS485/CAN"),
            (4, "Display always on"),
            (5, "Special charger"),
            (6, "Smart sleep"),
            (7, "Disable PCL module"),
            (8, "Timed stored data"),
            (9, "Charging float mode"),
        ]
        for bit, name in bits:
            print(f"{name:28s}: {'ON' if controls & (1 << bit) else 'OFF'}")

        print()
        print("=== Быстрая оценка ===")
        cap = ah(buf,130)
        if abs(cap - 25.0) < 0.2:
            print("OK: ёмкость BMS = 25 Ah")
        else:
            print(f"ВНИМАНИЕ: ёмкость BMS = {cap:.1f} Ah, для твоей АКБ надо 25 Ah")

        if mv(buf,10) <= 2.8:
            print("OK: Cell UVP в безопасном диапазоне")
        else:
            print("ПРОВЕРИТЬ: Cell UVP выше 2.8 В")

        if 3.60 <= mv(buf,18) <= 3.65:
            print("OK: Cell OVP типичный для LiFePO4")
        else:
            print("ПРОВЕРИТЬ: Cell OVP не в диапазоне 3.60–3.65 В")

        if t01(buf,98, signed=True) <= 0:
            print("OK: запрет заряда около/ниже 0°C")
        else:
            print("ВНИМАНИЕ: Charge UTP выше 0°C или не настроен как ожидалось")

    finally:
        try:
            await bms.disconnect()
        except Exception:
            pass

asyncio.run(main())
