"""Passive, roster-scoped listening for Vexo band advertisements (never connects to them).

The band number comes from manufacturer data, company 0xFFFF: [0x4F][proto][number lo][hi]
(contract section 1). Same parsing as detect.py.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

SERVICE_UUID = "254f0001-df82-4a9c-a2b5-563a0f6b2021"
MAKER_ID, MAKER_TAG = 0xFFFF, 0x4F
NAME_PREFIX = "Vexo-HACK-"

log = logging.getLogger("vexo.scanner")


def band_number(adv) -> int | None:
    maker = (adv.manufacturer_data or {}).get(MAKER_ID)
    if maker and len(maker) >= 4 and maker[0] == MAKER_TAG:
        n = int.from_bytes(bytes(maker[2:4]), "little")
        if 1 <= n <= 999:
            return n
    name = adv.local_name or ""
    if name.startswith(NAME_PREFIX):
        try:
            return int(name[len(NAME_PREFIX):])
        except ValueError:
            return None
    return None


class Scanner:
    """Calls on_sample(number, rssi, monotonic_time) for every advert from a roster band."""

    def __init__(self, roster: set, on_sample: Callable[[int, float, float], None]):
        self.roster = set(roster)
        self.on_sample = on_sample
        self.scanner = None
        self.counts: dict[int, int] = {}

    def _detected(self, device, adv) -> None:
        n = band_number(adv)
        if n is None or n not in self.roster or adv.rssi is None:
            return
        self.counts[n] = self.counts.get(n, 0) + 1
        self.on_sample(n, float(adv.rssi), time.monotonic())

    async def start(self) -> None:
        from bleak import BleakScanner
        self.scanner = BleakScanner(detection_callback=self._detected, service_uuids=[SERVICE_UUID])
        await self.scanner.start()
        log.info("scanning for roster bands %s", sorted(self.roster))

    async def stop(self) -> None:
        if self.scanner:
            await self.scanner.stop()
