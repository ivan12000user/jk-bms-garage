import asyncio
import time
from bleak import BleakScanner, BleakClient

MAC = "C8:47:80:53:3D:A7"
ADAPTER = "hci0"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
HEADER = bytes.fromhex("55 AA EB 90")

# TEST SETTINGS
NEW_RFV     = 3350       # 3.350 V/cell
NEW_RCV     = 3440       # 3.440 V/cell
NEW_SOC100  = 3430       # 3.430 V/cell
NEW_RCVTIME = 1          # 0.1 h = 6 min

WATCH_SECONDS = 20 * 60  # максимум 20 минут

rx = bytearray()

q_settings = asyncio.Queue()
q_info = asyncio.Queue()
q_live = asyncio.Queue()


def make_frame(reg, value=0, length=0):
    f = bytearray(20)

    f[0:4] = bytes.fromhex("AA 55 90 EB")
    f[4] = reg
    f[5] = length

    f[6] = (value >> 0) & 0xff
    f[7] = (value >> 8) & 0xff
    f[8] = (value >> 16) & 0xff
    f[9] = (value >> 24) & 0xff

    f[19] = sum(f[:19]) & 0xff

    return bytes(f)


def notify(sender, data):
    global rx

    rx.extend(data)

    while True:
        p = rx.find(HEADER)

        if p < 0:
            if len(rx) > 3:
                del rx[:-3]
            return

        if p > 0:
            del rx[:p]

        if len(rx) < 300:
            return

        f = bytes(rx[:300])
        del rx[:300]

        if (sum(f[:299]) & 0xff) != f[299]:
            continue

        typ = f[4]

        if typ == 0x01:
            q_settings.put_nowait(f)

        elif typ == 0x02:
            q_live.put_nowait(f)

        elif typ == 0x03:
            q_info.put_nowait(f)


async def clear(q):
    while not q.empty():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            break


async def send(client, ch, reg, value=0, length=0):
    f = make_frame(reg, value, length)

    print(
        "TX:",
        " ".join(f"{b:02X}" for b in f)
    )

    await client.write_gatt_char(
        ch,
        f,
        response=False
    )


async def find_bms():
    for n in range(1, 5):
        print(f"Searching BMS via {ADAPTER}, attempt {n}/4...")

        dev = await BleakScanner.find_device_by_address(
            MAC,
            timeout=12,
            adapter=ADAPTER
        )

        if dev is not None:
            return dev

        await asyncio.sleep(3)

    return None


def decode_settings(f):
    return {
        "soc100": int.from_bytes(f[30:34], "little"),
        "soc0":   int.from_bytes(f[34:38], "little"),
        "rcv":    int.from_bytes(f[38:42], "little"),
        "rfv":    int.from_bytes(f[42:46], "little"),
    }


def decode_info(f):
    return {
        "rcv_time_raw": f[266],
        "rfv_time_raw": f[267],
    }


def decode_live(f):
    cells = [
        int.from_bytes(f[6+i*2:8+i*2], "little") / 1000
        for i in range(4)
    ]

    pack = int.from_bytes(
        f[150:154], "little"
    ) / 1000

    current = int.from_bytes(
        f[158:162],
        "little",
        signed=True
    ) / 1000

    soc = f[173]

    remain = int.from_bytes(
        f[174:178], "little"
    ) / 1000

    capacity = int.from_bytes(
        f[178:182], "little"
    ) / 1000

    elapsed = int.from_bytes(
        f[278:280], "little"
    )

    status_id = f[280]

    status = {
        0: "Bulk",
        1: "Absorption",
        2: "Float"
    }.get(status_id, f"Unknown({status_id})")

    return {
        "cells": cells,
        "pack": pack,
        "current": current,
        "soc": soc,
        "remain": remain,
        "capacity": capacity,
        "elapsed": elapsed,
        "status": status,
        "status_id": status_id,
    }


def show_settings(title, s, inf):
    print()
    print("========================================")
    print(title)

    print(
        f"SOC-100:   {s['soc100']/1000:.3f} V/cell"
    )

    print(
        f"RCV:       {s['rcv']/1000:.3f} V/cell"
    )

    print(
        f"RFV:       {s['rfv']/1000:.3f} V/cell"
    )

    print(
        f"RCV Time:  {inf['rcv_time_raw']/10:.1f} h"
    )

    print(
        f"RFV Time:  {inf['rfv_time_raw']/10:.1f} h"
    )

    print("========================================")


def show_live(prefix, v):
    print(
        time.strftime("%H:%M:%S"),
        prefix,
        f"U={v['pack']:.3f}V",
        f"I={v['current']:+.3f}A",
        f"SOC={v['soc']}%",
        f"Remain={v['remain']:.3f}/{v['capacity']:.3f}Ah",
        f"Status={v['status']}",
        f"Timer={v['elapsed']}s",
        "Cells=" +
        "/".join(f"{x:.3f}" for x in v["cells"]),
        flush=True
    )


async def request_all(client, ch):
    await clear(q_settings)
    await clear(q_info)

    await send(client, ch, 0x97)

    info = await asyncio.wait_for(
        q_info.get(),
        timeout=12
    )

    await send(client, ch, 0x96)

    settings = await asyncio.wait_for(
        q_settings.get(),
        timeout=12
    )

    return settings, info


async def main():
    dev = await find_bms()

    if dev is None:
        raise SystemExit("BMS not found via hci0")

    print("Found:", dev)

    async with BleakClient(
        dev,
        adapter=ADAPTER,
        timeout=30
    ) as client:

        chars = [
            c
            for s in client.services
            for c in s.characteristics
            if c.uuid.lower() == FFE1
        ]

        write_ch = next(
            (
                c for c in chars
                if "write-without-response" in c.properties
            ),
            None
        )

        notify_ch = next(
            (
                c for c in chars
                if "notify" in c.properties
            ),
            None
        )

        if write_ch is None or notify_ch is None:
            raise RuntimeError("FFE1 write/notify not found")

        print("FFE1 handle:", write_ch.handle)

        await client.start_notify(
            notify_ch,
            notify
        )

        await asyncio.sleep(1)

        #
        # READ CURRENT SETTINGS
        #
        settings_frame, info_frame = await request_all(
            client,
            write_ch
        )

        old = decode_settings(settings_frame)
        old_info = decode_info(info_frame)

        show_settings(
            "BEFORE",
            old,
            old_info
        )

        print()
        print("OLD VALUES FOR ROLLBACK:")
        print(
            f"RFV={old['rfv']} "
            f"RCV={old['rcv']} "
            f"SOC100={old['soc100']} "
            f"RCVTIME={old_info['rcv_time_raw']}"
        )

        #
        # WRITE
        #
        print()
        print("===== WRITE NEW SOC SYNC SETTINGS =====")

        # Сначала RFV, чтобы никогда не получить
        # временно RFV > RCV.
        print()
        print("1/4 RFV -> 3.350 V")
        await send(
            client,
            write_ch,
            0x0A,
            NEW_RFV,
            4
        )
        await asyncio.sleep(1)

        print()
        print("2/4 RCV -> 3.440 V")
        await send(
            client,
            write_ch,
            0x09,
            NEW_RCV,
            4
        )
        await asyncio.sleep(1)

        print()
        print("3/4 SOC100 -> 3.430 V")
        await send(
            client,
            write_ch,
            0x07,
            NEW_SOC100,
            4
        )
        await asyncio.sleep(1)

        print()
        print("4/4 RCV Time -> 0.1 h")
        await send(
            client,
            write_ch,
            0xB3,
            NEW_RCVTIME,
            1
        )

        await asyncio.sleep(2)

        #
        # READ BACK
        #
        settings_frame, info_frame = await request_all(
            client,
            write_ch
        )

        new = decode_settings(settings_frame)
        new_info = decode_info(info_frame)

        show_settings(
            "AFTER WRITE / READBACK",
            new,
            new_info
        )

        ok = (
            new["rfv"] == NEW_RFV
            and new["rcv"] == NEW_RCV
            and new["soc100"] == NEW_SOC100
            and new_info["rcv_time_raw"] == NEW_RCVTIME
        )

        if not ok:
            print()
            print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            print("READBACK FAILED - STOPPING TEST")
            print("Do not change anything else.")
            print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            return

        print()
        print("READBACK OK")
        print()
        print("Target pack thresholds:")
        print(
            f"RCV:     {NEW_RCV/1000*4:.3f} V"
        )
        print(
            f"SOC100:  {NEW_SOC100/1000*4:.3f} V"
        )

        #
        # WATCH LIVE
        #
        print()
        print("========================================")
        print("WATCHING FOR SOC SYNCHRONIZATION")
        print("Max duration: 20 minutes")
        print("Expected path: Bulk -> Absorption -> Float")
        print("Ctrl+C can stop the watch safely.")
        print("========================================")
        print()

        await clear(q_live)

        # refresh streaming
        await send(client, write_ch, 0x96)

        start = time.monotonic()
        last_print = 0
        last_status = None
        last_soc = None
        final = None

        while time.monotonic() - start < WATCH_SECONDS:

            try:
                f = await asyncio.wait_for(
                    q_live.get(),
                    timeout=15
                )
            except asyncio.TimeoutError:
                print("No live frame - requesting 0x96")
                await send(client, write_ch, 0x96)
                continue

            v = decode_live(f)
            final = v

            now = time.monotonic()

            changed = (
                v["status"] != last_status
                or v["soc"] != last_soc
            )

            if changed or (now - last_print >= 5):
                show_live("", v)
                last_print = now
                last_status = v["status"]
                last_soc = v["soc"]

            if v["soc"] >= 100:
                print()
                print("========================================")
                print("SUCCESS: SOC REACHED 100%")
                print(
                    f"Remaining = {v['remain']:.3f} Ah"
                )
                print(
                    f"Status = {v['status']}"
                )
                print(
                    f"Status timer = {v['elapsed']} s"
                )
                print("========================================")
                break

        else:
            print()
            print("========================================")
            print("WATCH TIME EXPIRED")

            if final:
                print(
                    f"SOC={final['soc']}% "
                    f"Remaining={final['remain']:.3f}Ah "
                    f"Status={final['status']} "
                    f"Timer={final['elapsed']}s"
                )

            print("========================================")

        await client.stop_notify(
            notify_ch
        )


asyncio.run(main())
