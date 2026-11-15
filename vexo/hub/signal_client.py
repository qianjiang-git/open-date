"""Laptop client: poll the server for an accept/reject answer and shine the band.

    .venv/bin/python -m hub.signal_client --name kgen --band 36            # simulated band
    .venv/bin/python -m hub.signal_client --name kgen --band 36 --real     # real band over Bluetooth

Joins the hosted server by name (default kgen). --band is the band number to light.
accept -> green, reject -> red, for --shine seconds, then off.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import httpx

from .adapters import RealBand, SimBand

ROOT = Path(__file__).resolve().parent.parent
token_cache: dict = {}
COLORS = {"accept": "#00ff00", "reject": "#ff0000"}
log = logging.getLogger("vexo.signal")


async def run(server: str, name: str, band, shine: float, poll: float) -> None:
    seen = 0
    async with httpx.AsyncClient(base_url=server, timeout=60) as http:          # first call may wake a sleeping host
        while True:
            try:
                r = await http.post("/api/signal/join", json={"name": name, "token": token_cache.get("t")})
                r.raise_for_status()
                token_cache["t"] = r.json()["token"]
                break
            except httpx.HTTPError as exc:
                log.warning("cannot join (%s); retrying", exc)
                await asyncio.sleep(3)
        log.info("joined %s as %s", server, name)
        http.headers["Authorization"] = f"Bearer {token_cache['t']}"
        try:
            while True:
                try:
                    resp = await http.get("/api/signal")
                    if resp.status_code == 401:                 # server restarted: re-join and carry on
                        r = await http.post("/api/signal/join", json={"name": name})
                        r.raise_for_status()
                        token_cache["t"] = r.json()["token"]
                        http.headers["Authorization"] = f"Bearer {token_cache['t']}"
                        continue
                    resp.raise_for_status()
                    sig = resp.json().get("signal")
                    if sig and sig["seq"] > seen:
                        if not band.connected:
                            await band.connect()
                        await band.set_led(COLORS[sig["answer"]], brightness=1.0)
                        log.info("%s sent %s; band %s shines %s for %.1f seconds",
                                 sig["from"], sig["answer"], band.number, sig["answer"], shine)
                        seen = sig["seq"]
                        await asyncio.sleep(shine)
                        await band.led_off()
                        log.info("band %s light off", band.number)
                except (httpx.HTTPError, KeyError, ValueError) as exc:
                    log.warning("server error: %s", exc)
                except Exception as exc:       # retry the same answer if band link/LED fails
                    log.warning("band error: %s", exc)
                await asyncio.sleep(poll)
        finally:
            if band.connected:
                try:
                    await band.led_off()
                finally:
                    await band.disconnect()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="kgen")
    ap.add_argument("--band", type=int, default=1, help="band number to light")
    ap.add_argument("--server", default="https://vexo-match.onrender.com")
    ap.add_argument("--real", action="store_true", help="use the real band (default: simulated)")
    ap.add_argument("--shine", type=float, default=10.0)
    ap.add_argument("--poll", type=float, default=1.0)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    band = (RealBand if a.real else SimBand)(a.band)
    asyncio.run(run(a.server, a.name, band, a.shine, a.poll))


if __name__ == "__main__":
    main()
