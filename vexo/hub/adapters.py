"""Band adapters: the real band over Bluetooth, or the kit's simulated band.

Both use the kit's async `Band` class; only the transport differs. The simulator's
`set_rssi` affects its own link stream only: it does NOT broadcast an advertisement, so
cross-person discovery in simulated mode comes from operator sightings, never from here.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable

KIT = Path(__file__).resolve().parent.parent / "vexo-open-kit" / "python"
sys.path.insert(0, str(KIT))

log = logging.getLogger("vexo.band")


class BandAdapter:
    advertises = True          # False for the simulator: renewal is pointless there

    def __init__(self, number: int):
        self.number = number
        self.band = None
        self._on_tap: Callable | None = None
        self._on_drop: Callable | None = None

    @property
    def connected(self) -> bool:
        return self.band is not None and bool(getattr(self.band, "connected", True))

    def _transport(self):
        return "ble"

    async def connect(self) -> None:
        from vexo_open import Band
        band = await Band.connect(self.number, transport=self._transport(), timeout=5)
        info = await band.get_info()
        if int(info.get("number", -1)) != self.number:
            await band.disconnect()
            raise RuntimeError(f"connected band reports number {info.get('number')}, expected {self.number}")
        band.on("disconnect", self._dropped)
        self.band = band

    def _dropped(self, event=None) -> None:
        log.warning("band %s link dropped: %s", self.number, event)
        self.band = None
        if self._on_drop:
            self._on_drop()

    def on_drop(self, handler: Callable) -> None:
        self._on_drop = handler

    async def set_led(self, color: str, pattern: str = "solid", brightness: float = 0.6, period: int = 1000) -> None:
        await self.band.set_led(color, brightness=brightness, pattern=pattern, period=period)

    async def enable_taps(self, handler: Callable) -> None:
        self._on_tap = handler
        self.band.on("tap", lambda e: handler(e))
        await self.band.configure(events=True)

    async def led_off(self) -> None:
        if self.band is not None:
            await self.band.led_off()

    async def disconnect(self) -> None:
        band, self.band = self.band, None
        if band is not None:
            band.off("disconnect", self._dropped)     # a deliberate disconnect is not a drop
            await band.disconnect()

    async def battery(self) -> int | None:
        if self.band is None:
            return None
        try:
            return int((await self.band.get_battery()).get("percent"))
        except Exception:
            return None


class RealBand(BandAdapter):
    pass


class SimBand(BandAdapter):
    """The kit's pretend band. `tap()` makes the band report a tap, like a wrist tap."""
    advertises = False

    def __init__(self, number: int):
        super().__init__(number)
        self.led_log: list = []

    def _transport(self):
        from vexo_open import SimTransport
        return SimTransport(self.number, auto_tap=False, on_led=self._led)

    def _led(self, led) -> None:
        self.led_log.append(led)
        log.info("[sim band %s] LED %s", self.number, led)

    def tap(self) -> bool:
        if self.band is None:
            return False
        return bool(self.band.transport.tap("tap"))
