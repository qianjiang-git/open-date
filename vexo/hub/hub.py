"""Hub: stands in for one person's phone. Owns their band, listens for the others.

    .venv/bin/python -m hub.hub --config config/hub-alice.local.json
    .venv/bin/python -m hub.hub --config config/hub-alice.local.json --sim --sim-tap-after 4

Config keys: server_url, hub_token, band_number, roster (authorised band numbers),
adapter ("real" or "sim"), scan (true to listen for real advertisements).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.adapters import RealBand, SimBand          # noqa: E402
from hub.band_link import RENEW_S, BandLink         # noqa: E402
from hub.client import ServerClient                 # noqa: E402
from hub.proximity import Proximity                 # noqa: E402

log = logging.getLogger("vexo.hub")


async def main(cfg: dict, sim: bool, sim_tap_after: float | None) -> None:
    number = int(cfg["band_number"])
    roster = {int(n) for n in cfg.get("roster", [])}
    adapter = SimBand(number) if sim else RealBand(number)
    link = BandLink(adapter, renew_s=float(cfg.get("renew_s", RENEW_S)), sim_tap_after=sim_tap_after)

    proximity, scanner = None, None
    if cfg.get("scan", not sim):
        from hub.scanner import Scanner
        proximity = Proximity(number, roster)
        scanner = Scanner(roster - {number}, lambda n, rssi, t: proximity.add(n, rssi, t))
        await scanner.start()
    else:
        log.info("not scanning: proximity comes from operator sightings (%s)",
                 "simulated mode" if sim else "scan disabled")

    client = ServerClient(cfg["server_url"], cfg["hub_token"], link, proximity)
    log.info("hub for band %s (%s) -> %s", number, "simulated" if sim else "real", cfg["server_url"])
    try:
        await asyncio.gather(link.run(), client.run())
    finally:
        if scanner:
            await scanner.stop()
        if adapter.connected:
            await adapter.led_off()
            await adapter.disconnect()


def cli() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="hub config JSON (written by demo/seed.py)")
    ap.add_argument("--sim", action="store_true", help="use the kit's simulated band instead of Bluetooth")
    ap.add_argument("--sim-tap-after", type=float, default=None,
                    help="simulated band taps itself this many seconds after lighting")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "bleak"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    cfg = json.loads(Path(args.config).read_text())
    sim = args.sim or cfg.get("adapter") == "sim"
    try:
        asyncio.run(main(cfg, sim, args.sim_tap_after))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli()
