#!/usr/bin/env python3
"""Find a Vexo Open band, connect to it, and show what it can do.

Usage:
    python3 detect.py                 # scan, then connect to the only band nearby
    python3 detect.py 36              # connect straight to Vexo-HACK-36
    python3 detect.py --only-scan     # just list nearby bands
    python3 detect.py --led           # red/green/blue/blink, to prove control
    python3 detect.py --json          # machine-readable output

The band only advertises for 60 seconds after a double-tap.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE / "vexo-open-kit"
sys.path.insert(0, str(KIT / "python"))

SERVICE_UUID = "254f0001-df82-4a9c-a2b5-563a0f6b2021"
NAME_PREFIX = "Vexo-HACK-"
MAKER_ID = 0xFFFF
MAKER_TAG = 0x4F


def _band_name(number: int) -> str:
    return NAME_PREFIX + (f"{number:02d}" if number < 100 else str(number))


async def scan_bands(seconds: float) -> dict[int, dict]:
    """Return {band_number: {"name", "address", "rssi"}} for bands advertising right now."""
    from bleak import BleakScanner

    found = await BleakScanner.discover(
        timeout=seconds, return_adv=True, service_uuids=[SERVICE_UUID]
    )
    bands: dict[int, dict] = {}
    for device, adv in found.values():
        name = adv.local_name or device.name or ""
        if name.startswith(NAME_PREFIX):
            try:
                number = int(name[len(NAME_PREFIX):])
            except ValueError:
                continue
            bands[number] = {"name": name, "address": device.address, "rssi": adv.rssi}
            continue
        maker = (adv.manufacturer_data or {}).get(MAKER_ID)
        if maker and len(maker) >= 4 and maker[0] == MAKER_TAG:
            number = int.from_bytes(maker[2:4], "little")
            if 1 <= number <= 999 and number not in bands:
                bands[number] = {
                    "name": _band_name(number),
                    "address": device.address,
                    "rssi": adv.rssi,
                }
    return bands


def prompt_double_tap() -> bool:
    try:
        input("Double-tap the band (its light blinks blue), then press Enter to scan again"
              " — or Ctrl+C to quit. ")
        return True
    except (EOFError, KeyboardInterrupt):
        return False


def read_band(number: int) -> dict:
    from vexo_open.sync import Band

    band = Band.connect(number)
    try:
        info = dict(band.get_info())
        battery = dict(band.get_battery())
        name = band.get_name()
    finally:
        band.disconnect()
    return {"name": name, "info": info, "battery": battery}


def led_check(number: int) -> None:
    import time

    from vexo_open.sync import Band

    band = Band.connect(number)
    try:
        for colour in ("#ff0000", "#00ff00", "#0000ff"):
            band.set_led(colour)
            time.sleep(0.6)
        band.set_led("#ffffff", pattern="blink", period=500)
        band.wait(2)
    finally:
        band.disconnect()


def show(result: dict) -> None:
    info = result["info"]
    battery = result["battery"]
    print(f"name:      {result['name']}")
    print(f"band no:   {info.get('number')}")
    print(f"firmware:  {info.get('firmware')}  protocol {info.get('protocol')}  hardware {info.get('hardware')}")
    print(f"features:  {', '.join(info.get('features') or []) or '-'}")
    print(f"caps:      {', '.join(info.get('capabilities') or [])}")
    print(f"battery:   {battery.get('percent')}% ({battery.get('millivolts')} mV, {battery.get('state')})")


async def async_main(args: argparse.Namespace) -> int:
    number = args.band
    if args.only_scan or number is None:
        while True:
            print(f"Scanning {args.scan:g}s for Vexo bands...")
            bands = await scan_bands(args.scan)
            if bands:
                for n in sorted(bands):
                    b = bands[n]
                    print(f"  {b['name']}  {b['address']}  rssi {b['rssi']}")
                if args.only_scan:
                    return 0
                if number is None:
                    if len(bands) == 1:
                        number = next(iter(bands))
                        break
                    if not sys.stdin.isatty():
                        print("More than one band nearby; pass the number you want.", file=sys.stderr)
                        return 1
                    choice = input(f"Which band? [{', '.join(map(str, sorted(bands)))}] ")
                    try:
                        number = int(choice)
                    except ValueError:
                        continue
                    if number not in bands:
                        print(f"Band {number} is not in the list.", file=sys.stderr)
                        continue
                    break
            elif args.only_scan:
                print("No Vexo band is advertising right now.")
                return 1
            else:
                print("No Vexo band found.")
                if not sys.stdin.isatty() or not prompt_double_tap():
                    return 1

    if args.led:
        led_check(number)
    result = await asyncio.to_thread(read_band, number)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        show(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Find and read a Vexo Open band.")
    parser.add_argument("band", nargs="?", type=int, help="band number, e.g. 36")
    parser.add_argument("--scan", type=float, default=8.0, help="seconds per scan (default 8)")
    parser.add_argument("--only-scan", action="store_true", help="list nearby bands and exit")
    parser.add_argument("--led", action="store_true", help="flash the LED as a control check")
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args()

    try:
        return asyncio.run(async_main(args))
    except ImportError as exc:
        print(f"Missing Python package: {exc}. Run ./setup.sh (it installs bleak).", file=sys.stderr)
        return 1
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        print(f"Could not read the band: {message}", file=sys.stderr)
        print("Double-tap the band and try again. Only one program can use it at a time.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
