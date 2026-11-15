"""Phase 0 hardware gate: does a normal disconnect reopen the advertising window?

    .venv/bin/python demo/beacon_check.py 36                  # one window, no renewal (125 s)
    .venv/bin/python demo/beacon_check.py 36 --renewals 3     # renew at 90 s, three times

Use only a band you own. Double-tap it first (blue blink), close the dashboard, then run.
Writes demo/hardware_validation.<band>.json (git-ignored) and prints a verdict:
REAL_BEACON_VERIFIED or SIMULATED_SIGHTINGS. It never claims more than it measured.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vexo-open-kit" / "python"))

from hub.scanner import SERVICE_UUID, band_number   # noqa: E402

EXPECTED_WINDOW_S = 120.0


async def connect_cycle(number: int) -> dict:
    """Connect, verify identity, read battery, disconnect. Returns timings."""
    from vexo_open import Band
    started = time.monotonic()
    band = await Band.connect(number, timeout=5)
    connected = time.monotonic()
    info = await band.get_info()
    battery = await band.get_battery()
    if int(info.get("number", -1)) != number:
        await band.disconnect()
        raise SystemExit(f"Band reports number {info.get('number')}, not {number}. Stopping.")
    await band.disconnect()
    done = time.monotonic()
    return {"connect_s": round(connected - started, 2), "cycle_s": round(done - started, 2),
            "disconnected_at": done, "firmware": info.get("firmware"),
            "battery_percent": battery.get("percent"), "battery_state": battery.get("state")}


def summarise_window(samples: list, start: float, end: float) -> dict:
    inside = [(t, r) for t, r in samples if start <= t < end]
    if not inside:
        return {"adverts": 0}
    times = [t for t, _ in inside]
    gaps = [b - a for a, b in zip(times, times[1:])]
    span = times[-1] - times[0]
    return {"adverts": len(inside),
            "first_after_disconnect_s": round(times[0] - start, 1),
            "last_after_disconnect_s": round(times[-1] - start, 1),
            "callbacks_per_s": round(len(inside) / span, 2) if span > 0 else None,
            "longest_gap_s": round(max(gaps), 1) if gaps else None,
            "rssi_median": statistics.median(r for _, r in inside),
            "rssi_min": min(r for _, r in inside), "rssi_max": max(r for _, r in inside)}


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("band", type=int, help="the number of a band you own")
    ap.add_argument("--renewals", type=int, default=0, help="renew this many times (0 = watch one window expire)")
    ap.add_argument("--renew-at", type=float, default=90.0, help="seconds after a disconnect to renew")
    ap.add_argument("--watch", type=float, default=EXPECTED_WINDOW_S + 5, help="seconds to watch the last window")
    args = ap.parse_args()

    from bleak import BleakScanner
    samples: list = []

    def seen(device, adv):
        if band_number(adv) == args.band and adv.rssi is not None:
            samples.append((time.monotonic(), float(adv.rssi)))

    scanner = BleakScanner(detection_callback=seen, service_uuids=[SERVICE_UUID])
    print(f"Connecting to band {args.band} (double-tap it if this fails)…")
    cycles = [await connect_cycle(args.band)]
    print(f"  connected in {cycles[0]['connect_s']} s, battery {cycles[0]['battery_percent']}% "
          f"({cycles[0]['battery_state']}), firmware {cycles[0]['firmware']}")
    await scanner.start()
    try:
        for i in range(args.renewals):
            wait = cycles[-1]["disconnected_at"] + args.renew_at - time.monotonic()
            print(f"Watching; renewal {i + 1}/{args.renewals} in {wait:.0f} s…")
            await asyncio.sleep(max(0, wait))
            await scanner.stop()                  # avoid racing our own connect on some stacks
            try:
                cycles.append(await connect_cycle(args.band))
            except Exception as exc:
                print(f"  renewal failed: {type(exc).__name__}: {exc}")
                break
            finally:
                await scanner.start()
            print(f"  renewed (connect {cycles[-1]['connect_s']} s)")
        print(f"Watching the last window for {args.watch:.0f} s without renewing…")
        await asyncio.sleep(max(0, cycles[-1]["disconnected_at"] + args.watch - time.monotonic()))
    finally:
        await scanner.stop()

    windows = []
    for i, c in enumerate(cycles):
        end = cycles[i + 1]["disconnected_at"] if i + 1 < len(cycles) else c["disconnected_at"] + args.watch
        windows.append({**{k: v for k, v in c.items() if k != "disconnected_at"},
                        **summarise_window(samples, c["disconnected_at"], end)})

    last = windows[-1]
    window_ok = last.get("adverts", 0) > 0 and (last.get("last_after_disconnect_s") or 0) >= 100
    stops_ok = (last.get("last_after_disconnect_s") or 0) <= EXPECTED_WINDOW_S + 5
    renew_ok = all(w.get("adverts", 0) > 0 for w in windows)
    rssi_ok = (last.get("callbacks_per_s") or 0) >= 0.5
    verdict = "REAL_BEACON_VERIFIED" if (window_ok and renew_ok and rssi_ok) else "SIMULATED_SIGHTINGS"
    report = {"band": args.band, "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "verdict": verdict,
              "checks": {"window_lasts_100s_without_tap": window_ok, "window_stops_near_120s": stops_ok,
                         "every_renewal_reopened_window": renew_ok, "repeated_rssi_callbacks": rssi_ok},
              "windows": windows}
    out = ROOT / "demo" / f"hardware_validation.{args.band}.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"\nVerdict: {verdict}  (saved to {out.relative_to(ROOT)})")
    if verdict != "REAL_BEACON_VERIFIED":
        print("Use the simulated demo mode, and say so in the demo. Do not count this as radio proximity.")


if __name__ == "__main__":
    asyncio.run(main())
